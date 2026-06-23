"""
主入口 — 全局热键注册、QThread 任务编排、应用生命周期管理

支持多显示器+高DPI：截图使用物理像素，显示和交互使用逻辑像素。
退出方式：系统托盘右键菜单、Ctrl+Shift+Q、终端 Ctrl+C
"""

import sys
import ctypes
from ctypes import Structure, c_void_p, c_uint, c_ulonglong, c_longlong, c_ulong, c_long, sizeof, cast, POINTER
import traceback

# 确保控制台使用 UTF-8 编码（noconsole 模式下 stdout/stderr 为 None）
try:
    if sys.stdout is not None and sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass
try:
    if sys.stderr is not None and sys.stderr.encoding != 'utf-8':
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

import mss
import numpy as np
from PIL import Image

from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QLabel, QWidget, QVBoxLayout,
    QSystemTrayIcon, QMenu, QDialog,
)
from PyQt6.QtCore import (
    Qt, QThread, QObject, pyqtSignal, QRect,
    QAbstractNativeEventFilter, QTimer,
)
from PyQt6.QtGui import QFont, QIcon, QAction, QImage, QPixmap, QKeySequence

from config import (
    FONT_FAMILY, FONT_SIZE, HOTKEY_ID,
    MOD_CONTROL, MOD_SHIFT, MOD_ALT,
)
import config  # 用于调用 config.update_from_settings()
from screen_capture import ScreenCaptureWidget
from ocr_engine import LlamaServerManager, OCREngine
from translator import Translator
from overlay import TextOverlay
import settings_manager
from settings_dialog import SettingsDialog
from main_window import MainWindow


# 退出热键 ID（不同 ID 避免冲突）
HOTKEY_ID_EXIT = 2

OCR_ENGINE_NOT_READY_MSG = "OCR 引擎未就绪\n请打开托盘菜单 → 设置 → 手动启动 OCR 服务器"


# ======================================================================
# 启动状态窗口
# ======================================================================

class StatusWindow(QWidget):
    """应用启动时的状态窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setFixedSize(340, 100)
        self._center_on_screen()

        self._label = QLabel("正在启动 OCR 服务...", self)
        self._label.setFont(QFont(FONT_FAMILY, 13))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)

    def set_status(self, text: str):
        self._label.setText(text)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )


# ======================================================================
# Windows MSG 结构体
# ======================================================================

_ULONG_PTR = c_ulonglong if sizeof(c_void_p) == 8 else c_ulong
_LONG_PTR = c_longlong if sizeof(c_void_p) == 8 else c_long


class _WinMSG(Structure):
    _fields_ = [
        ("hwnd", c_void_p),
        ("message", c_uint),
        ("wParam", _ULONG_PTR),
        ("lParam", _LONG_PTR),
        ("time", c_ulong),
        ("pt_x", c_long),
        ("pt_y", c_long),
    ]


# ======================================================================
# 全局热键过滤器
# ======================================================================

class GlobalHotkeyFilter(QAbstractNativeEventFilter):
    """通过 Windows WM_HOTKEY 消息触发全局快捷键回调"""

    WM_HOTKEY = 0x0312

    def __init__(self):
        super().__init__()
        self._hotkey_callbacks: dict[int, callable] = {}

    def add_handler(self, hotkey_id: int, callback: callable):
        self._hotkey_callbacks[hotkey_id] = callback

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = _WinMSG.from_address(int(message))
            if msg.message == self.WM_HOTKEY:
                cb = self._hotkey_callbacks.get(msg.wParam)
                if cb:
                    cb()
                    return True, 0
        return False, 0


# ======================================================================
# 工作线程
# ======================================================================

class OCRWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, engine: OCREngine, image: Image.Image):
        super().__init__()
        self._engine = engine
        self._image = image

    def run(self):
        try:
            text = self._engine.extract_text(self._image)
            self.finished.emit(text)
        except Exception as e:
            self.error.emit(str(e))


class TranslateWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, translator: Translator, text: str):
        super().__init__()
        self._translator = translator
        self._text = text

    def run(self):
        try:
            result = self._translator.translate(self._text)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ======================================================================
# 主应用
# ======================================================================

class App(QApplication):
    """OCR 翻译应用 — 全局热键 → 框选 → OCR/翻译 → 悬浮显示"""

    def __init__(self, argv):
        super().__init__(argv)
        self.setFont(QFont(FONT_FAMILY, FONT_SIZE))

        # 系统托盘应用：禁止最后一个窗口关闭时退出应用
        self.setQuitOnLastWindowClosed(False)

        # 核心组件
        self._server: LlamaServerManager | None = None
        self._ocr_engine: OCREngine | None = None
        self._translator: Translator | None = None
        self._capture_widgets: list[ScreenCaptureWidget] = []

        # 线程引用
        self._threads: list[QThread] = []

        # 加载用户设置
        self._settings = settings_manager.load_settings()

        # 热键过滤器
        self._hotkey_filter = GlobalHotkeyFilter()
        self.installNativeEventFilter(self._hotkey_filter)

        # 翻译器（不依赖本地模型，始终可用）
        self._translator = Translator()

        # 主窗口（必须在 _init_server 之前创建，因为 _init_server 会引用 _main_window）
        self._main_window = MainWindow()

        # 根据设置决定是否自动启动 OCR 本地模型
        if self._settings.get("auto_start_ocr", False):
            try:
                self._init_server(
                    show_status=not self._settings.get("hide_on_startup", False),
                    exit_on_fail=False,
                )
            except Exception as e:
                print(f"[App] Auto-start OCR failed: {e}")
                self._settings["auto_start_ocr"] = False
                settings_manager.save_settings(self._settings)
                QMessageBox.warning(
                    None, "OCR 自动启动失败",
                    f"自动启动 OCR 服务器失败，已自动关闭该选项。\n"
                    f"请打开设置检查路径配置后手动启动。\n\n"
                    f"错误: {e}",
                )
        else:
            print("[App] OCR auto-start is disabled — 可通过设置手动启动")

        # 注册热键 — 从用户设置加载快捷键
        self._hotkey_mod, self._hotkey_vk = self._parse_keyseq(
            self._settings.get("hotkey", "Ctrl+Shift+S")
        )
        self._hotkey_str = self._settings.get("hotkey", "Ctrl+Shift+S")
        self._register_hotkey(HOTKEY_ID, self._hotkey_mod, self._hotkey_vk, self._on_hotkey, self._hotkey_str)
        self._register_hotkey(HOTKEY_ID_EXIT, MOD_CONTROL | MOD_SHIFT, ord('Q'), self._on_quit_hotkey, "Ctrl+Shift+Q")

        # 同步热键提示到主窗口托盘（此时 _main_window 已创建）
        self._main_window.update_hotkey_hint(self._hotkey_str)

        # 系统托盘
        self._tray: QSystemTrayIcon | None = None
        self._init_tray()

        # 主窗口 UI 绑定与显示
        self._main_window.settings_btn.clicked.connect(self._open_settings)
        self._main_window.start_btn.clicked.connect(self._main_window_toggle_server)
        self._main_window.quit_btn.clicked.connect(self.quit)
        if not self._settings.get("hide_on_startup", False):
            self._main_window.show()

        # 如果服务器已在_init_server中启动，更新主窗口状态
        if self._server is not None and self._server.is_running:
            self._main_window.set_server_status(True)

        # 退出清理
        self.aboutToQuit.connect(self._cleanup)

    # ------------------------------------------------------------------
    # 服务器初始化
    # ------------------------------------------------------------------
    def _init_server(self, show_status: bool = True, exit_on_fail: bool = True):
        """启动 llama-server 并等待就绪

        Args:
            show_status: 是否显示启动状态窗口
            exit_on_fail: 启动失败时是否退出进程（True=自动启动时退出，False=手动启动时不退出）
        """
        status = None
        if show_status:
            status = StatusWindow()
            status.set_status("正在启动 OCR 服务 (llama-server)...\n首次加载可能需要 10-30 秒")
            status.show()
            self.processEvents()

        try:
            self._server = LlamaServerManager()
            self._server.start()

            self._ocr_engine = OCREngine(self._server)
            # _translator 已在 __init__ 中创建，这里不再重复创建

            if status:
                status.hide()
                status.deleteLater()

            self._main_window.set_server_status(True)
            print("[App] 所有服务就绪")
        except Exception as e:
            if status:
                status.hide()
                status.deleteLater()

            if exit_on_fail and self._settings.get("auto_start_ocr", False):
                QMessageBox.critical(
                    None, "启动失败",
                    f"无法启动 OCR 服务:\n\n{e}\n\n"
                    f"请检查模型文件路径和 llama-server 配置。",
                )
                sys.exit(1)
            raise  # 手动启动时向上抛，由调用者处理

    # ------------------------------------------------------------------
    # 系统托盘
    # ------------------------------------------------------------------
    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("[App] 系统托盘不可用")
            return

        self._tray = QSystemTrayIcon(self)
        # 创建一个简单的图标（16x16 蓝色方块）
        icon_img = QImage(16, 16, QImage.Format.Format_RGB32)
        icon_img.fill(Qt.GlobalColor.darkCyan)
        self._tray.setIcon(QIcon(QPixmap.fromImage(icon_img)))
        self._tray.setToolTip("OCR 翻译工具\nCtrl+Shift+S 截图\nCtrl+Shift+Q 退出")

        menu = QMenu()
        menu.setStyleSheet(
            "QMenu { font-size: 12px; padding: 4px; background: white; border: 1px solid #ccc; }"
            "QMenu::item { padding: 4px 20px 4px 8px; }"
            "QMenu::item:selected { background: #e0e0e0; }"
        )

        show_action = QAction("🏠 显示主界面", self)
        show_action.triggered.connect(lambda: self._main_window.show())
        menu.addAction(show_action)

        settings_action = QAction("⚙ 设置", self)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.quit)
        menu.addAction(exit_action)

        self._tray.setContextMenu(menu)

        # 左键点击 → 显示主窗口
        self._tray.activated.connect(self._on_tray_activated)

        self._tray.show()
        if not self._settings.get("hide_on_startup", False):
            self._tray.showMessage(
                "OCR 翻译工具",
                "已启动，使用 Ctrl+Shift+S 截图\n右键托盘图标可退出程序",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

        print("[App] 系统托盘已创建 — 右键托盘 → 显示/设置/退出")

    # ------------------------------------------------------------------
    # 托盘图标点击
    # ------------------------------------------------------------------
    def _on_tray_activated(self, reason):
        """左键/双击托盘 → 显示主窗口"""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._main_window.show()
            self._main_window.raise_()
            self._main_window.activateWindow()

    # ------------------------------------------------------------------
    # 全局热键
    # ------------------------------------------------------------------
    def _register_hotkey(self, hotkey_id: int, modifiers: int, vk: int, callback: callable, name: str):
        user32 = ctypes.windll.user32
        ok = user32.RegisterHotKey(None, hotkey_id, modifiers, vk)
        if ok:
            print(f"[App] 热键 {name} 已注册")
        else:
            print(f"[App] 热键 {name} 注册失败")

        self._hotkey_filter.add_handler(hotkey_id, callback)

    # ------------------------------------------------------------------
    # 热键字符串 → WM_HOTKEY modifiers + vk
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_keyseq(keyseq_str: str) -> tuple[int, int]:
        """将 'Ctrl+Shift+S' 转换为 (modifiers, vk) 用于 Win32 RegisterHotKey"""
        ks = QKeySequence(keyseq_str)
        if not ks.count():
            return MOD_CONTROL | MOD_SHIFT, ord('S')  # fallback
        kc = ks[0]
        m = kc.keyboardModifiers()
        k = kc.key()

        win_mod = 0
        if m & Qt.KeyboardModifier.ControlModifier:
            win_mod |= MOD_CONTROL
        if m & Qt.KeyboardModifier.ShiftModifier:
            win_mod |= MOD_SHIFT
        if m & Qt.KeyboardModifier.AltModifier:
            win_mod |= MOD_ALT

        # 必须至少有一个修饰键
        if not win_mod:
            return MOD_CONTROL | MOD_SHIFT, ord('S')

        # 功能键映射表
        fkey_map = {
            Qt.Key.Key_F1: 0x70, Qt.Key.Key_F2: 0x71,
            Qt.Key.Key_F3: 0x72, Qt.Key.Key_F4: 0x73,
            Qt.Key.Key_F5: 0x74, Qt.Key.Key_F6: 0x75,
            Qt.Key.Key_F7: 0x76, Qt.Key.Key_F8: 0x77,
            Qt.Key.Key_F9: 0x78, Qt.Key.Key_F10: 0x79,
            Qt.Key.Key_F11: 0x7A, Qt.Key.Key_F12: 0x7B,
        }
        vk = fkey_map.get(k, k)
        return win_mod, vk

    # ------------------------------------------------------------------
    # 热键回调
    # ------------------------------------------------------------------
    def _on_hotkey(self):
        # 如果有任何一个 widget 正在显示，忽略本次触发
        if any(w.isVisible() for w in self._capture_widgets):
            return

        # 关闭所有打开的模态对话框（如设置窗口），避免浮于截图上层
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible():
                w.reject()

        try:
            self._capture_widgets = []

            with mss.mss() as sct:
                monitor_infos = sct.monitors[1:]  # 跳过 virtual (index 0)
                for mon_info in monitor_infos:
                    shot = sct.grab(mon_info)
                    arr = np.array(shot, dtype=np.uint8)

                    widget = ScreenCaptureWidget(arr, mon_info)
                    widget.action_triggered.connect(self._on_action)
                    widget.cancelled.connect(self._on_cancel)
                    widget.showNormal()
                    widget.raise_()
                    widget.activateWindow()
                    self._capture_widgets.append(widget)

        except Exception as e:
            traceback.print_exc()
            QMessageBox.warning(None, "截图失败", f"无法截取屏幕:\n{e}")

    def _on_quit_hotkey(self):
        print("[App] Ctrl+Shift+Q — 退出程序")
        self.quit()

    # ------------------------------------------------------------------
    # 用户操作回调
    # ------------------------------------------------------------------
    def _on_action(self, logical_rect: QRect, physical_rect: QRect, screenshot_np: np.ndarray, action: str):
        # 关闭所有采集 widget
        self._close_all_capture_widgets()

        try:
            roi_image = ScreenCaptureWidget.crop_region(screenshot_np, physical_rect)
        except Exception as e:
            self._show_error(f"裁切图像失败: {e}")
            return

        if action == "extract":
            self._run_ocr(roi_image, logical_rect, roi_image)
        elif action == "translate":
            self._run_ocr_then_translate(roi_image, logical_rect, roi_image)

    def _on_cancel(self):
        self._close_all_capture_widgets()

    def _close_all_capture_widgets(self):
        for w in self._capture_widgets:
            try:
                w.hide()
                w.close()
            except RuntimeError:
                pass  # 可能已被垃圾回收
        self._capture_widgets = []

    # ------------------------------------------------------------------
    # 设置对话框
    # ------------------------------------------------------------------
    def _open_settings(self):
        """打开设置对话框（模态），用户保存后刷新配置"""
        # 临时注销截图热键，避免干扰 QKeySequenceEdit 捕获按键
        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(None, HOTKEY_ID)

        dialog = SettingsDialog(
            parent=None,
            server_running=self._server is not None and self._server.is_running,
        )
        # 连接启停信号（对话框不关闭，实时触发）
        dialog.server_toggle_requested.connect(self._on_settings_toggle)
        result = dialog.exec()

        # 对话框关闭后刷新配置
        new_settings = settings_manager.load_settings()
        config.update_from_settings(new_settings)
        self._settings = new_settings

        # 重新注册截图热键（用更新后的设置）
        hotkey_str = self._settings.get("hotkey", "Ctrl+Shift+S")
        self._hotkey_mod, self._hotkey_vk = self._parse_keyseq(hotkey_str)
        self._register_hotkey(HOTKEY_ID, self._hotkey_mod, self._hotkey_vk, self._on_hotkey, hotkey_str)
        self._hotkey_str = hotkey_str

        if result == QDialog.DialogCode.Accepted:
            print("[App] Settings saved")
            config.reload_env()

        # 同步热键提示到 UI（无论保存与否，确保显示一致）
        self._main_window.update_hotkey_hint(self._hotkey_str)
        self._tray.setToolTip(
            f"OCR 翻译工具\n{self._hotkey_str} 截图\n"
            f"Ctrl+Shift+Q 退出\n右键托盘 → 显示/设置/退出"
        )

    def _on_settings_toggle(self, action: str):
        """设置对话框的启停按钮触发的实时操作"""
        if action == "start":
            try:
                self._init_server(show_status=False, exit_on_fail=False)
                self._main_window.set_server_status(True)
            except Exception as e:
                QMessageBox.critical(None, "启动失败", f"OCR 服务器启动失败:\n{e}")
        elif action == "stop":
            if self._server is None:
                return
            try:
                self._server.stop()
                self._ocr_engine = None
                self._main_window.set_server_status(False)
            except Exception as e:
                QMessageBox.critical(None, "停止失败", f"OCR 服务器停止失败:\n{e}")

    def _main_window_toggle_server(self):
        """主窗口按钮：启动/停止切换"""
        if self._server and self._server.is_running:
            try:
                self._server.stop()
                self._ocr_engine = None
                self._main_window.set_server_status(False)
            except Exception as e:
                QMessageBox.critical(
                    None, "停止失败", f"OCR 服务器停止失败:\n{e}"
                )
        else:
            try:
                self._init_server(show_status=False, exit_on_fail=False)
                self._main_window.set_server_status(True)
            except Exception as e:
                QMessageBox.critical(
                    None, "启动失败", f"OCR 服务器启动失败:\n{e}"
                )

    # ------------------------------------------------------------------
    # OCR 流水线
    # ------------------------------------------------------------------
    def _run_ocr(self, image: Image.Image, rect: QRect, roi_image: Image.Image | None = None):
        if self._ocr_engine is None:
            self._show_error(OCR_ENGINE_NOT_READY_MSG)
            return

        self._loading = StatusWindow()
        self._loading.set_status("正在识别文字...")
        self._loading.show()
        self.processEvents()

        thread = QThread()
        worker = OCRWorker(self._ocr_engine, image)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def on_finished(text: str):
            self._loading.hide()
            self._loading.deleteLater()
            self._show_overlay(text, rect, roi_image)
            self._cleanup_thread(thread, worker)

        def on_error(err: str):
            self._loading.hide()
            self._loading.deleteLater()
            self._show_error(f"OCR 失败:\n{err}")
            self._cleanup_thread(thread, worker)

        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        self._threads.append(thread)
        thread.start()

    def _run_ocr_then_translate(self, image: Image.Image, rect: QRect, roi_image: Image.Image | None = None):
        if self._ocr_engine is None:
            self._show_error(OCR_ENGINE_NOT_READY_MSG)
            return
        if self._translator is None:
            self._show_error("翻译器未就绪")
            return

        self._loading = StatusWindow()
        self._loading.set_status("正在识别文字...")
        self._loading.show()
        self.processEvents()

        thread1 = QThread()
        worker1 = OCRWorker(self._ocr_engine, image)
        worker1.moveToThread(thread1)

        def on_ocr_finished(text: str):
            self._loading.set_status("正在翻译...")
            self.processEvents()

            thread2 = QThread()
            worker2 = TranslateWorker(self._translator, text)
            worker2.moveToThread(thread2)

            def on_translate_finished(translated: str):
                self._loading.hide()
                self._loading.deleteLater()
                self._show_overlay(translated, rect, roi_image)
                self._cleanup_thread(thread1, worker1)
                self._cleanup_thread(thread2, worker2)

            def on_translate_error(err: str):
                self._loading.hide()
                self._loading.deleteLater()
                self._show_overlay(f"（翻译失败: {err}）\n\n{text}", rect, roi_image)
                self._cleanup_thread(thread1, worker1)
                self._cleanup_thread(thread2, worker2)

            thread2.started.connect(worker2.run)
            worker2.finished.connect(on_translate_finished)
            worker2.error.connect(on_translate_error)
            worker2.finished.connect(thread2.quit)
            worker2.error.connect(thread2.quit)
            self._threads.append(thread2)
            thread2.start()

        def on_ocr_error(err: str):
            self._loading.hide()
            self._loading.deleteLater()
            self._show_error(f"OCR 失败:\n{err}")
            self._cleanup_thread(thread1, worker1)

        thread1.started.connect(worker1.run)
        worker1.finished.connect(on_ocr_finished)
        worker1.error.connect(on_ocr_error)
        worker1.finished.connect(thread1.quit)
        worker1.error.connect(thread1.quit)
        self._threads.append(thread1)
        thread1.start()

    # ------------------------------------------------------------------
    # 结果展示
    # ------------------------------------------------------------------
    def _show_overlay(self, text: str, rect: QRect, roi_image: Image.Image | None = None):
        overlay = TextOverlay(text, rect, roi_image)
        overlay.show()

    # ------------------------------------------------------------------
    # 错误处理
    # ------------------------------------------------------------------
    def _show_error(self, message: str):
        QMessageBox.warning(None, "错误", message)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------
    def _cleanup_thread(self, thread: QThread, worker: QObject):
        worker.deleteLater()
        thread.deleteLater()
        if thread in self._threads:
            self._threads.remove(thread)

    def _cleanup(self):
        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(None, HOTKEY_ID)
        user32.UnregisterHotKey(None, HOTKEY_ID_EXIT)

        if self._server is not None:
            self._server.stop()
            self._server = None

        print("[App] 已退出")


# ======================================================================
# 入口
# ======================================================================
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = App(sys.argv)

    print("=" * 50)
    print("  OCR 翻译工具")
    print("  ---------------------------------")
    print(f"  {config.HOTKEY_STR}  截图 & 识别/翻译")
    print("  Ctrl+Shift+Q  退出程序")
    print("  右键托盘图标  退出程序")
    print("=" * 50)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

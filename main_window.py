"""
主窗口 — 应用主界面

启动时默认显示，system tray 右键也可调出。
显示服务器状态、快捷键提示，并提供设置/启动/退出按钮。
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class MainWindow(QWidget):
    """应用主窗口 — 非模态，关闭时隐藏到托盘"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OCR 翻译工具")
        self.setFixedSize(420, 300)
        self.setWindowFlags(
            Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )

        self._server_status = "未启动"
        self._setup_ui()
        self._center_on_screen()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ── 标题 ──
        title = QLabel("OCR 翻译工具")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont("微软雅黑", 16)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color: #4285F4;")
        layout.addWidget(title)

        # ── 分隔线 ──
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #CCC;")
        layout.addWidget(line)

        # ── 状态区域 ──
        self._status_label = QLabel()
        self._status_label.setFont(QFont("微软雅黑", 11))
        self._status_label.setWordWrap(True)
        self._update_status_text()
        layout.addWidget(self._status_label)

        layout.addStretch()

        # ── 按钮区域 ──
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self._settings_btn = QPushButton("⚙ 设置")
        self._settings_btn.setFixedHeight(36)
        self._settings_btn.setStyleSheet(self._btn_style("#4285F4"))
        btn_layout.addWidget(self._settings_btn)

        self._start_btn = QPushButton("▶ 手动启动 OCR")
        self._start_btn.setFixedHeight(36)
        self._start_btn.setStyleSheet(self._btn_style("#34A853"))
        btn_layout.addWidget(self._start_btn)

        self._quit_btn = QPushButton("退出")
        self._quit_btn.setFixedHeight(36)
        self._quit_btn.setStyleSheet(self._btn_style("#EA4335"))
        btn_layout.addWidget(self._quit_btn)

        layout.addLayout(btn_layout)

        # ── 快捷键提示 ──
        self._hint_label = QLabel(
            "快捷键:\n"
            "  Ctrl+Shift+S  →  截图 & 识别/翻译\n"
            "  Ctrl+Shift+Q  →  退出程序"
        )
        self._hint_label.setFont(QFont("微软雅黑", 10))
        self._hint_label.setStyleSheet("color: #888;")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint_label)

    @staticmethod
    def _btn_style(color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
            }}
            QPushButton:pressed {{
                background-color: {color}aa;
            }}
            QPushButton:disabled {{
                background-color: #CCC;
            }}
        """

    # ------------------------------------------------------------------
    # 状态更新
    # ------------------------------------------------------------------
    def set_server_status(self, running: bool):
        self._server_status = "运行中" if running else "未启动"
        self._update_status_text()
        self._start_btn.setEnabled(True)
        self._start_btn.setText("■ 停止 OCR" if running else "▶ 启动 OCR")
        if running:
            self._start_btn.setStyleSheet(self._btn_style("#EA4335"))  # 红色 = 停止
        else:
            self._start_btn.setStyleSheet(self._btn_style("#34A853"))  # 绿色 = 启动

    def _update_status_text(self):
        self._status_label.setText(
            f"OCR 服务器：{self._server_status}\n"
            f"DeepSeek API：已配置"
        )

    # ------------------------------------------------------------------
    # 热键提示同步
    # ------------------------------------------------------------------
    def update_hotkey_hint(self, hotkey_str: str):
        """更新主界面的快捷键提示文字"""
        self._hint_label.setText(
            f"快捷键:\n"
            f"  {hotkey_str}  →  截图 & 识别/翻译\n"
            f"  Ctrl+Shift+Q  →  退出程序"
        )

    # ------------------------------------------------------------------
    # 按钮信号暴露（供 main.py 连接）
    # ------------------------------------------------------------------
    @property
    def settings_btn(self) -> QPushButton:
        return self._settings_btn

    @property
    def start_btn(self) -> QPushButton:
        return self._start_btn

    @property
    def quit_btn(self) -> QPushButton:
        return self._quit_btn

    # ------------------------------------------------------------------
    # 窗口管理
    # ------------------------------------------------------------------
    def _center_on_screen(self):
        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )

    def closeEvent(self, event):
        """点击关闭按钮时隐藏到托盘，不退出"""
        event.ignore()
        self.hide()

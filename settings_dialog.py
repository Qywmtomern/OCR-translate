"""
设置对话框 — 配置路径、API 密钥、CUDA 检测、启动选项

出口属性:
    manual_start_requested: bool  — 用户是否点击了"手动启动"
"""

import os
import re
import shutil
import subprocess

# noconsole 模式下隐藏子进程命令行窗口
_HIDE_WINDOW = subprocess.STARTUPINFO()
_HIDE_WINDOW.dwFlags |= subprocess.STARTF_USESHOWWINDOW
_HIDE_WINDOW.wShowWindow = subprocess.SW_HIDE

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QGridLayout,
    QKeySequenceEdit,
)
from PyQt6.QtCore import Qt, QTimer, QThread, QObject, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence

import config
import settings_manager


class SettingsDialog(QDialog):
    """应用程序设置"""

    # 服务器启停请求信号（main.py 连接此信号执行实际启停）
    server_toggle_requested = pyqtSignal(str)  # "start" | "stop"

    def __init__(self, parent=None, server_running: bool = False):
        super().__init__(parent)
        self._settings = settings_manager.load_settings()
        self._server_running = server_running

        # 服务器动作标志 —— "start" / "stop" / None
        self.server_action: str | None = None

        self.setWindowTitle("⚙ 设置")
        self.setMinimumWidth(640)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        # 设置窗口字体比全局小 3px
        self.setFont(QFont(config.FONT_FAMILY, config.FONT_SIZE - 3))
        self._setup_ui()
        self._load_values()

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ----------------------------------------------------------------
        # OCR 模型路径组
        # ----------------------------------------------------------------
        grp_ocr = QGroupBox("OCR 模型设置")
        g = QGridLayout(grp_ocr)
        g.setVerticalSpacing(8)

        g.addWidget(QLabel("模型文件:"), 0, 0)
        self._model_path = QLineEdit()
        self._model_path.setPlaceholderText("PaddleOCR-VL GGUF 模型路径")
        g.addWidget(self._model_path, 0, 1)
        btn = QPushButton("浏览...")
        btn.clicked.connect(self._browse_model)
        g.addWidget(btn, 0, 2)

        g.addWidget(QLabel("mmproj:"), 1, 0)
        self._mmproj_path = QLineEdit()
        self._mmproj_path.setPlaceholderText("mmproj 投影文件路径")
        g.addWidget(self._mmproj_path, 1, 1)
        btn = QPushButton("浏览...")
        btn.clicked.connect(self._browse_mmproj)
        g.addWidget(btn, 1, 2)

        g.addWidget(QLabel("llama-server:"), 2, 0)
        self._server_exe = QLineEdit()
        self._server_exe.setPlaceholderText("llama-server.exe 路径")
        g.addWidget(self._server_exe, 2, 1)
        btn = QPushButton("浏览...")
        btn.clicked.connect(self._browse_server)
        g.addWidget(btn, 2, 2)

        layout.addWidget(grp_ocr)

        # ----------------------------------------------------------------
        # DeepSeek API 组
        # ----------------------------------------------------------------
        grp_api = QGroupBox("DeepSeek API 设置")
        g = QGridLayout(grp_api)
        g.setVerticalSpacing(8)
        g.setColumnStretch(0, 0)
        g.setColumnStretch(1, 2)   # 输入框列分配宽度（约原来的 2x）
        g.setColumnStretch(2, 1)   # 右侧空白吸收多余空间

        g.addWidget(QLabel("API Key:"), 0, 0)
        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        g.addWidget(self._api_key, 0, 1)

        g.addWidget(QLabel("Base URL:"), 1, 0)
        self._base_url = QLineEdit()
        self._base_url.setPlaceholderText("https://api.deepseek.com")
        g.addWidget(self._base_url, 1, 1)

        # API 连接测试
        self._api_test_btn = QPushButton("测试连接")
        self._api_test_btn.setFixedWidth(100)
        self._api_test_btn.setStyleSheet(
            "QPushButton { background:#34A853; color:white; border:none; border-radius:4px; font-size:11px; padding:4px 0; }"
            "QPushButton:hover { background:#2d8f47; }"
            "QPushButton:disabled { background:#CCC; }"
        )
        self._api_test_btn.clicked.connect(self._test_api_connection)
        g.addWidget(self._api_test_btn, 0, 2, 2, 1, Qt.AlignmentFlag.AlignCenter)

        self._api_test_label = QLabel("")
        self._api_test_label.setStyleSheet("color: gray; font-size: 11px;")
        g.addWidget(self._api_test_label, 2, 1, 1, 2)

        layout.addWidget(grp_api)

        # ----------------------------------------------------------------
        # CUDA 检测
        # ----------------------------------------------------------------
        cuda_row = QHBoxLayout()
        cuda_row.addWidget(QLabel("CUDA 状态:"))
        self._cuda_label = QLabel("未检测")
        self._cuda_label.setStyleSheet("color: gray; font-size: 11px;")
        cuda_row.addWidget(self._cuda_label)
        btn_cuda = QPushButton("检测 CUDA")
        btn_cuda.clicked.connect(self._check_cuda)
        cuda_row.addWidget(btn_cuda)
        cuda_row.addStretch()
        layout.addLayout(cuda_row)

        # ----------------------------------------------------------------
        # 启动选项
        # ----------------------------------------------------------------
        grp_opt = QGroupBox("启动选项")
        opt = QVBoxLayout(grp_opt)

        row = QHBoxLayout()
        self._auto_start_cb = QCheckBox("自动启动 OCR 模型（下次启动生效）")
        row.addWidget(self._auto_start_cb)

        self._manual_btn = QPushButton("手动启动 OCR 服务器")
        self._manual_btn.setFixedWidth(180)
        self._manual_btn.clicked.connect(self._on_manual_start)
        row.addWidget(self._manual_btn)
        row.addStretch()
        opt.addLayout(row)

        self._hide_cb = QCheckBox("启动时隐藏主界面（仅托盘图标）")
        opt.addWidget(self._hide_cb)

        hk_row = QHBoxLayout()
        hk_row.addWidget(QLabel("截图快捷键:"))
        self._hotkey_edit = QKeySequenceEdit()
        self._hotkey_edit.setMaximumWidth(200)
        hk_row.addWidget(self._hotkey_edit)
        hk_label = QLabel("（必须包含 Ctrl / Shift / Alt 组合键）")
        hk_label.setStyleSheet("color: #999; font-size: 11px;")
        hk_row.addWidget(hk_label)
        hk_row.addStretch()
        opt.addLayout(hk_row)

        layout.addWidget(grp_opt)

        # ----------------------------------------------------------------
        # 底部按钮
        # ----------------------------------------------------------------
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self._save_status = QLabel("")
        self._save_status.setStyleSheet("color: green; font-size: 11px;")
        btn_row.addWidget(self._save_status)
        btn_row.addStretch()

        self._save_btn = QPushButton("💾  保存")
        self._save_btn.setFixedSize(100, 32)
        self._save_btn.setStyleSheet(
            "QPushButton { background:#4285F4; color:white; border:none; border-radius:6px; font-size:12px; padding:0 8px; }"
            "QPushButton:hover { background:#3367D6; }"
        )
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(80, 32)
        close_btn.setStyleSheet(
            "QPushButton { background:#888; color:white; border:none; border-radius:6px; font-size:12px; padding:0 8px; }"
            "QPushButton:hover { background:#666; }"
        )
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    # ----------------------------------------------------------------
    # 文件浏览
    # ----------------------------------------------------------------
    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 OCR 模型文件",
            "",
            "GGUF 模型 (*.gguf);;所有文件 (*.*)",
        )
        if not path:
            return
        self._model_path.setText(path)
        # 自动推导 mmproj 路径（相同目录，文件名加 -mmproj）
        if path.lower().endswith(".gguf"):
            base = path[: -len(".gguf")]
            if "-mmproj" not in base.lower():
                mmproj = base + "-mmproj.gguf"
                if os.path.exists(mmproj):
                    self._mmproj_path.setText(mmproj)

    def _browse_mmproj(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 mmproj 文件", "", "GGUF 模型 (*.gguf);;所有文件 (*.*)"
        )
        if path:
            self._mmproj_path.setText(path)

    def _browse_server(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 llama-server.exe",
            "",
            "可执行文件 (*.exe);;所有文件 (*.*)",
        )
        if path:
            self._server_exe.setText(path)

    # ----------------------------------------------------------------
    # CUDA 检测
    # ----------------------------------------------------------------
    def _find_nvidia_smi(self) -> str | None:
        """在 PATH 和常见安装目录中查找 nvidia-smi"""
        # 1. PATH
        exe = shutil.which("nvidia-smi")
        if exe:
            return exe
        # 2. 常见安装目录
        candidates = [
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
            r"C:\Program Files (x86)\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
            r"C:\Windows\System32\nvidia-smi.exe",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        # 3. 尝试 where 命令
        try:
            result = subprocess.run(
                ["where", "nvidia-smi"],
                capture_output=True, text=True, timeout=5,
                startupinfo=_HIDE_WINDOW,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split("\n")[0].strip()
        except Exception:
            pass
        return None

    def _check_cuda(self):
        self._cuda_label.setText("检测中...")
        self._cuda_label.setStyleSheet("color: gray; font-size: 11px;")
        QTimer.singleShot(50, self._do_check_cuda)

    def _do_check_cuda(self):
        smi = self._find_nvidia_smi()
        if not smi:
            self._cuda_label.setText("❌ 未找到 nvidia-smi（无 NVIDIA 驱动或不在 PATH 中）")
            self._cuda_label.setStyleSheet("color: red; font-size: 11px;")
            return

        try:
            # ── 使用 --query-gpu 获取 GPU 名称和驱动版本（这两个字段跨版本兼容） ──
            result = subprocess.run(
                [smi, "--query-gpu=name,driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
                startupinfo=_HIDE_WINDOW,
            )
            if result.returncode != 0 or not result.stdout.strip():
                self._cuda_label.setText("❌ nvidia-smi 无法查询 GPU 信息")
                self._cuda_label.setStyleSheet("color: red; font-size: 11px;")
                return

            parts = [p.strip() for p in result.stdout.strip().split(",")]
            name = parts[0] if len(parts) > 0 else "Unknown"
            driver = parts[1] if len(parts) > 1 else "?"

            # ── 从 nvidia-smi -q 文本输出中解析 CUDA 版本 ──
            cuda_ver = self._parse_cuda_version(smi)
            ver_text = f"CUDA {cuda_ver}" if cuda_ver else "CUDA 未知"

            self._cuda_label.setText(
                f"✅ {name}  |  驱动 {driver}  |  {ver_text}"
            )
            self._cuda_label.setStyleSheet("color: green; font-weight: bold; font-size: 11px;")
        except subprocess.TimeoutExpired:
            self._cuda_label.setText("❌ 检测超时")
            self._cuda_label.setStyleSheet("color: red; font-size: 11px;")
        except Exception as e:
            self._cuda_label.setText(f"❌ {str(e)[:50]}")
            self._cuda_label.setStyleSheet("color: red; font-size: 11px;")

    @staticmethod
    def _parse_cuda_version(smi: str) -> str | None:
        """从 nvidia-smi -q 文本输出中提取 CUDA 版本号"""
        try:
            result = subprocess.run(
                [smi, "-q"], capture_output=True, text=True, timeout=10,
                startupinfo=_HIDE_WINDOW,
            )
            if result.returncode != 0:
                return None
            # 匹配 "CUDA Version : 13.3" 或 "CUDA UMD Version : 13.3"
            m = re.search(r"CUDA\s+(?:UMD\s+)?Version\s*:\s*([\d.]+)", result.stdout)
            return m.group(1) if m else None
        except Exception:
            return None

    # ----------------------------------------------------------------
    # API 连接测试（异步 QThread）
    # ----------------------------------------------------------------
    def _test_api_connection(self):
        key = self._api_key.text().strip()
        base_url = self._base_url.text().strip().rstrip("/")
        if not key:
            self._api_test_label.setText("❌ 请输入 API Key")
            self._api_test_label.setStyleSheet("color: red; font-size: 11px;")
            return
        if not base_url:
            base_url = "https://api.deepseek.com"

        self._api_test_btn.setEnabled(False)
        self._api_test_btn.setText("测试中...")
        self._api_test_label.setText("⏳ 正在测试连接...")
        self._api_test_label.setStyleSheet("color: gray; font-size: 11px;")

        # 使用 QThread 异步执行
        self._api_test_thread = QThread()
        self._api_test_worker = _ApiTestWorker(key, base_url)
        self._api_test_worker.moveToThread(self._api_test_thread)
        self._api_test_thread.started.connect(self._api_test_worker.run)
        self._api_test_worker.result_ready.connect(self._on_api_test_result)
        self._api_test_worker.finished.connect(self._api_test_thread.quit)
        self._api_test_worker.finished.connect(self._api_test_worker.deleteLater)
        self._api_test_thread.finished.connect(self._api_test_thread.deleteLater)
        self._api_test_thread.start()

    def _on_api_test_result(self, success: bool, message: str):
        self._api_test_btn.setEnabled(True)
        self._api_test_btn.setText("测试连接")
        if success:
            self._api_test_label.setText(f"✅ {message}")
            self._api_test_label.setStyleSheet("color: green; font-weight: bold; font-size: 11px;")
        else:
            self._api_test_label.setText(f"❌ {message}")
            self._api_test_label.setStyleSheet("color: red; font-size: 11px;")


    # ----------------------------------------------------------------
    # 加载 / 保存
    # ----------------------------------------------------------------
    def _load_values(self):
        s = self._settings
        self._model_path.setText(s.get("model_path", ""))
        self._mmproj_path.setText(s.get("mmproj_path", ""))
        self._server_exe.setText(s.get("llama_server_exe", ""))
        # API Key 从 .env 读取，不在 settings.json 中
        self._api_key.setText(settings_manager.load_api_key())
        self._base_url.setText(s.get("deepseek_base_url", ""))
        self._auto_start_cb.setChecked(s.get("auto_start_ocr", False))
        self._hide_cb.setChecked(s.get("hide_on_startup", False))
        self._hotkey_edit.setKeySequence(QKeySequence(s.get("hotkey", "Ctrl+Shift+S")))
        self._update_manual_btn()

    def _update_manual_btn(self):
        # 显式设置字体，避免 setStyleSheet 覆盖继承
        btn_font = QFont(config.FONT_FAMILY, config.FONT_SIZE - 3)
        if self._server_running:
            self._manual_btn.setText("■ 停止 OCR 服务器")
            self._manual_btn.setEnabled(True)
            self._manual_btn.setStyleSheet("color: #EA4335;")
            self._manual_btn.setFont(btn_font)
        else:
            self._manual_btn.setText("▶ 手动启动 OCR 服务器")
            self._manual_btn.setEnabled(True)
            self._manual_btn.setStyleSheet("")
            self._manual_btn.setFont(btn_font)

    def _collect(self) -> dict:
        """收集表单值（不含 API key，key 单独存入 .env）"""
        return {
            "model_path": self._model_path.text().strip(),
            "mmproj_path": self._mmproj_path.text().strip(),
            "llama_server_exe": self._server_exe.text().strip(),
            "deepseek_base_url": self._base_url.text().strip(),
            "deepseek_model": self._settings.get(
                "deepseek_model", "deepseek-v4-flash"
            ),
            "hotkey": self._hotkey_edit.keySequence().toString(
                QKeySequence.SequenceFormat.NativeText
            ),
            "auto_start_ocr": self._auto_start_cb.isChecked(),
            "hide_on_startup": self._hide_cb.isChecked(),
        }

    def _save_to_file(self):
        settings_manager.save_settings(self._collect())

    def _save_api_key_to_env(self):
        """将 API key 单独写入 .env 文件"""
        key = self._api_key.text().strip()
        settings_manager.save_api_key(key)

    def _on_manual_start(self):
        """点击手动启动/停止 → 保存 → 通知 App 启停 → 更新按钮状态"""
        self._save_to_file()
        self._save_api_key_to_env()
        key = self._api_key.text().strip()
        config.DEEPSEEK_API_KEY = key
        action = "stop" if self._server_running else "start"
        self.server_toggle_requested.emit(action)
        # 切换本地状态，无需关闭对话框
        self._server_running = not self._server_running
        self._update_manual_btn()

    def _on_save(self):
        self._save_to_file()
        # 保存 API key 到 .env 用于持久化
        self._save_api_key_to_env()
        # 直接设置内存中的值，不经过 .env 文件回读（更可靠）
        key = self._api_key.text().strip()
        config.DEEPSEEK_API_KEY = key
        print(f"[settings] API key set in memory (len={len(key)})")
        self._save_status.setText("✅ 已保存")
        # 3 秒后自动清除状态文字
        self._save_timer = QTimer(self)
        self._save_timer.timeout.connect(self._clear_save_status)
        self._save_timer.setSingleShot(True)
        self._save_timer.start(3000)

    def _clear_save_status(self):
        try:
            self._save_status.setText("")
        except RuntimeError:
            pass  # dialog 已销毁


class _ApiTestWorker(QObject):
    """工作线程：执行 API 连接测试"""
    result_ready = pyqtSignal(bool, str)
    finished = pyqtSignal()

    def __init__(self, api_key: str, base_url: str):
        super().__init__()
        self._api_key = api_key
        self._base_url = base_url

    def run(self):
        try:
            from openai import OpenAI
            client = OpenAI(base_url=self._base_url, api_key=self._api_key, timeout=15.0)
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "回复'ok'"}],
                max_tokens=5,
                temperature=0,
            )
            _ = resp.choices[0].message.content
            self.result_ready.emit(True, "连接成功，API 正常工作")
        except Exception as e:
            msg = str(e)
            if len(msg) > 60:
                msg = msg[:60] + "…"
            self.result_ready.emit(False, msg)
        finally:
            self.finished.emit()

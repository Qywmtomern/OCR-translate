"""
OCR 引擎 — 通过 llama-server.exe 子进程调用本地 PaddleOCR-VL 模型
"""

import os
import subprocess
import time
import sys
import requests
import base64
from io import BytesIO
from PIL import Image

# 确保控制台 UTF-8 编码（noconsole 模式下 stdout/stderr 为 None）
try:
    if sys.stdout is not None and sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

import config


class LlamaServerManager:
    """管理 llama-server.exe 子进程的完整生命周期"""

    def __init__(self):
        self.process: subprocess.Popen | None = None

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动 llama-server 并等待健康检查通过"""
        # 路径预校验
        missing = []
        for label, path in [
            ("llama-server.exe", config.LLAMA_SERVER_EXE),
            ("模型文件", config.MODEL_PATH),
            ("mmproj 投影文件", config.MMPROJ_PATH),
        ]:
            if not os.path.exists(path):
                missing.append(f"  {label}: {path}")
        if missing:
            raise FileNotFoundError(
                "以下文件路径不存在，请检查设置：\n" + "\n".join(missing)
            )

        cmd = [
            config.LLAMA_SERVER_EXE,
            "-m", config.MODEL_PATH,
            "--mmproj", config.MMPROJ_PATH,
            "--host", config.LLAMA_HOST,
            "--port", str(config.LLAMA_PORT),
            "--gpu-layers", config.LLAMA_GPU_LAYERS,
            "--ctx-size", str(config.LLAMA_CTX_SIZE),
            "--parallel", str(config.LLAMA_N_PARALLEL),
            "--temp", str(config.LLAMA_TEMP),
            "--no-webui",
        ]
        print(f"[llama-server] Starting: {' '.join(cmd)}")

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        # 轮询健康检查
        print("[llama-server] Waiting for server to be ready...")
        timeout = 120
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                stderr_output = self.process.stderr.read() if self.process.stderr else ""
                raise RuntimeError(
                    f"llama-server exited unexpectedly (code={self.process.returncode}):\n{stderr_output[-2000:]}"
                )
            if self._health_check():
                print("[llama-server] Server is ready")
                return
            time.sleep(0.5)

        self.stop()
        raise TimeoutError(f"llama-server did not become ready within {timeout}s")

    def stop(self) -> None:
        """终止 llama-server 子进程"""
        if self.process is None:
            return
        print("[llama-server] Stopping...")
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("[llama-server] Force killing process")
            self.process.kill()
            self.process.wait()
        self.process = None
        print("[llama-server] Stopped")

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------
    def _health_check(self) -> bool:
        try:
            r = requests.get(
                f"http://{config.LLAMA_HOST}:{config.LLAMA_PORT}/health",
                timeout=2,
            )
            return r.status_code == 200
        except Exception:
            return False

    def health_check(self) -> bool:
        """公开的健康检查接口"""
        return self._health_check()


class OCREngine:
    """使用 llama-server 的 OpenAI 兼容 API 进行 OCR"""

    def __init__(self, server: LlamaServerManager):
        self.server = server

    # ------------------------------------------------------------------
    # 文字提取
    # ------------------------------------------------------------------
    def extract_text(self, image: Image.Image) -> str:
        """对 PIL Image 执行 OCR，返回提取的文字"""
        if not self.server.is_running:
            raise RuntimeError("llama-server is not running")

        # 编码图像为 base64 data URI
        img_base64 = self._encode_image(image)

        # 构造 OpenAI 兼容请求
        payload = {
            "model": "paddleocr-vl",
            "messages": [
                {
                    "role": "system",
                    "content": config.OCR_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": img_base64},
                        },
                        {
                            "type": "text",
                            "text": config.OCR_PROMPT,
                        },
                    ],
                },
            ],
            "temperature": config.LLAMA_TEMP,
            "max_tokens": 2048,
            "stream": False,
        }

        resp = requests.post(
            f"http://{config.LLAMA_HOST}:{config.LLAMA_PORT}/v1/chat/completions",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        text = data["choices"][0]["message"]["content"].strip()
        return text if text else "（无文字）"

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _encode_image(image: Image.Image) -> str:
        """将 PIL Image 编码为 PNG base64 data URI"""
        buf = BytesIO()
        image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

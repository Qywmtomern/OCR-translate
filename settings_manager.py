"""
Settings manager — load/save user settings from/to settings.json & .env

- settings.json: 存储路径、选项等非敏感配置
- .env: 存储 DEEPSEEK_API_KEY，不进入 settings.json
"""

import json
import os
import sys

try:
    from dotenv import load_dotenv, set_key
    _dotenv_available = True
except ModuleNotFoundError:
    load_dotenv = None
    set_key = None
    _dotenv_available = False

# 程序所在目录（源码或打包 exe）
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
DOTENV_FILE = os.path.join(BASE_DIR, ".env")


DEFAULT_SETTINGS = {
    # ---- OCR 本地模型 ----
    "llama_server_exe": r"E:\Develop\llama-b8882-bin-win-cuda-12.4-x64\llama-server.exe",
    "model_path": r"E:\Develop\LM Studio_models\PaddlePaddle\PaddleOCR-VL-1.6-GGUF\PaddleOCR-VL-1.6-GGUF.gguf",
    "mmproj_path": r"E:\Develop\LM Studio_models\PaddlePaddle\PaddleOCR-VL-1.6-GGUF\PaddleOCR-VL-1.6-GGUF-mmproj.gguf",

    # ---- DeepSeek API（仅非敏感项） ----
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-v4-flash",

    # ---- 截图热键 ----
    "hotkey": "Ctrl+Shift+S",

    # ---- 启动选项 ----
    "auto_start_ocr": False,
    "hide_on_startup": False,
}


# ======================================================================
# settings.json 读写
# ======================================================================

def load_settings() -> dict:
    """从 settings.json 读取设置，缺失字段用默认值补齐"""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        saved = {}

    merged = DEFAULT_SETTINGS.copy()
    merged.update(saved)
    return merged


def save_settings(settings: dict) -> None:
    """将设置写入 settings.json（自动移除 API key 敏感字段）"""
    # 确保不写入 API key
    safe = {k: v for k, v in settings.items() if k != "deepseek_api_key"}
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(safe, f, ensure_ascii=False, indent=2)


# ======================================================================
# .env 文件读写（仅 DEEPSEEK_API_KEY）
# ======================================================================

def load_api_key() -> str:
    """从 .env 文件读取 DEEPSEEK_API_KEY，不存在返回空字符串"""
    if not os.path.exists(DOTENV_FILE):
        return ""

    if _dotenv_available:
        try:
            load_dotenv(DOTENV_FILE, override=True)
            return os.getenv("DEEPSEEK_API_KEY", "")
        except Exception:
            pass

    # fallback: 手动解析 .env 文件
    try:
        with open(DOTENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    val = line.split("=", 1)[1].strip()
                    # 去除引号
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                        val = val[1:-1]
                    return val
    except Exception:
        pass
    return ""


def save_api_key(key: str) -> None:
    """将 DEEPSEEK_API_KEY 写入 .env 文件（先尝试 set_key，失败时手动写入）"""
    if _dotenv_available:
        try:
            set_key(DOTENV_FILE, "DEEPSEEK_API_KEY", key)
            print(f"[settings] API key saved to {DOTENV_FILE}")
            return
        except Exception as e:
            print(f"[settings] dotenv set_key failed ({e}), using manual fallback")

    # fallback: 手动写入
    try:
        with open(DOTENV_FILE, "w", encoding="utf-8") as f:
            # 如果 key 包含特殊字符，用双引号包裹
            if any(c in key for c in (" ", "#", "'", '"', "\\")):
                escaped = key.replace("\\", "\\\\").replace('"', '\\"')
                f.write(f'DEEPSEEK_API_KEY="{escaped}"\n')
            else:
                f.write(f"DEEPSEEK_API_KEY={key}\n")
        print(f"[settings] API key manually saved to {DOTENV_FILE}")
    except Exception as e:
        print(f"[settings] ERROR: failed to write {DOTENV_FILE}: {e}")

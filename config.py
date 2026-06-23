"""
配置常量 — 从 settings.json 加载路径/密钥，UI/提示词等固定参数保持在代码中

敏感信息（DEEPSEEK_API_KEY）从 .env 文件加载，不进入 settings.json。
"""

from settings_manager import load_settings, load_api_key

# ============================================================
# 从 .env 加载 API Key（含手动解析 fallback）
# ============================================================
DEEPSEEK_API_KEY = load_api_key()

# ============================================================
# 从 settings.json 加载用户可配置项
# ============================================================
_settings = load_settings()

LLAMA_SERVER_EXE = _settings["llama_server_exe"]
MODEL_PATH = _settings["model_path"]
MMPROJ_PATH = _settings["mmproj_path"]

LLAMA_HOST = "127.0.0.1"
LLAMA_PORT = 8787
LLAMA_GPU_LAYERS = "all"
LLAMA_CTX_SIZE = 4096
LLAMA_N_PARALLEL = 1
LLAMA_TEMP = 0.1

DEEPSEEK_BASE_URL = _settings["deepseek_base_url"]
DEEPSEEK_MODEL = _settings["deepseek_model"]


# ==================================================================
# 热更新
# ==================================================================

def update_from_settings(settings: dict) -> None:
    """用新的用户设置刷新本模块的变量（不包含 API key，key 由 reload_env 更新）"""
    global LLAMA_SERVER_EXE, MODEL_PATH, MMPROJ_PATH
    global DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, HOTKEY_STR
    LLAMA_SERVER_EXE = settings.get("llama_server_exe", LLAMA_SERVER_EXE)
    MODEL_PATH = settings.get("model_path", MODEL_PATH)
    MMPROJ_PATH = settings.get("mmproj_path", MMPROJ_PATH)
    DEEPSEEK_BASE_URL = settings.get("deepseek_base_url", DEEPSEEK_BASE_URL)
    DEEPSEEK_MODEL = settings.get("deepseek_model", DEEPSEEK_MODEL)
    HOTKEY_STR = settings.get("hotkey", HOTKEY_STR)


def reload_env() -> None:
    """重新加载 .env 文件并刷新 DEEPSEEK_API_KEY"""
    global DEEPSEEK_API_KEY
    DEEPSEEK_API_KEY = load_api_key()


# ============================================================
# 全局热键配置
# ============================================================
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_ALT = 0x0001
HOTKEY_MODIFIERS = MOD_CONTROL | MOD_SHIFT
HOTKEY_VK = ord('S')
HOTKEY_ID = 1
HOTKEY_STR = _settings.get("hotkey", "Ctrl+Shift+S")

# ============================================================
# UI 常量
# ============================================================
FONT_FAMILY = "微软雅黑"
FONT_SIZE = 14
SELECTION_BORDER_COLOR = "#4285F4"
SELECTION_BORDER_WIDTH = 2
SELECTION_OVERLAY_ALPHA = 120
BUTTON_WIDTH = 120
BUTTON_HEIGHT = 36
BUTTON_GAP = 8
BUTTON_MARGIN = 8
BUTTON_STYLE = """
QPushButton {
    background-color: #4285F4;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-family: "微软雅黑";
    font-size: 13px;
    font-weight: bold;
}
QPushButton:hover { background-color: #3367D6; }
QPushButton:pressed { background-color: #2A56C6; }
"""
OVERLAY_BG_COLOR = "rgba(255, 255, 255, 230)"
OVERLAY_TEXT_COLOR = "#333333"
OVERLAY_BORDER_COLOR = "#CCCCCC"
OVERLAY_BORDER_RADIUS = 8
MIN_SELECTION_SIZE = 20

# ============================================================
# OCR 提示词
# ============================================================
OCR_SYSTEM_PROMPT = "你是一个专业的 OCR 文字识别助手。"
OCR_PROMPT = "识别图片中的所有文字，直接输出文字内容，不要添加任何解释。如果图片中没有文字，请回复（无文字）。"

TRANSLATE_SYSTEM_PROMPT = (
    "你是一个专业的翻译助手。将用户输入的任何语言文本翻译成简体中文。"
    "只输出翻译结果，不要添加任何解释或注释。保持原文的换行和格式。"
)

# OCR 翻译工具

一个 Windows 桌面截图翻译工具，支持多显示器 + 高 DPI，集成本地 PaddleOCR-VL 模型（通过 llama.cpp）与云端 DeepSeek API 翻译。

---

## 功能概览

| 功能 | 描述 |
|------|------|
| 📸 框选截图 | `Ctrl+Shift+S` 启动全屏框选，鼠标拖拽选中任意区域 |
| 🔍 文字识别 (OCR) | 调用本地 llama-server 运行 PaddleOCR-VL GGUF 模型进行离线识别 |
| 🌐 翻译 | 通过 DeepSeek API 将识别文字翻译为简体中文 |
| 💻 多显示器 | 每个显示器独立的截图层，互不影响 |
| 🖥️ 高 DPI 支持 | 物理像素截图 + 逻辑像素渲染，完美支持高 DPI 缩放 |
| 🔄 模型热启停 | 设置界面可随时启动/停止本地 OCR 模型，无需重启应用 |
| 🖱️ 系统托盘 | 托盘常驻，右键菜单可打开主界面/设置/重启/退出 |
| ⚙️ 可配置快捷键 | 设置对话框中支持自定义截图快捷键 |

---

## 快速开始

### 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11（需要 Win32 全局热键支持） |
| Python | 3.12+（如需从源码运行） |
| GPU 加速 | NVIDIA GPU + CUDA 12.4（llama.cpp 构建，可选但推荐） |

### 前置依赖

本工具需要以下外部组件（需自行下载）：

| 组件                   | 来源                                                                        | 说明                                              |
|:---------------------|---------------------------------------------------------------------------|-------------------------------------------------|
| `llama-server.exe`   | [llama.cpp Releases](https://github.com/ggerganov/llama.cpp/releases)     | 需下载包含多模态支持的构建版本（如 `bNNNN-bin-win-cuda-X.Y-x64`） |
| PaddleOCR-VL GGUF 模型 | [hugging face](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/tree/main) | 需要主模型 `.gguf` + 对应的 `-mmproj.gguf` 投影文件         |
| CUDA环境               | [CUDA Toolkit Archive](https://developer.nvidia.com/cuda-toolkit-archive) | 选取匹配的CUDA环境   |

### 安装步骤

```bash
# 1. 克隆/进入项目目录
cd your project path

# 2. （可选）创建虚拟环境
python -m venv venv
.\venv\Scripts\activate

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 配置 settings.json（见配置说明）
# 5. 配置 .env 文件填入 DeepSeek API Key
# 6. 运行
python main.py
```

### 打包为独立可执行文件

```bash
pip install pyinstaller
pyinstaller --clean --onefile --name "OCR-Translate" --noconsole --hidden-import mss main.py
```

打包产出：
- `OCR-Translate.exe` — 单文件可执行（约 70MB，含 Python 运行时）
- `settings.json` — 与 exe 同目录放置
- `.env` — 与 exe 同目录放置（存放 `DEEPSEEK_API_KEY`）

---

## 项目结构

```
ocr/
├── main.py               # 应用入口：全局热键、QThread 编排、生命周期管理
├── config.py              # 配置常量：路径、热键编码、UI 样式、OCR/翻译提示词
├── ocr_engine.py          # OCR 引擎：llama-server 进程管理 + OpenAI 兼容 API 调用
├── screen_capture.py      # 截图框选：全屏遮罩 + 鼠标拖拽选区 + 操作按钮
├── overlay.py             # 文字贴图：段落级画布 + 像素投影布局 + 可拖动标题栏
├── translator.py          # 翻译器：DeepSeek API 客户端（多模型 fallback）
├── settings_manager.py    # 设置管理器：settings.json + .env 文件读写
├── settings_dialog.py     # 设置对话框：路径配置、API 密钥、CUDA 检测、快捷键设置
├── main_window.py         # 主窗口：服务器状态、快捷键提示、控制按钮
├── settings.json          # 用户配置文件（非敏感信息）
├── requirements.txt       # Python 依赖清单
├── .env                   # 环境变量（含 DEEPSEEK_API_KEY，不应纳入版本控制）
└── OCR-Translate.exe      # PyInstaller 打包的可执行文件
```

---

## 系统架构

```
┌────────────────────────────────────────────────────────────────
│  main.py (App / QApplication)
│  ┌─────────────────────────────────────────────────────────┐
│  │  GlobalHotkeyFilter (Win32 WM_HOTKEY)                   
│  │  · Ctrl+Shift+S（可自定义） → 框选截图                      
│  │  · Ctrl+Shift+Q          → 退出                          
│  └─────────────────────────────────────────────────────────┘
│                         │
│                         ▼
│  ┌─────────────────────────────────────────────────────────┐
│  │  ScreenCaptureWidget × N（每个显示器一个）               
│  │  · 全屏遮罩 + 半透明选区显示                              
│  │  · 鼠标拖拽选区 + 选区外部遮罩                            
│  │  · 「提取文字」/「翻译」按钮（自动避开屏幕边缘）            
│  └─────────────────────────────────────────────────────────┘
│                         │
│                         ▼
│  ┌─────────────────────────────────────────────────────────┐
│  │  QThread 任务编排（异步，不阻塞 UI）                      
│  │                                                         
│  │  OCRWorker       →  OCREngine.extract_text()            
│  │  TranslateWorker →  Translator.translate()              
│  │                                                         
│  │  提取模式: 框选截图 → OCR                                  
│  │  翻译模式: 框选截图 → OCR → 翻译                           
│  └─────────────────────────────────────────────────────────┘
│                         │
│                         ▼
│  ┌─────────────────────────────────────────────────────────┐
│  │  TextOverlay（半透明悬浮窗口）                            
│  │  · 段落级布局 + 像素投影权重分配字号                      
│  │  · 可拖动标题栏（关闭/复制/拖拽）                         
│  │  · QPropertyAnimation 淡入动画（120ms）                  
│  └─────────────────────────────────────────────────────────┘
│
│  ┌─────────────────────────────────────────────────────────┐
│  │  主窗口 + 系统托盘                                       
│  │  · MainWindow: 服务器状态 / 设置 / 启停 / 退出            
│  │  · QSystemTrayIcon: 右键菜单（显示/设置/退出）       
│  └─────────────────────────────────────────────────────────┘
└────────────────────────────────────────────────────────────────
```

### 数据流

```
用户按键 Ctrl+Shift+S
    │
    ▼
GlobalHotkeyFilter 触发 _on_hotkey()
    │
    ▼
mss 截取所有显示器（物理像素 BGRA）
    │
    ▼
每个显示器创建一个 ScreenCaptureWidget（全屏半透明遮罩）
    │
    ▼
用户鼠标拖拽选中的区域
    ├── 点击「提取文字」
    │       │
    │       ▼
    │   QThread → OCREngine.extract_text()
    │       │  ├── 裁切选区 → PIL → PNG base64 data URI
    │       │  └── POST /v1/chat/completions → llama-server
    │       ▼
    │   TextOverlay 显示识别结果（半透明悬浮窗口）
    │
    └── 点击「翻译」
            │
            ▼
        QThread → OCR →（链式）→ QThread → Translator.translate()
            │                     │  ├── OpenAI(DeepSeek) API
            │                     │  └── 多模型 fallback 机制
            ▼
        TextOverlay 显示翻译结果
```

---

## 核心模块详解

### 1. `main.py` — 应用入口

| 类/函数 | 职责 |
|---------|------|
| `App` | `QApplication` 子类，管理全局热键、截图编排、OCR/翻译流水线、系统托盘和设置 |
| `StatusWindow` | 启动/加载状态显示窗口（无边框居中，用于显示"正在启动 OCR 服务…"等状态） |
| `GlobalHotkeyFilter` | Win32 `WM_HOTKEY` 原生事件过滤器，通过 `QAbstractNativeEventFilter` 实现 |
| `OCRWorker` / `TranslateWorker` | `QThread` Worker 对象，分别在独立线程中执行 OCR 和翻译 |
| `main()` | 入口函数，设置高 DPI 缩放策略并启动 `App` |

关键行为：
- **坐标系统**：所有 Widget 使用逻辑像素，截图使用物理像素，转换在 `ScreenCaptureWidget._to_physical()` 中通过 `_scale_x`/`_scale_y` 缩放因子完成
- **多显示器**：每个显示器一个独立 Widget，互不阻塞
- **退出方式**：`Ctrl+Shift+Q`、系统托盘右键退出、终端 `Ctrl+C`

### 2. `config.py` — 配置常量

| 类别 | 内容 |
|------|------|
| API 密钥 | `DEEPSEEK_API_KEY` 从 `.env` 文件加载 |
| 模型路径 | `llama_server_exe`、`model_path`、`mmproj_path` 从 `settings.json` 加载 |
| 热键 | `MOD_CONTROL` (`0x0002`)、`MOD_SHIFT` (`0x0004`)、`HOTKEY_VK` (`S`) |
| UI 常量 | 半透明遮罩颜色、选区样式、按钮样式、字体大小 |
| OCR 提示词 | 系统提示 + 用户提示（支持多模态视觉输入） |
| 翻译提示词 | 系统提示（要求翻译为简体中文） |

关键机制：
- `update_from_settings(settings)` → 运行时热更新路径配置
- `reload_env()` → 重新加载 `.env` 文件刷新 API Key

### 3. `ocr_engine.py` — OCR 引擎

**`LlamaServerManager`** — llama-server.exe 子进程生命周期管理器

| 方法 | 说明 |
|------|------|
| `start()` | 启动子进程，轮询 `/health` 直到就绪（超时 120 秒） |
| `stop()` | 发送 SIGTERM → 等待 5 秒 → 超时则强制 SIGKILL |
| `is_running` | 只读属性：检查子进程是否存活 |
| `health_check()` | 调用 `http://127.0.0.1:8787/health` 检查服务状态 |

启动参数：
```
llama-server.exe -m <MODEL_PATH> --mmproj <MMPROJ_PATH>
    --host 127.0.0.1 --port 8787 --gpu-layers all
    --ctx-size 4096 --parallel 1 --temp 0.1 --no-webui
```

**`OCREngine`** — 通过 OpenAI 兼容 API 调用 OCR 模型

| 方法 | 说明 |
|------|------|
| `extract_text(image)` | 接收 PIL Image → base64 PNG data URI → POST `/v1/chat/completions` → 返回识别文本 |
| `_encode_image(image)` | PIL Image → PNG base64 data URI 编码 |

### 4. `screen_capture.py` — 截图框选

**`ScreenCaptureWidget`** — 单个显示器上的全屏半透明覆盖层

| 信号 | 参数 | 说明 |
|------|------|------|
| `action_triggered` | `(QRect逻辑, QRect物理, np.ndarray, "extract"\|"translate")` | 用户选择了操作 |
| `cancelled` | — | 用户取消了框选 |

坐标系统：
- 鼠标事件使用 **逻辑像素**（Qt 坐标）
- `_to_physical(logical_rect)` → 乘以 `_scale_x`/`_scale_y` 得到 **物理像素**（用于 mss 截图裁切）
- 高 DPI 支持：`setDevicePixelRatio(dpr)` 让 Qt 自动缩放

关键机制：
- **多显示器匹配**：通过 `_find_qt_screen()` 将 mss monitor 映射到 Qt `QScreen`
- **选区遮罩**：使用 `QPainterPath.subtracted()` 在选区外部绘制半透明遮罩，突出选中区域
- **操作按钮**：「提取文字」和「翻译」按钮定位在选区附近，带有屏幕边缘碰撞检测，防止按钮超出屏幕

### 5. `overlay.py` — 文字贴图

**`TextOverlay`** — 段落级半透明悬浮文字窗口

核心算法 `_layout_paragraphs()`：
```
OCR 原始文本
    │
    ▼ 按双换行符 \n\n 分段 → list[str]
    │
    ▼ 对 ROI 图像做像素投影分析（灰度 → 暗像素密度 → 行权重）
    │
    ▼ 按权重比例分配垂直空间 → 每段字号 = 行高 × 0.50（上限 16px）
    │
    ▼ 每段落创建一个 QLabel，设置字号与位置
```

| 功能 | 说明 |
|------|------|
| 拖动标题栏 | 顶部蓝色渐变条，含关闭 ✕ / 复制 📋 按钮，可拖动窗口 |
| 动画 | `QPropertyAnimation` 窗口淡入效果（120ms） |
| 快捷键 | `Esc` / 双击关闭、`Ctrl+C` 复制全部文本 |
| 文本选择 | `TextSelectableByMouse` 支持鼠标框选文字 |

### 6. `translator.py` — 翻译器

| 方法 | 说明 |
|------|------|
| `translate(text)` | 接收文本 → DeepSeek API → 返回简体中文翻译 |

模型 fallback 机制（按序尝试，成功后缓存模型名）：
```
[deepseek-v4-flash, deepseek-chat, deepSeek-V4-pro]
```

实现细节：
- 每次调用创建独立 OpenAI 客户端，线程安全
- 请求失败时自动重试下一个模型名
- 使用当前缓存的模型名避免重复 fallback

### 7. `settings_manager.py` — 设置管理器

| 函数 | 说明 |
|------|------|
| `load_settings()` | 读取 `settings.json`，缺失字段用默认值补齐 |
| `save_settings(settings)` | 写入 `settings.json`（自动过滤 API Key，避免泄露） |
| `load_api_key()` | 从 `.env` 读取 `DEEPSEEK_API_KEY`（优先 `python-dotenv`，失败则手动解析） |
| `save_api_key(key)` | 写入 `.env`（优先 `set_key`，失败则手动写入） |

### 8. `settings_dialog.py` — 设置对话框

| 功能区域 | 说明 |
|----------|------|
| OCR 模型路径 | 三个文本框分别设置模型 `.gguf`、mmproj `.gguf`、`llama-server.exe` 路径，均带有文件浏览对话框 |
| 自动推导 mmproj | 当选择模型文件时，自动在同一目录寻找对应的 `-mmproj.gguf` 文件并填入 |
| DeepSeek API | API Key（密码模式输入）、Base URL、模型名；含异步连接测试（通过独立 `_ApiTestWorker` QThread） |
| CUDA 检测 | 自动定位 `nvidia-smi`，显示 GPU 型号、驱动版本、CUDA 版本 |
| 截图快捷键 | `QKeySequenceEdit` 小部件，支持自定义截图热键 |
| 启动选项 | 自动启动 OCR 模型、启动时隐藏主界面 |
| 模型启停 | 实时启动/停止 llama-server，无需关闭对话框（通过 `server_toggle_requested` 信号） |

### 9. `main_window.py` — 主窗口

- 固定大小 420×300，居中显示
- 显示 OCR 服务器状态（运行中/已停止）和 DeepSeek API 状态
- 三个按钮：**设置**（打开设置对话框）、**启动/停止 OCR**（切换按钮）、**退出**
- 关闭窗口时隐藏到系统托盘（不退出应用）
- 热键提示随 `settings.json` 配置动态同步

---

## 配置说明

### settings.json

与可执行文件（或 `main.py`）同目录放置，包含非敏感配置：

```json
{
  "model_path": "path/to/PaddleOCR-VL-1.6-GGUF.gguf",
  "mmproj_path": "path/to/PaddleOCR-VL-1.6-GGUF-mmproj.gguf",
  "llama_server_exe": "path/to/llama-server.exe",
  "deepseek_base_url": "https://api.deepseek.com",
  "deepseek_model": "deepseek-v4-flash",
  "hotkey": "Ctrl+Shift+S",
  "auto_start_ocr": false,
  "hide_on_startup": false
}
```

| 字段 | 说明 |
|------|------|
| `model_path` | PaddleOCR-VL GGUF 模型文件的完整路径 |
| `mmproj_path` | 对应的 mmproj 投影文件完整路径 |
| `llama_server_exe` | llama-server.exe 可执行文件的完整路径 |
| `deepseek_base_url` | DeepSeek API 的基础地址 |
| `deepseek_model` | DeepSeek 模型名称 |
| `hotkey` | 截图快捷键（可通过设置对话框修改） |
| `auto_start_ocr` | 启动应用时自动启动 OCR 模型服务 |
| `hide_on_startup` | 启动时隐藏主窗口，仅显示系统托盘图标 |

### .env

存放敏感信息，**不应纳入版本控制**：

```
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

可通过设置对话框的 API Key 输入框直接修改，修改后自动保存到此文件。

---

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Shift+S`（可自定义） | 截图框选（覆盖所有显示器） |
| `Ctrl+Shift+Q` | 退出程序 |
| `Esc` | 取消截图 / 关闭文字悬浮窗 |
| `Ctrl+C` | 复制文字悬浮窗中的全部文本 |
| 双击文字悬浮窗 | 关闭文字悬浮窗 |

> 截图快捷键可在「设置」→「截图快捷键」中自定义。

---

## 常见问题排查

### OCR 服务无法启动

1. 检查 `llama-server.exe` 路径是否正确
2. 确认模型文件路径和 mmproj 文件路径正确
3. 查看是否端口 `8787` 被占用：`netstat -ano | findstr :8787`
4. 检查 GPU 驱动和 CUDA 版本是否与 llama.cpp 构建版本匹配
5. 启动后在设置对话框中点击「启动 OCR」查看实时日志

### OCR 识别质量不佳

- 确保截图区域文字清晰可见
- 调整截图区域，避免包含过多无关内容
- PaddleOCR-VL 对印刷体文字识别效果较好

### 翻译功能不可用

1. 确认 `.env` 中 `DEEPSEEK_API_KEY` 已正确填写
2. 在设置对话框中点击「测试连接」验证 API 连通性
3. 检查 `deepseek_base_url` 配置是否正确
4. 确认网络可以访问 `api.deepseek.com`

### 高 DPI 显示异常

- 应用会自动检测系统 DPI 缩放比例
- 如果截图区域与实际选择区域不匹配，尝试在「设置」中确认显示器缩放设置

---

## 开发环境

| 项目 | 说明 |
|------|------|
| Python | 3.12+ |
| GUI 框架 | PyQt6 |
| 截图库 | [mss](https://github.com/BoboTiG/python-mss)（跨平台屏幕捕获） |
| 图片处理 | Pillow |
| OCR 引擎 | llama.cpp + PaddleOCR-VL (GGUF) |
| 翻译 API | DeepSeek API（OpenAI 兼容接口） |
| 操作系统 | Windows 10/11（Win32 全局热键） |
| GPU 加速 | CUDA 12.4（llama.cpp 构建） |
| IDE | 兼容 JetBrains IDE（项目包含 `.idea/` 配置） |

### 依赖清单

```
PyQt6>=6.6      # 桌面 GUI 框架
mss>=9.0        # 跨平台屏幕截图
Pillow>=10.0    # 图像处理
openai>=2.0     # OpenAI 兼容 API 客户端（用于 DeepSeek API）
requests>=2.31  # HTTP 客户端（用于 llama-server 健康检查）
numpy>=1.24     # 数组操作（图像像素分析）
python-dotenv>=1.0  # .env 文件解析
```

---

## 许可

本项目仅供个人学习和研究使用。

---

## 相关链接

- [llama.cpp](https://github.com/ggerganov/llama.cpp) — 本地 LLM 推理框架
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) — 百度 OCR 工具套件
- [DeepSeek API](https://platform.deepseek.com/) — DeepSeek 大语言模型 API
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — Python Qt 绑定

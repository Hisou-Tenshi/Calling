# Calling

本项目是一个**本地最小化 LLM 网页对话框**（带工具 Agent + 文档翻译），通过自己的 API Key 调用各家模型。

## 功能概览

### Chat 标签

| 功能 | 说明 |
|------|------|
| **多模型支持** | Claude / Gemini / Grok，UI 内可选或手动输入 model id |
| **20 轮上下文窗口** | 服务端自动裁剪，只保留最近 20 轮（user + assistant） |
| **Function Calling** | `web_search`（全网搜索，优先 Tavily，回退 DuckDuckGo）；`read_file`（读项目内任意文件，`__TREE__` 获取目录树） |
| **强制联网开关** | 开启后本轮回答前模型必须调用一次 `web_search` |
| **文件上传** | 上传后存入 `data/uploads/`，支持多文件 |
| **RAG（开关）** | 上传时对文件分块 embedding（需配置 `GEMINI_API_KEY`），对话时自动检索注入上下文 |
| **多会话** | 侧边栏管理历史会话，支持新建 / 切换 / 删除 |

### Translate 标签（文档翻译）

| 功能 | 说明 |
|------|------|
| **支持格式** | `.txt` `.md` `.rmd` `.rtf` `.doc` `.docx` `.pdf` |
| **可选模型** | 与 Chat 共用同一模型列表 |
| **原语言** | 自动识别（留空）或手动指定 |
| **目标语言** | 26 种常用语言下拉选择 |
| **分块策略** | 见下方详细说明 |
| **流式进度条** | 每翻译完一个 chunk 实时更新输出和进度 |
| **急停按钮** | 翻译进行中可随时点 Stop 终止，已翻译部分仍可复制/下载 |
| **输出格式** | Markdown，尽量保留原文排版结构 |
| **复制 / 下载** | 一键复制到剪贴板，或下载为 `原文件名_translated.md` |

#### 分块策略详解

翻译时按「父块 → 子块」两级切割，每个子块单独调用模型，结果拼回父块顺序输出。

| 模式 | 说明 |
|------|------|
| **Separator-based（默认）** | 按分隔符优先级贪心合并，直到达到「父块最大字符数」 |
| **LLM-assisted split** | 先用一个轻量模型把全文切成逻辑段落（返回 JSON 数组），再翻译各段 |

**内置分隔符预设：**

| 预设 | 使用的分隔符（按优先级） |
|------|------------------------|
| `paragraph`（默认） | `\n\n\n` → `\n\n` → `\n` |
| `sentence` | 段落分隔符 + `. ` `! ` `? ` |
| `heading` | Markdown 标题行 + 段落分隔符 |
| `custom` | 自行输入，多个分隔符用 `|` 隔开，如 `\n\n|---` |

**参数建议：**
- 父块最大（Parent max）：2000–4000 字符，过大单次 API 耗时长
- 子块最大（Child max）：600–1200 字符，过小翻译割裂感强

---

## 安装与运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

核心依赖（翻译相关额外包）：

```
python-docx   # .docx 解析
pdfminer.six  # .pdf 文本提取
striprtf      # .rtf 解析
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并填写：

```env
# 至少填一个模型的 Key
CLAUDE_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
GROK_API_KEY=xai-...

# 可选：Claude 代理（与 Tenshi 同名变量）
CLAUDE_PROXY_KEY=...
CLAUDE_PROXY_BASE_URL=https://your-proxy/v1
CLAUDE_PROXY_KEY_2=...
CLAUDE_PROXY_BASE_URL_2=https://your-proxy2/v1

# 可选：Tavily 联网搜索（比 DuckDuckGo 更稳定）
TAVILY_KEY=tvly-...

# 可选：默认模型
DEFAULT_CHAT_MODEL=claude-3-5-sonnet-20241022

# 可选：RAG 参数
RAG_CHUNK_SIZE=1200
RAG_CHUNK_OVERLAP=150
RAG_TOP_K=5

# 可选：服务器
HOST=127.0.0.1
PORT=8000
```

### 3. 启动

```bash
# 推荐（跨平台，不依赖 PATH）
python -m uvicorn backend.main:app --reload

# 或者直接
python -m backend.main
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## 日志面板

页面**右下角**有两个悬浮按钮：

| 按钮 | 功能 |
|------|------|
| 📋（日志） | 展开/收起日志弹窗 |
| ⏹（停止） | 向服务端发送关机信号，服务器会在 0.5 秒后退出 |

日志弹窗特性：
- **实时流式**：通过 SSE 推送，连接后自动回放最近 500 条历史记录
- **级别着色**：INFO 灰白、DEBUG 暗蓝、WARNING 黄色、ERROR 红色
- **自动滚动**：跟随最新日志；手动向上滚动后暂停，滚回底部恢复
- **Clear** 按钮清空当前显示（不影响后端日志）
- 断线后 3 秒自动重连

日志同时输出到终端 stdout，格式：

```
2026-03-30 12:00:00,000 [INFO] calling.translate: [translate] start file=doc.pdf model=claude-3-5-sonnet-20241022 target=Chinese (Simplified) split_mode=separator
2026-03-30 12:00:01,000 [INFO] calling.translate: [translate] extracted 15234 chars from doc.pdf
2026-03-30 12:00:01,100 [INFO] calling.translate: [translate] 6 parent chunks to translate
2026-03-30 12:00:05,000 [INFO] calling.translate: [translate] chunk 1/6 sub 1/1 chars=2843
...
```

调试级别（verbose）可在 `backend/main.py` 顶部将 `level=logging.INFO` 改为 `level=logging.DEBUG`。

## 服务管理

### 启动

```bash
# 推荐（跨平台，不依赖 PATH）
python -m uvicorn backend.main:app --reload

# Windows 如果 uvicorn 不在 PATH
C:\Users\<你的用户名>\AppData\Roaming\Python\Python313\Scripts\uvicorn.exe backend.main:app --reload
```

### 关闭

**方法 1（推荐）**：点击网页右下角 ⏹ 按钮，服务端会优雅退出。

**方法 2**：在运行 uvicorn 的终端按 `Ctrl+C`。

**方法 3**：通过 API
```bash
curl -X POST http://127.0.0.1:8000/api/server/shutdown
```

### 重启

关闭后在原终端重新运行启动命令即可。如果使用 `--reload` 模式，修改 Python 文件后 uvicorn 会**自动热重载**，无需手动重启。

---

## 文件结构

```
Calling/
├── backend/
│   ├── main.py           # FastAPI 应用，所有 HTTP 端点
│   ├── agent.py          # 多 Provider 工具调用逻辑（Claude/Gemini/Grok）
│   ├── translate.py      # 文档翻译：解析 → 分块 → LLM 翻译 → 输出
│   ├── config.py         # 环境变量加载
│   ├── conversation_store.py  # 会话持久化（JSON）
│   ├── ingest.py         # RAG 文件入库
│   ├── rag_store.py      # SQLite 向量存储（余弦相似度）
│   ├── embeddings.py     # Gemini embedding 封装
│   ├── tools.py          # web_search / read_file 工具实现
│   └── util.py           # 通用工具函数
├── frontend/
│   ├── index.html        # 单页应用入口
│   └── static/
│       ├── app.js        # 全部前端逻辑
│       └── styles.css    # 样式
├── data/
│   ├── uploads/          # 上传文件存放目录
│   ├── conversations.json
│   └── rag.sqlite3       # RAG 向量数据库
├── .env.example
└── requirements.txt
```

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/models` | 可用模型列表 |
| POST | `/api/conversations/new` | 新建会话 |
| GET | `/api/conversations` | 列出所有会话 |
| GET | `/api/conversations/{id}` | 获取会话详情 |
| DELETE | `/api/conversations/{id}` | 删除会话 |
| POST | `/api/upload` | 上传文件（支持 RAG） |
| POST | `/api/chat` | 发送消息（返回完整 JSON） |
| GET | `/api/translate/languages` | 可用语言 + 分隔符预设列表 |
| POST | `/api/translate` | 翻译文件（同步，等待全部完成） |
| POST | `/api/translate/stream` | 翻译文件（SSE 流式，逐块返回） |
| POST | `/api/translate/abort/{job_id}` | 中止流式翻译任务 |

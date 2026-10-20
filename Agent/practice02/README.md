# files-oper-func

> 带 **Function Call（工具调用）** 的多轮 LLM 对话脚本，内置 12 个工具，支持系统信息查询与文件/目录的读写、创建、删除、重命名等操作。

---

## 1. 项目简介

`files-oper-func.py` 是一个基于 OpenAI 兼容接口的命令行聊天脚本。用户输入自然语言，模型可自主决定调用预定义的工具（Function Calling），脚本执行工具并把结果回传给模型，最终由模型整合后回答，从而完成多轮、可操作本地文件系统的对话。

脚本具备**安全沙箱机制**：所有文件操作都被限制在项目根目录 `LLM-Course` 之内，防止路径越界。

---

## 2. 目录结构

```
practice02/
├── files-oper-func.py                  # 主程序（本脚本）
├── files-oper-func-architecture.mmd    # Mermaid 代码架构图
├── config.ini                          # LLM 配置（base_url / api_key / model）
├── README.md                           # 本文档
├── chat.py                             # 早期示例脚本
└── chat_days.py                        # 早期示例脚本
```

---

## 3. 配置文件 `config.ini`

程序启动时通过 `configparser` 读取同目录下的 `config.ini`，需包含 `[llm]` 节：

```ini
[llm]
base_url = https://your-api-endpoint/v1
api_key  = your-api-key
model    = your-model-name
```

---

## 4. 架构总览

```
配置初始化 → 多轮对话主循环 → 工具调用解析与派发 → 工具注册表 → 底层依赖
```

整体流程：

1. **配置与初始化**：读取 `config.ini`，创建 `OpenAI` 客户端；计算安全根目录 `ROOT`。
2. **多轮对话主循环**：读取用户输入 → 调用 `chat.completions.create()` → 判断是否有 `tool_calls`。
3. **工具调用解析与派发**：解析 JSON 参数 → 通过 `TOOL_HANDLERS` 字典派发 → 经 `_safe()` 路径校验 → `try/except` 处理异常 → 结果回填并再次请求模型。
4. **工具注册表**：`TOOLS`（供模型识别的函数描述）+ `TOOL_HANDLERS`（工具名到实现函数的映射）。
5. **底层依赖**：`subprocess`、`os`、`shutil`、`json`、`datetime`、`openai`。

> 详细可视化架构见 [`files-oper-func-architecture.mmd`](./files-oper-func-architecture.mmd)。

---

## 5. 安全机制

| 机制 | 说明 |
|------|------|
| `ROOT` 安全根目录 | 固定为 `LLM-Course` 项目根，所有相对路径均拼接到此目录下 |
| `_safe(path)` | 将路径转为绝对路径并校验 `startswith(ROOT)`，越界抛出 `PermissionError` |
| `TEXT_EXT` 白名单 | `readFile` / `editFile` 仅允许读取/编辑纯文本扩展名（`.txt/.py/.json/.md/.ini/.csv` 等） |
| 异常兜底 | 工具执行包裹 `try/except`，捕获 `PermissionError`、`FileNotFoundError` 及通用异常 |

纯文本扩展名白名单 `TEXT_EXT`：

```
.txt .py .json .md .ini .csv .js .ts .log .xml .yaml .yml
.html .css .java .c .cpp .h .sh .bat
```

---

## 6. 内置工具一览（共 12 个）

### 6.1 系统信息类（原有 2 个）

| 工具名 | 对应实现 | 说明 |
|--------|----------|------|
| `getDate` | `get_date()` | 获取当前电脑的日期和时间 |
| `isLeapYear` | `is_leap_year(year)` | 判断某年份是否为闰年 |

### 6.2 文件操作类（新增 10 个）

| 工具名 | 对应实现 | 说明 |
|--------|----------|------|
| `getCwd` | `get_cwd()` | 获取当前工作目录绝对路径（返回 `ROOT`） |
| `listDir` | `list_dir(path)` | 列出目录下所有文件与子目录（目录名后加 `/`） |
| `getFileType` | `get_file_type(path)` | 获取文件扩展名 |
| `readFile` | `read_file(path)` | 读取纯文本文件内容 |
| `createFile` | `create_file(path, content?)` | 创建纯文本文件，可附带初始内容 |
| `editFile` | `edit_file(path, content)` | 覆盖写入文件全部内容 |
| `createDir` | `create_dir(path)` | 创建目录（自动创建父目录） |
| `removeDir` | `remove_dir(path)` | 删除目录及其全部内容（谨慎使用） |
| `removeFile` | `remove_file(path)` | 删除指定文件 |
| `renamePath` | `rename_path(old_path, new_path)` | 重命名文件或目录 |

---

## 7. 核心代码结构

```python
# 1) 配置与客户端
cfg = configparser.ConfigParser()
cfg.read("config.ini", encoding="utf-8")
client = OpenAI(base_url=..., api_key=...)
ROOT = <LLM-Course 绝对路径>

# 2) 安全路径校验
def _safe(path): ...

# 3) 工具定义（供模型识别）
TOOLS = [ {...getDate...}, {...isLeapYear...}, ...文件操作10个... ]

# 4) 工具实现函数
def get_date(): ...
def list_dir(path): ...
def read_file(path): ...
# ...

# 5) 工具名到实现的派发字典
TOOL_HANDLERS = { "getDate": lambda args: get_date(), ... }

# 6) 多轮对话主循环
messages = []
while True:
    user_input = input("你: ")
    messages.append({"role": "user", "content": user_input})
    resp = client.chat.completions.create(model=..., messages=messages, tools=TOOLS)
    msg = resp.choices[0].message
    while msg.tool_calls:          # 处理工具调用
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            result = TOOL_HANDLERS[tc.function.name](args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        resp = client.chat.completions.create(...)  # 再次请求
        msg = resp.choices[0].message
    print("AI:", msg.content)
    messages.append({"role": "assistant", "content": msg.content})
```

---

## 8. 运行方式

```bash
# 确保已安装依赖
pip install openai

# 在同一目录准备好 config.ini 后运行
python files-oper-func.py
```

运行后即可用自然语言与 AI 交互，例如：

- 「现在几点了？」→ 触发 `getDate`
- 「列出 practice02 目录下的文件」→ 触发 `listDir`
- 「新建一个 notes.txt 并写入 Hello」→ 触发 `createFile`
- 「把 a.txt 重命名为 b.txt」→ 触发 `renamePath`

---

## 9. 依赖说明

| 依赖 | 用途 |
|------|------|
| `openai` | LLM 客户端与 Function Calling |
| `configparser` | 读取 `config.ini` |
| `subprocess` | 调用系统命令获取日期/时间 |
| `os` / `shutil` | 文件与目录的读写、创建、删除、重命名 |
| `json` | 解析工具调用的参数 |
| `datetime` | 时间相关（闰年判断等） |

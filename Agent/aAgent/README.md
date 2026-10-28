# aAgent

一个基于 LLM Function Calling 的本地智能助手：终端界面（TUI）负责交互，核心层负责对话编排与工具执行，可查询日期时间、判断闰年，并对工作区内的文件进行增删改查。

代码按「核心 / 界面」分层，新增 Web、Desktop 等界面版本时无需改动业务逻辑。

---

## 功能

| 类别 | 工具 | 说明 |
|------|------|------|
| 日期时间 | `getDate` | 调用系统命令获取当前日期和时间 |
| 日期时间 | `isLeapYear` | 判断指定年份是否为闰年 |
| 网络搜索 | `searchWeb` | 通过百度千帆联网搜索，获取互联网上的最新信息（实时事件、新闻、价格、官网文档等） |
| 网页抓取 | `fetchWeb` | 用 curl 获取指定网页源码，trafilatura 提取正文并转为 Markdown（保留标题、段落、列表、表格、链接） |
| 文件 | `getCwd` | 获取工作区根目录 |
| 文件 | `listDir` | 列出目录下的文件和子目录 |
| 文件 | `getFileType` | 获取文件的扩展名类型 |
| 文件 | `readFile` | 读取纯文本文件内容 |
| 文件 | `createFile` | 创建文件（可附带初始内容） |
| 文件 | `editFile` | 覆盖写入文件内容 |
| 文件 | `createDir` | 创建目录（自动创建父目录） |
| 文件 | `removeDir` | 删除目录及其全部内容 |
| 文件 | `removeFile` | 删除文件 |
| 文件 | `renamePath` | 重命名文件或目录 |

所有文件操作都限制在配置的工作区目录内，读写的文件类型限定为常见纯文本格式（`.txt`、`.py`、`.json`、`.md`、`.ini`、`.csv` 等）。

---

## 目录结构

```
aAgent/
├── config.ini               # LLM 与工作区配置
├── main.py                  # TUI 入口：装配依赖并启动界面
├── core/                    # 业务内核（不依赖任何界面）
│   ├── config.py            #   读取 config.ini
│   ├── llm.py               #   LLM 客户端封装
│   ├── agent.py             #   消息历史 + 工具调用循环
│   └── tools/
│       ├── registry.py      #   Tool 抽象与注册表
│       ├── datetime_tools.py
│       ├── file_tools.py
│       ├── fetch_tools.py
│       └── web_tools.py
└── ui/
    └── tui/app.py           # Textual 终端界面
```

---

## 环境要求

- Python 3.9 及以上
- 系统依赖：`curl`（已预装在 Windows 10+）
- Python 依赖：`openai`、`textual`、`trafilatura`

安装依赖：

```bash
pip install openai textual trafilatura
```

---

## 配置

编辑同目录下的 `config.ini`：

```ini
[llm]
base_url = https://api.deepseek.com
api_key = sk-你的密钥
model = deepseek-flash

[agent]
workspace_root = D:\LLM-Course
system_prompt = 你是一个可以查询日期时间、操作本地文件的智能助手。

[search]
baidu_qianfan_api_key = bce-v3/你的百度千帆密钥
; base_url = https://qianfan.baidubce.com/v2/ai_search   ; 可选，默认百度千帆
```

| 配置项 | 说明 |
|--------|------|
| `base_url`（[llm]） | OpenAI 兼容接口地址 |
| `api_key`（[llm]） | LLM 接口密钥 |
| `model` | 模型名称 |
| `workspace_root` | 文件工具允许访问的根目录；不填则默认为配置文件上两级目录 |
| `system_prompt` | 系统提示词，可省略 |
| `baidu_qianfan_api_key`（[search]） | 百度千帆 AI 搜索 API Key；不配则 searchWeb 工具不注册 |
| `base_url`（[search]） | 搜索 API 地址，可省略 |

> `config.ini` 中含真实密钥，请勿提交到公开仓库或分享给他人。

---

## 运行

```bash
python main.py
```

Windows 下若使用指定解释器：

```powershell
D:\Python\Python39\python.exe D:\LLM-Course\Agent\aAgent\main.py
```

在任意目录启动都可以，配置路径按脚本所在目录解析。

---

## 使用示例

在输入框输入问题后按回车：

- `现在几点了？`
- `2024 年是闰年吗？今年呢？`
- `列出 Playground 目录下的文件`
- `在 Playground 下创建 demo 目录，写一个 hello.txt，内容是 Hello`
- `把 hello.txt 重命名为 hi.txt，再读出来看看`
- `2026 年国庆假期放几天？`
- `帮我搜一下 Python 3.13 有哪些新特性`
- `打开 https://docs.python.org/3/whatsnew/3.13.html 帮我总结一下`

界面会依次显示：用户消息卡片 → 工具调用卡片（参数、结果、耗时）→ AI 最终回复。

### 快捷键

| 按键 | 作用 |
|------|------|
| `Enter` | 发送输入 |
| `Ctrl+N` | 新会话（清空上下文，思考中不可用） |
| `Ctrl+L` | 清空日志显示（不改变上下文） |
| `Ctrl+B` | 收起 / 展开右侧栏 |
| `Ctrl+Q` | 退出 |

---

## 扩展

### 新增一个工具

1. 在 `core/tools/` 下新建模块（如 `weather_tools.py`），实现 `register_weather_tools(registry)`；
2. 用 `registry.add(Tool(name, description, handler, parameters))` 注册，`handler` 接收参数字典并返回字符串；
3. 在 `core/tools/__init__.py` 中导出；
4. 在 `main.py` 的 `build()` 中调用注册函数。

工具抛出的异常由 `ToolRegistry.execute` 统一转换为文本返回给模型，不需要在工具内部处理。

### 新增一个界面

新建 `ui/web/`、`ui/desktop/` 等目录，只依赖 `core` 的公开接口：

```python
agent, settings, tools = build(Path("config.ini"))
answer = agent.send("现在几点？", on_tool=on_tool)
```

`on_tool(name, args, result, elapsed)` 用于展示工具调用过程；耗时单位是秒。业务逻辑无需改动，界面自行决定渲染方式。

---

## 设计说明

| 层 | 职责 | 依赖约束 |
|----|------|----------|
| `core/tools` | 工具定义、Schema、执行、异常兜底 | 不感知 LLM 与界面 |
| `core/agent` | 维护消息历史、驱动 tool_calls 循环 | 不 import 任何 UI 模块、不直接输出 |
| `core/llm` | 封装一次对话请求 | 唯一接触 `openai` SDK 的模块 |
| `ui/tui` | 输入、渲染、后台线程调度 | 仅使用 core 公开接口与传入的展示数据 |

LLM 调用在 Textual 的后台线程执行，通过 `call_from_thread` 回到界面线程更新，避免界面卡顿。

### 安全边界

- 所有路径都会解析为绝对路径，并校验必须位于 `workspace_root` 之内，越界直接拒绝；
- 读写文件仅允许纯文本扩展名，二进制文件会被拒绝；
- `removeDir` 会递归删除且无二次确认，使用时请确认模型给出的路径正确。

---

## 常见问题

**Q：启动后提示 `No module named 'textual'`？**
A：当前解释器未安装依赖，执行 `pip install textual openai`，或改用已安装依赖的解释器运行。

**Q：界面显示"调用失败"？**
A：依次检查网络是否可访问 `base_url`、`api_key` 是否有效、`model` 名称是否正确；错误信息会显示在红色卡片中。

**Q：文件工具提示"路径越界"？**
A：模型给出的路径超出了 `workspace_root`。把 `workspace_root` 调整为要操作的目录，或在提问时使用工作区内的相对路径。

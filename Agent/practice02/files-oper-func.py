#!/usr/bin/env python3
"""带 Function Call 的多轮 LLM 对话脚本（含文件操作）。"""
import configparser
import json
import os
import shutil
import subprocess
from datetime import datetime

from openai import OpenAI

cfg = configparser.ConfigParser()
cfg.read(os.path.join(os.path.dirname(__file__), "config.ini"), encoding="utf-8")

client = OpenAI(
    base_url=cfg["llm"]["base_url"],
    api_key=cfg["llm"]["api_key"],
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))  # 安全根目录：LLM-Course

TEXT_EXT = {".txt", ".py", ".json", ".md", ".ini", ".csv", ".js", ".ts",
            ".log", ".xml", ".yaml", ".yml", ".html", ".css", ".java",
            ".c", ".cpp", ".h", ".sh", ".bat"}


def _safe(path: str) -> str:
    """把相对路径拼到 ROOT 下，并校验绝对路径不越界。"""
    p = os.path.abspath(os.path.join(ROOT, path))
    if not p.startswith(ROOT):
        raise PermissionError(f"路径越界: {path}")
    return p


TOOLS = [
    # —— 原有的 2 个工具 ——
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "判断某个年份是否是闰年",
            "parameters": {
                "type": "object",
                "properties": {"year": {"type": "integer"}},
                "required": ["year"],
            },
        },
    },
    # —— 新增 10 个文件操作工具 ——
    {
        "type": "function",
        "function": {
            "name": "getCwd",
            "description": "获取当前工作目录的绝对路径",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listDir",
            "description": "列出指定目录下所有文件和子目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，可传空或.表示当前目录"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定文件的文件类型（扩展名）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readFile",
            "description": "获取指定文件的内容，仅支持纯文本格式文件",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createFile",
            "description": "根据指定的目录和文件名创建新的纯文本文件，可附带初始内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件完整路径，如 docs/readme.txt"},
                    "content": {"type": "string", "description": "初始内容，可省略"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editFile",
            "description": "覆盖写入指定文件的全部内容，仅支持纯文本格式文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "新的完整内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createDir",
            "description": "创建新目录（自动创建父目录）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "removeDir",
            "description": "删除目录及其下所有内容（非空目录也可删除），谨慎使用",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "removeFile",
            "description": "删除指定文件",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "renamePath",
            "description": "重命名文件或目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {"type": "string", "description": "原路径"},
                    "new_path": {"type": "string", "description": "新路径"},
                },
                "required": ["old_path", "new_path"],
            },
        },
    },
]


# —— 原有工具实现 ——

def get_date():
    d = subprocess.run(["date", "/t"], capture_output=True, text=True, shell=True).stdout.strip()
    t = subprocess.run(["time", "/t"], capture_output=True, text=True, shell=True).stdout.strip()
    return f"{d} {t}"


def is_leap_year(year: int) -> str:
    leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    return f"{year} 年是{'闰年' if leap else '平年'}"


# —— 新增 10 个文件工具实现 ——

def get_cwd() -> str:
    return ROOT


def list_dir(path: str) -> str:
    p = _safe(path or ".")
    if not os.path.isdir(p):
        return f"错误: {path} 不是目录"
    items = sorted(os.listdir(p))
    lines = []
    for name in items:
        full = os.path.join(p, name)
        mark = "/" if os.path.isdir(full) else ""
        lines.append(f"{mark}{name}")
    return "\n".join(lines) if lines else "(空目录)"


def get_file_type(path: str) -> str:
    p = _safe(path)
    if not os.path.exists(p):
        return f"错误: {path} 不存在"
    ext = os.path.splitext(p)[1].lower()
    return f"{path} 的类型是: {ext if ext else '(无扩展名)'}"


def read_file(path: str) -> str:
    p = _safe(path)
    if not os.path.isfile(p):
        return f"错误: {path} 不是文件"
    ext = os.path.splitext(p)[1].lower()
    if ext not in TEXT_EXT:
        return f"错误: {ext} 不是纯文本格式，不支持读取"
    with open(p, encoding="utf-8", errors="replace") as f:
        content = f.read()
    return content if content else "(空文件)"


def create_file(path: str, content: str = "") -> str:
    p = _safe(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"已创建文件 {path}"


def edit_file(path: str, content: str) -> str:
    p = _safe(path)
    if not os.path.isfile(p):
        return f"错误: {path} 不存在"
    ext = os.path.splitext(p)[1].lower()
    if ext not in TEXT_EXT:
        return f"错误: {ext} 不是纯文本格式，不支持编辑"
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"已更新文件 {path}"


def create_dir(path: str) -> str:
    p = _safe(path)
    os.makedirs(p, exist_ok=True)
    return f"已创建目录 {path}"


def remove_dir(path: str) -> str:
    p = _safe(path)
    if not os.path.isdir(p):
        return f"错误: {path} 不是目录"
    shutil.rmtree(p)
    return f"已删除目录 {path}"


def remove_file(path: str) -> str:
    p = _safe(path)
    if not os.path.isfile(p):
        return f"错误: {path} 不是文件"
    os.remove(p)
    return f"已删除文件 {path}"


def rename_path(old_path: str, new_path: str) -> str:
    old = _safe(old_path)
    new = _safe(new_path)
    if not os.path.exists(old):
        return f"错误: {old_path} 不存在"
    os.rename(old, new)
    return f"已将 {old_path} 重命名为 {new_path}"


# —— 字典派发：工具名 → 实现函数 ——

TOOL_HANDLERS = {
    "getDate": lambda args: get_date(),
    "isLeapYear": lambda args: is_leap_year(args["year"]),
    "getCwd": lambda args: get_cwd(),
    "listDir": lambda args: list_dir(args["path"]),
    "getFileType": lambda args: get_file_type(args["path"]),
    "readFile": lambda args: read_file(args["path"]),
    "createFile": lambda args: create_file(args["path"], args.get("content", "")),
    "editFile": lambda args: edit_file(args["path"], args["content"]),
    "createDir": lambda args: create_dir(args["path"]),
    "removeDir": lambda args: remove_dir(args["path"]),
    "removeFile": lambda args: remove_file(args["path"]),
    "renamePath": lambda args: rename_path(args["old_path"], args["new_path"]),
}


messages = []
while True:
    user_input = input("你: ")
    messages.append({"role": "user", "content": user_input})
    resp = client.chat.completions.create(
        model=cfg["llm"]["model"],
        messages=messages,
        tools=TOOLS,
    )
    msg = resp.choices[0].message
    while msg.tool_calls:
        messages.append(msg)
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            handler = TOOL_HANDLERS.get(tc.function.name)
            if handler is None:
                result = f"未知工具: {tc.function.name}"
            else:
                try:
                    result = handler(args)
                except PermissionError as e:
                    result = str(e)
                except FileNotFoundError as e:
                    result = f"文件/目录不存在: {e}"
                except Exception as e:
                    result = f"执行错误: {type(e).__name__}: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        resp = client.chat.completions.create(
            model=cfg["llm"]["model"],
            messages=messages,
            tools=TOOLS,
        )
        msg = resp.choices[0].message
    print("AI:", msg.content)
    messages.append({"role": "assistant", "content": msg.content})

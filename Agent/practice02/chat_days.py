#!/usr/bin/env python3
"""带 Function Call 的多轮 LLM 对话脚本（含日期差计算）。"""
import configparser
import os
import json
import subprocess
from datetime import datetime

from openai import OpenAI

cfg = configparser.ConfigParser()
cfg.read(os.path.join(os.path.dirname(__file__), "config.ini"), encoding="utf-8")

client = OpenAI(
    base_url=cfg["llm"]["base_url"],
    api_key=cfg["llm"]["api_key"],
)

TOOLS = [
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
                "properties": {
                    "year": {"type": "integer", "description": "要判断的年份，如 2024"}
                },
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "daysBetween",
            "description": "计算两个日期之间相差多少天",
            "parameters": {
                "type": "object",
                "properties": {
                    "date1": {"type": "string", "description": "起始日期，格式 YYYY-MM-DD，如 2024-01-01"},
                    "date2": {"type": "string", "description": "结束日期，格式 YYYY-MM-DD，如 2024-12-31"},
                },
                "required": ["date1", "date2"],
            },
        },
    },
]


def get_date():
    d = subprocess.run(["date", "/t"], capture_output=True, text=True, shell=True).stdout.strip()
    t = subprocess.run(["time", "/t"], capture_output=True, text=True, shell=True).stdout.strip()
    return f"{d} {t}"


def is_leap_year(year: int) -> str:
    leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    return f"{year} 年是{'闰年' if leap else '平年'}"


def days_between(date1: str, date2: str) -> str:
    d1 = datetime.strptime(date1, "%Y-%m-%d")
    d2 = datetime.strptime(date2, "%Y-%m-%d")
    diff = abs((d2 - d1).days)
    return f"{date1} 和 {date2} 相差 {diff} 天"


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
            if tc.function.name == "getDate":
                result = get_date()
            elif tc.function.name == "isLeapYear":
                result = is_leap_year(args["year"])
            elif tc.function.name == "daysBetween":
                result = days_between(args["date1"], args["date2"])
            else:
                result = f"未知工具: {tc.function.name}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        resp = client.chat.completions.create(
            model=cfg["llm"]["model"],
            messages=messages,
            tools=TOOLS,
        )
        msg = resp.choices[0].message
    print("AI:", msg.content)
    messages.append({"role": "assistant", "content": msg.content})

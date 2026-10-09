#!/usr/bin/env python3
"""最简单的一次性 LLM 对话脚本。"""
import configparser
import os

from openai import OpenAI

cfg = configparser.ConfigParser()
cfg.read(os.path.join(os.path.dirname(__file__), "config.ini"), encoding="utf-8")

client = OpenAI(
    base_url=cfg["llm"]["base_url"],
    api_key=cfg["llm"]["api_key"],
)

messages = []
while True:
    user_input = input("你: ")
    messages.append({"role": "user", "content": user_input})
    resp = client.chat.completions.create(
        model=cfg["llm"]["model"],
        messages=messages,
        stream=True,
    )
    print("AI: ", end="", flush=True)
    answer = ""
    for chunk in resp:
        content = chunk.choices[0].delta.content
        if content is not None:
            answer += content
            print(content, end="", flush=True)
    messages.append({"role": "assistant", "content": answer})
    print()

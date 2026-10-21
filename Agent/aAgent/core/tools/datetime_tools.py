"""日期时间类工具。"""
import subprocess

from .registry import Tool, ToolRegistry


def _get_date() -> str:
    date = subprocess.run(["date", "/t"], capture_output=True, text=True, shell=True).stdout.strip()
    clock = subprocess.run(["time", "/t"], capture_output=True, text=True, shell=True).stdout.strip()
    return f"{date} {clock}"


def _is_leap_year(year: int) -> str:
    leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    return f"{year} 年是{'闰年' if leap else '平年'}"


def register_datetime_tools(registry: ToolRegistry) -> None:
    registry.add(Tool("getDate", "获取当前电脑的日期和时间", lambda args: _get_date()))
    registry.add(Tool(
        "isLeapYear",
        "判断某个年份是否是闰年",
        lambda args: _is_leap_year(args["year"]),
        {
            "type": "object",
            "properties": {"year": {"type": "integer", "description": "要判断的年份，如 2024"}},
            "required": ["year"],
        },
    ))

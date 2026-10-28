"""应用配置：从 config.ini 读取，供任意界面层复用。"""
from dataclasses import dataclass
from pathlib import Path
import configparser
from typing import Optional


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class SearchConfig:
    api_key: str
    base_url: str = "https://qianfan.baidubce.com/v2/ai_search"


@dataclass(frozen=True)
class Settings:
    llm: LLMConfig
    workspace_root: str
    system_prompt: str = ""
    search: Optional[SearchConfig] = None


def load_settings(config_path: Path) -> Settings:
    config_path = Path(config_path).resolve()
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")

    llm = LLMConfig(
        base_url=cfg["llm"]["base_url"],
        api_key=cfg["llm"]["api_key"],
        model=cfg["llm"]["model"],
    )
    workspace_root = cfg.get("agent", "workspace_root", fallback=str(config_path.parents[2]))
    search = None
    if cfg.has_section("search") and cfg.has_option("search", "baidu_qianfan_api_key"):
        key = cfg["search"]["baidu_qianfan_api_key"].strip()
        if key:
            search = SearchConfig(
                api_key=key,
                base_url=cfg.get("search", "base_url", fallback="https://qianfan.baidubce.com/v2/ai_search"),
            )
    return Settings(
        llm=llm,
        workspace_root=str(Path(workspace_root).resolve()),
        system_prompt=cfg.get("agent", "system_prompt", fallback=""),
        search=search,
    )

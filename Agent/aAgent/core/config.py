"""应用配置：从 config.ini 读取，供任意界面层复用。"""
from dataclasses import dataclass
from pathlib import Path
import configparser


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class Settings:
    llm: LLMConfig
    workspace_root: str
    system_prompt: str = ""


def load_settings(config_path: Path) -> Settings:
    config_path = Path(config_path).resolve()
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")

    llm = LLMConfig(
        base_url=cfg["llm"]["base_url"],
        api_key=cfg["llm"]["api_key"],
        model=cfg["llm"]["model"],
    )
    # 未显式配置时，工作区取配置文件上两级目录（aAgent -> Agent -> LLM-Course）
    workspace_root = cfg.get("agent", "workspace_root", fallback=str(config_path.parents[2]))
    return Settings(
        llm=llm,
        workspace_root=str(Path(workspace_root).resolve()),
        system_prompt=cfg.get("agent", "system_prompt", fallback=""),
    )

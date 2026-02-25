from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass
class RuntimeConfig:
    token: str
    guild_id: int | None
    activity_text: str
    command_prefix: str
    owner_ids: set[int]


DEFAULT_CONFIG_PATH = Path("config.yaml")


def load_yaml_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a top-level mapping")

    return data


def load_runtime_config() -> RuntimeConfig:
    load_dotenv()

    yaml_cfg = load_yaml_config()

    token = os.getenv("DISCORD_TOKEN", yaml_cfg.get("discord_token", ""))
    if not token:
        raise ValueError("Missing DISCORD_TOKEN in environment or config.yaml")

    guild_raw = os.getenv("GUILD_ID", str(yaml_cfg.get("guild_id", "")).strip())
    guild_id = int(guild_raw) if guild_raw else None

    activity_text = os.getenv("ACTIVITY_TEXT", yaml_cfg.get("activity_text", "Managing your server"))
    command_prefix = os.getenv("COMMAND_PREFIX", yaml_cfg.get("command_prefix", "!"))

    owner_ids_raw = os.getenv("OWNER_IDS", yaml_cfg.get("owner_ids", ""))
    owner_ids = {
        int(user_id.strip())
        for user_id in str(owner_ids_raw).split(",")
        if user_id.strip().isdigit()
    }

    return RuntimeConfig(
        token=token,
        guild_id=guild_id,
        activity_text=activity_text,
        command_prefix=command_prefix,
        owner_ids=owner_ids,
    )

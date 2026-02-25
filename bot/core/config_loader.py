from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when a config file is invalid or missing required fields."""


_SNOWFLAKE_MAX = (1 << 63) - 1


def _is_snowflake(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 < value <= _SNOWFLAKE_MAX
    if isinstance(value, str) and value.isdigit():
        as_int = int(value)
        return 0 < as_int <= _SNOWFLAKE_MAX
    return False


def _as_int(value: Any, path: str) -> int:
    if not _is_snowflake(value):
        raise ConfigError(f"{path} must be a Discord snowflake ID (positive integer or numeric string).")
    return int(value)


def _ensure_type(value: Any, expected: type, path: str) -> Any:
    if not isinstance(value, expected):
        raise ConfigError(f"{path} must be {expected.__name__}, got {type(value).__name__}.")
    return value


def _validate_hex_color(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{path} must be a hex color string like '#5865F2'.")
    if value.startswith("#"):
        value = value[1:]
    if len(value) not in {3, 6} or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ConfigError(f"{path} must be a valid 3 or 6 digit hex color.")
    return f"#{value.upper()}"


def _validate_buttons(buttons: Any, path: str) -> list[dict[str, Any]]:
    if buttons is None:
        return []
    _ensure_type(buttons, list, path)
    validated: list[dict[str, Any]] = []
    for i, button in enumerate(buttons):
        button_path = f"{path}[{i}]"
        _ensure_type(button, dict, button_path)
        label = button.get("label")
        action = button.get("action")
        if not label or not isinstance(label, str):
            raise ConfigError(f"{button_path}.label is required and must be a string.")
        if not action or not isinstance(action, str):
            raise ConfigError(f"{button_path}.action is required and must be a string.")
        style = button.get("style", "primary")
        if style not in {"primary", "secondary", "success", "danger", "link"}:
            raise ConfigError(
                f"{button_path}.style must be one of primary, secondary, success, danger, link."
            )
        validated.append(
            {
                "label": label,
                "action": action,
                "style": style,
                "emoji": button.get("emoji"),
                "disabled": bool(button.get("disabled", False)),
            }
        )
    return validated


def _validate_embed_customization(config: dict[str, Any], path: str, default_color: str) -> dict[str, Any]:
    embed = config.get("embed", {})
    _ensure_type(embed, dict, f"{path}.embed")

    images = embed.get("images", {})
    _ensure_type(images, dict, f"{path}.embed.images")

    messages = config.get("messages", {})
    _ensure_type(messages, dict, f"{path}.messages")

    color = embed.get("color", default_color)

    return {
        "title": embed.get("title", ""),
        "body": embed.get("body", ""),
        "footer": embed.get("footer", ""),
        "images": {
            "thumbnail": images.get("thumbnail", ""),
            "image": images.get("image", ""),
            "icon": images.get("icon", ""),
        },
        "buttons": _validate_buttons(embed.get("buttons", []), f"{path}.embed.buttons"),
        "color": _validate_hex_color(color, f"{path}.embed.color"),
        "messages": messages,
    }


@dataclass(frozen=True)
class LoadedConfig:
    bot: dict[str, Any]
    welcome: dict[str, Any]
    tickets: dict[str, Any]
    status: dict[str, Any]
    music: dict[str, Any]
    join_to_create_vc: dict[str, Any]
    levels: dict[str, Any]


class ConfigLoader:
    def __init__(self, config_dir: str | Path = "config") -> None:
        self.config_dir = Path(config_dir)

    def _read_yaml(self, file_name: str) -> dict[str, Any]:
        path = self.config_dir / file_name
        if not path.exists():
            raise ConfigError(f"Required config file is missing: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ConfigError(f"{path} must contain a top-level mapping/object.")
        return data

    def _require(self, data: dict[str, Any], key: str, path: str) -> Any:
        if key not in data:
            raise ConfigError(f"Missing required field: {path}.{key}")
        return data[key]

    def _load_bot(self) -> dict[str, Any]:
        data = self._read_yaml("bot.yml")
        theme = data.get("theme", {})
        _ensure_type(theme, dict, "bot.theme")
        return {
            "token": _ensure_type(self._require(data, "token", "bot"), str, "bot.token"),
            "guild_id": _as_int(self._require(data, "guild_id", "bot"), "bot.guild_id"),
            "theme": {
                "name": theme.get("name", "default"),
                "color": _validate_hex_color(theme.get("color", "#5865F2"), "bot.theme.color"),
                "success_color": _validate_hex_color(
                    theme.get("success_color", "#57F287"), "bot.theme.success_color"
                ),
                "error_color": _validate_hex_color(
                    theme.get("error_color", "#ED4245"), "bot.theme.error_color"
                ),
            },
        }

    def _load_welcome(self, default_color: str) -> dict[str, Any]:
        data = self._read_yaml("welcome.yml")
        return {
            "enabled": bool(data.get("enabled", True)),
            "channel_id": _as_int(self._require(data, "channel_id", "welcome"), "welcome.channel_id"),
            "mention_new_member": bool(data.get("mention_new_member", False)),
            "embed": _validate_embed_customization(data, "welcome", default_color),
        }

    def _load_tickets(self, default_color: str) -> dict[str, Any]:
        data = self._read_yaml("tickets.yml")
        support_roles = data.get("support_role_ids", [])
        _ensure_type(support_roles, list, "tickets.support_role_ids")
        return {
            "enabled": bool(data.get("enabled", True)),
            "panel_channel_id": _as_int(
                self._require(data, "panel_channel_id", "tickets"), "tickets.panel_channel_id"
            ),
            "category_id": _as_int(self._require(data, "category_id", "tickets"), "tickets.category_id"),
            "support_role_ids": [
                _as_int(role_id, f"tickets.support_role_ids[{i}]") for i, role_id in enumerate(support_roles)
            ],
            "transcript_channel_id": _as_int(
                data.get("transcript_channel_id", data["panel_channel_id"]), "tickets.transcript_channel_id"
            ),
            "embed": _validate_embed_customization(data, "tickets", default_color),
        }

    def _load_status(self, default_color: str) -> dict[str, Any]:
        data = self._read_yaml("status.yml")
        rotations = data.get("rotations", [])
        _ensure_type(rotations, list, "status.rotations")
        return {
            "enabled": bool(data.get("enabled", True)),
            "interval_seconds": int(data.get("interval_seconds", 300)),
            "rotations": [str(item) for item in rotations],
            "embed": _validate_embed_customization(data, "status", default_color),
        }

    def _load_music(self, default_color: str) -> dict[str, Any]:
        data = self._read_yaml("music.yml")
        return {
            "enabled": bool(data.get("enabled", True)),
            "default_volume": int(data.get("default_volume", 75)),
            "max_queue_size": int(data.get("max_queue_size", 100)),
            "embed": _validate_embed_customization(data, "music", default_color),
        }

    def _load_join_to_create(self, default_color: str) -> dict[str, Any]:
        data = self._read_yaml("join_to_create_vc.yml")
        return {
            "enabled": bool(data.get("enabled", True)),
            "join_channel_id": _as_int(
                self._require(data, "join_channel_id", "join_to_create_vc"), "join_to_create_vc.join_channel_id"
            ),
            "category_id": _as_int(
                self._require(data, "category_id", "join_to_create_vc"), "join_to_create_vc.category_id"
            ),
            "name_template": str(data.get("name_template", "{user}'s room")),
            "embed": _validate_embed_customization(data, "join_to_create_vc", default_color),
        }

    def _load_levels(self, default_color: str) -> dict[str, Any]:
        data = self._read_yaml("levels.yml")
        reward_roles = data.get("reward_roles", {})
        _ensure_type(reward_roles, dict, "levels.reward_roles")
        validated_reward_roles: dict[int, int] = {}
        for level, role_id in reward_roles.items():
            if not str(level).isdigit():
                raise ConfigError("levels.reward_roles keys must be numeric levels.")
            validated_reward_roles[int(level)] = _as_int(role_id, f"levels.reward_roles[{level}]")

        return {
            "enabled": bool(data.get("enabled", True)),
            "xp_per_message": int(data.get("xp_per_message", 15)),
            "cooldown_seconds": int(data.get("cooldown_seconds", 60)),
            "level_up_channel_id": _as_int(
                self._require(data, "level_up_channel_id", "levels"), "levels.level_up_channel_id"
            ),
            "reward_roles": validated_reward_roles,
            "embed": _validate_embed_customization(data, "levels", default_color),
        }

    def load_all(self) -> LoadedConfig:
        bot = self._load_bot()
        default_color = bot["theme"]["color"]
        return LoadedConfig(
            bot=bot,
            welcome=self._load_welcome(default_color),
            tickets=self._load_tickets(default_color),
            status=self._load_status(default_color),
            music=self._load_music(default_color),
            join_to_create_vc=self._load_join_to_create(default_color),
            levels=self._load_levels(default_color),
        )

from __future__ import annotations

from pathlib import Path
from typing import Any

import discord
from discord.ext import commands
import yaml


class VoiceCreate(commands.Cog):
    """Join-to-create temporary voice channels."""

    CONFIG_PATH = Path("config/join_to_create_vc.yml")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.config = self._load_config()
        self._active_temp_channels: dict[int, set[int]] = {}

    def _load_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "trigger_channel_id": 0,
            "category_id": 0,
            "channel_name_template": "{user}'s-VC",
            "user_limit": 25,
            "max_temp_channels": 7,
            "cap_reached_message": "Temporary voice channel limit has been reached.",
            "cap_reached_embed": {
                "enabled": True,
                "title": "Voice Channels Full",
                "description": "Please wait until a temporary channel is available.",
                "color": "0x3498db",
            },
        }

        if not self.CONFIG_PATH.exists():
            return defaults

        with self.CONFIG_PATH.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file) or {}

        merged = defaults.copy()
        merged.update({k: v for k, v in loaded.items() if k in defaults})
        if isinstance(loaded.get("cap_reached_embed"), dict):
            embed_cfg = defaults["cap_reached_embed"].copy()
            embed_cfg.update(loaded["cap_reached_embed"])
            merged["cap_reached_embed"] = embed_cfg
        return merged

    async def _notify_limit_reached(self, member: discord.Member) -> None:
        embed_cfg = self.config.get("cap_reached_embed", {})
        message = self.config.get("cap_reached_message", "")

        embed: discord.Embed | None = None
        if embed_cfg.get("enabled", False):
            color_raw = str(embed_cfg.get("color", "0x3498db"))
            try:
                color_val = int(color_raw, 16) if color_raw.startswith("0x") else int(color_raw)
            except ValueError:
                color_val = 0x3498DB
            embed = discord.Embed(
                title=embed_cfg.get("title", "Voice Channels Full"),
                description=embed_cfg.get("description", message),
                color=color_val,
            )

        try:
            await member.send(content=message if message else None, embed=embed)
        except discord.Forbidden:
            pass

    def _guild_temp_channels(self, guild_id: int) -> set[int]:
        return self._active_temp_channels.setdefault(guild_id, set())

    async def _cleanup_deleted_channels(self, guild: discord.Guild) -> None:
        tracked = self._guild_temp_channels(guild.id)
        stale = {cid for cid in tracked if guild.get_channel(cid) is None}
        tracked.difference_update(stale)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        guild = member.guild
        await self._cleanup_deleted_channels(guild)

        if before.channel and before.channel.id in self._guild_temp_channels(guild.id):
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="Temporary voice channel emptied")
                finally:
                    self._guild_temp_channels(guild.id).discard(before.channel.id)

        trigger_channel_id = int(self.config.get("trigger_channel_id", 0))
        if not after.channel or after.channel.id != trigger_channel_id:
            return

        tracked = self._guild_temp_channels(guild.id)
        if len(tracked) >= int(self.config.get("max_temp_channels", 7)):
            await self._notify_limit_reached(member)
            return

        category = None
        configured_category_id = int(self.config.get("category_id", 0))
        if configured_category_id:
            category = guild.get_channel(configured_category_id)
        if category is None:
            category = after.channel.category

        channel_name = str(self.config.get("channel_name_template", "{user}'s-VC")).format(
            user=member.display_name,
        )
        user_limit = int(self.config.get("user_limit", 25))

        voice_channel = await guild.create_voice_channel(
            name=channel_name,
            category=category,
            user_limit=user_limit,
            reason=f"Temporary VC for {member}",
        )

        tracked.add(voice_channel.id)
        try:
            await member.move_to(voice_channel, reason="Moved to newly created temporary VC")
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceCreate(bot))

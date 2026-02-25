from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import discord
import yaml
from discord.ext import commands

DEFAULT_AUTOROLE_ID = 1472473308459958376
DEFAULT_CONFIG_PATH = Path("config/welcome.yml")


class Welcome(commands.Cog):
    """Handles new-member onboarding messages and role assignment."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        if not DEFAULT_CONFIG_PATH.exists():
            return {}

        with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            loaded = yaml.safe_load(config_file) or {}

        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _format_local_timestamp(timestamp: datetime) -> str:
        local_time = timestamp.astimezone()
        today = datetime.now().astimezone().date()

        if local_time.date() == today:
            return f"Today at {local_time.strftime('%I:%M %p')}"

        return local_time.strftime("%b %d, %Y at %I:%M %p")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild

        autorole_id = int(self.config.get("autorole_id", DEFAULT_AUTOROLE_ID))
        role = guild.get_role(autorole_id)

        if role is None:
            print(
                f"[Welcome] Auto-role {autorole_id} not found in guild "
                f"{guild.id} ({guild.name})."
            )
        else:
            try:
                await member.add_roles(role, reason="Configured auto-role on member join")
            except discord.Forbidden:
                print(
                    f"[Welcome] Missing permission to assign role {autorole_id} "
                    f"in guild {guild.id} ({guild.name})."
                )
            except discord.HTTPException as exc:
                print(
                    f"[Welcome] Failed assigning role {autorole_id} to member "
                    f"{member.id}: {exc}"
                )

        channel_id = self.config.get("welcome_channel_id")
        welcome_channel: discord.abc.Messageable | None = None

        if channel_id:
            welcome_channel = guild.get_channel(int(channel_id))

        if welcome_channel is None:
            welcome_channel = guild.system_channel

        if welcome_channel is None:
            print(
                f"[Welcome] No welcome channel configured/found for guild "
                f"{guild.id} ({guild.name})."
            )
            return

        joins_count = guild.member_count or 0
        joined_at = member.joined_at or discord.utils.utcnow()
        formatted_join_time = self._format_local_timestamp(joined_at)

        welcome_template = self.config.get(
            "welcome_text",
            "Welcome to **{server_name}**, {member_mention}!",
        )
        welcome_text = welcome_template.format(
            member_mention=member.mention,
            member_name=member.display_name,
            server_name=guild.name,
            member_count=joins_count,
        )

        connection_info = (
            f"You are member **#{joins_count}**.\n"
            f"Connected: **{formatted_join_time}**"
        )

        embed = discord.Embed(
            title=self.config.get("embed_title", "Welcome!"),
            description=f"{welcome_text}\n\n{connection_info}",
            color=discord.Color.blue(),
        )

        # Use avatar in author and thumbnail by default.
        avatar_url = member.display_avatar.url
        embed.set_author(name=member.display_name, icon_url=avatar_url)

        thumbnail_url = self.config.get("thumbnail_url") or avatar_url
        embed.set_thumbnail(url=thumbnail_url)

        banner_url = self.config.get("banner_url")
        if banner_url:
            embed.set_image(url=banner_url)

        embed.set_footer(text=formatted_join_time)

        try:
            await welcome_channel.send(embed=embed)
        except discord.Forbidden:
            print(
                f"[Welcome] Missing permission to send message in "
                f"channel {getattr(welcome_channel, 'id', 'unknown')} for guild "
                f"{guild.id} ({guild.name})."
            )
        except discord.HTTPException as exc:
            print(f"[Welcome] Failed to send welcome embed in guild {guild.id}: {exc}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))

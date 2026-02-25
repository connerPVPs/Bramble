from __future__ import annotations

import time
from typing import Dict, Optional

import discord
from discord.ext import commands

from bot.core.level_engine import (
    JsonLevelStorage,
    LevelConfig,
    LevelEngine,
    SQLiteLevelStorage,
)


class Levels(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        storage_path: str = "data/levels.json",
        use_sqlite: bool = False,
        announcement_channel_id: Optional[int] = None,
        level_roles: Optional[Dict[int, int]] = None,
        admin_commands_enabled: bool = True,
        cooldown_seconds: float = 45.0,
    ):
        self.bot = bot
        self.admin_commands_enabled = admin_commands_enabled
        self.announcement_channel_id = announcement_channel_id
        self.level_roles = level_roles or {25: 0, 50: 0, 75: 0, 100: 0}

        storage = SQLiteLevelStorage(storage_path) if use_sqlite else JsonLevelStorage(storage_path)
        self.engine = LevelEngine(
            storage=storage,
            config=LevelConfig(cooldown_seconds=cooldown_seconds),
            role_milestones=self.level_roles,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        update = self.engine.process_message(
            guild_id=message.guild.id,
            user_id=message.author.id,
            timestamp=time.time(),
        )

        if not update.leveled_up:
            return

        await self._apply_role_rewards(message.guild, message.author, update.reached_role_levels)

        if update.should_announce:
            await self._send_level_up_announcement(message.guild, message.author, update.new_level)

    async def _send_level_up_announcement(
        self,
        guild: discord.Guild,
        member: discord.Member,
        new_level: int,
    ) -> None:
        channel = (
            guild.get_channel(self.announcement_channel_id)
            if self.announcement_channel_id
            else guild.system_channel
        )
        if channel is None:
            return

        embed = discord.Embed(
            title="Level Up!",
            description=f"{member.mention} reached **Level {new_level}**.",
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Keep chatting to gain more XP.")
        await channel.send(embed=embed)

    async def _apply_role_rewards(
        self,
        guild: discord.Guild,
        member: discord.Member,
        reached_levels: list[int],
    ) -> None:
        for level in reached_levels:
            role_id = self.level_roles.get(level)
            if not role_id:
                continue
            role = guild.get_role(role_id)
            if role is None or role in member.roles:
                continue
            try:
                await member.add_roles(role, reason=f"Reached level {level}")
            except discord.Forbidden:
                continue

    @commands.group(name="level", invoke_without_command=True)
    async def level(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        target = member or ctx.author
        record = self.engine.get_record(ctx.guild.id, target.id)
        await ctx.send(f"{target.mention} is level **{record.level}** with **{record.total_xp}** XP.")

    @level.command(name="check")
    async def level_check(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self.level(ctx, member)

    @level.command(name="set")
    @commands.has_permissions(manage_guild=True)
    async def level_set(self, ctx: commands.Context, member: discord.Member, level: int) -> None:
        if not self.admin_commands_enabled:
            await ctx.send("Admin level commands are disabled.")
            return

        updated = self.engine.set_level(ctx.guild.id, member.id, level)
        await ctx.send(f"Set {member.mention} to level **{updated.level}**.")

    @level.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def level_reset(self, ctx: commands.Context, member: discord.Member) -> None:
        if not self.admin_commands_enabled:
            await ctx.send("Admin level commands are disabled.")
            return

        self.engine.reset_level(ctx.guild.id, member.id)
        await ctx.send(f"Reset level data for {member.mention}.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Levels(bot))

from __future__ import annotations

from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.embeds import EmbedFactory


class LevelsCog(commands.Cog, name="levels"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.xp: dict[int, int] = defaultdict(int)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        self.xp[message.author.id] += 5

    @app_commands.command(name="rank", description="Show your current level")
    async def rank(self, interaction: discord.Interaction) -> None:
        xp = self.xp.get(interaction.user.id, 0)
        level = int((xp / 100) ** 0.5)
        embed = EmbedFactory.info(
            "Rank",
            f"{interaction.user.mention}\nXP: `{xp}`\nLevel: `{level}`",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LevelsCog(bot))

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.embeds import EmbedFactory


class WelcomeCog(commands.Cog, name="welcome"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.system_channel is None:
            return

        embed = EmbedFactory.success(
            "Welcome!",
            f"{member.mention} joined **{member.guild.name}**. Enjoy your stay!",
        )
        await member.guild.system_channel.send(embed=embed)

    @app_commands.command(name="welcome", description="Send a test welcome message")
    async def welcome(self, interaction: discord.Interaction) -> None:
        embed = EmbedFactory.info("Welcome", f"Hello {interaction.user.mention} 👋")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))

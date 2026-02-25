from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from mcstatus import JavaServer

from bot.core.embeds import EmbedFactory


class StatusCog(commands.Cog, name="status"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="mcstatus", description="Check a Minecraft Java server status")
    async def mc_status(self, interaction: discord.Interaction, address: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            server = JavaServer.lookup(address)
            status = await server.async_status()
        except Exception as exc:  # network + remote server failures
            await interaction.followup.send(embed=EmbedFactory.error("Server Offline", str(exc)))
            return

        description = (
            f"Address: `{address}`\n"
            f"Players: `{status.players.online}/{status.players.max}`\n"
            f"Latency: `{status.latency:.2f}ms`"
        )
        await interaction.followup.send(embed=EmbedFactory.success("Minecraft Status", description))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatusCog(bot))

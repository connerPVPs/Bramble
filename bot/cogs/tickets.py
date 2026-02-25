from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.embeds import EmbedFactory
from bot.core.permissions import admin_only


class TicketsCog(commands.Cog, name="tickets"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ticket", description="Create a private support ticket channel")
    async def ticket(self, interaction: discord.Interaction, reason: str = "No reason provided") -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this command in a server.", ephemeral=True)
            return

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        channel_name = f"ticket-{interaction.user.name}".lower().replace(" ", "-")
        channel = await interaction.guild.create_text_channel(channel_name, overwrites=overwrites, reason=reason)

        embed = EmbedFactory.info("Ticket Created", f"Support will be with you shortly.\nReason: {reason}")
        await channel.send(content=interaction.user.mention, embed=embed)
        await interaction.response.send_message(f"Created ticket: {channel.mention}", ephemeral=True)

    @app_commands.command(name="close-ticket", description="Close and delete a ticket channel")
    @admin_only()
    async def close_ticket(self, interaction: discord.Interaction) -> None:
        if interaction.channel is None or not interaction.channel.name.startswith("ticket-"):
            await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
            return

        await interaction.response.send_message("Closing ticket in 5 seconds...")
        await interaction.channel.delete(reason=f"Closed by {interaction.user}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketsCog(bot))

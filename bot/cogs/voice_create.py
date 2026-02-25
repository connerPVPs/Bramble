from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.embeds import EmbedFactory
from bot.core.permissions import admin_only


class VoiceCreateCog(commands.Cog, name="voice_create"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.create_channel_ids: set[int] = set()
        self.temporary_channels: set[int] = set()

    @app_commands.command(name="set-create-voice", description="Set a voice channel as the auto-create lobby")
    @admin_only()
    async def set_create_voice(self, interaction: discord.Interaction, channel: discord.VoiceChannel) -> None:
        self.create_channel_ids.add(channel.id)
        await interaction.response.send_message(
            embed=EmbedFactory.success("Configured", f"{channel.mention} is now an auto-create lobby."),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if after.channel and after.channel.id in self.create_channel_ids and member.guild:
            new_channel = await member.guild.create_voice_channel(
                name=f"{member.display_name}'s Room",
                category=after.channel.category,
                reason="Temporary auto-created voice channel",
            )
            self.temporary_channels.add(new_channel.id)
            await member.move_to(new_channel)

        if before.channel and before.channel.id in self.temporary_channels and len(before.channel.members) == 0:
            self.temporary_channels.discard(before.channel.id)
            await before.channel.delete(reason="Temporary voice channel cleanup")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceCreateCog(bot))

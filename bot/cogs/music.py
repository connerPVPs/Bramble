from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

from bot.core.embeds import EmbedFactory


class MusicCog(commands.Cog, name="music"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="join", description="Join your current voice channel")
    async def join(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or interaction.user.voice is None:
            await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        if interaction.guild is None:
            await interaction.response.send_message("Use in a server.", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if voice_client:
            await voice_client.move_to(channel)
        else:
            await channel.connect()

        await interaction.response.send_message(f"Joined {channel.mention}")

    @app_commands.command(name="leave", description="Disconnect from voice")
    async def leave(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.voice_client is None:
            await interaction.response.send_message("I am not in a voice channel.", ephemeral=True)
            return

        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("Disconnected.")

    @app_commands.command(name="play", description="Stream audio from a URL")
    async def play(self, interaction: discord.Interaction, url: str) -> None:
        if interaction.guild is None or interaction.guild.voice_client is None:
            await interaction.response.send_message("Use /join first.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        voice_client = interaction.guild.voice_client

        ydl_opts = {"format": "bestaudio/best", "noplaylist": True, "quiet": True}

        def extract() -> tuple[str, str]:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get("url", ""), info.get("title", "Unknown")

        stream_url, title = await asyncio.to_thread(extract)
        if not stream_url:
            await interaction.followup.send(embed=EmbedFactory.error("Playback Error", "Unable to read stream URL."))
            return

        source = discord.FFmpegPCMAudio(stream_url, options="-vn")
        if voice_client.is_playing():
            voice_client.stop()
        voice_client.play(source)

        await interaction.followup.send(embed=EmbedFactory.success("Now Playing", title))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))

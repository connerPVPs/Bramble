from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.music_player import GuildMusicPlayer, MusicPlayerError


class MusicCog(commands.Cog):
    """Slash-command based music controls."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.players: dict[int, GuildMusicPlayer] = {}

    def get_player(self, interaction: discord.Interaction) -> GuildMusicPlayer:
        guild_id = interaction.guild_id
        if guild_id is None:
            raise MusicPlayerError("This command can only be used inside a server.")

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            raise MusicPlayerError("Use this command from a text channel.")

        if guild_id not in self.players:
            self.players[guild_id] = GuildMusicPlayer(self.bot, interaction.guild, channel)
        return self.players[guild_id]

    @app_commands.command(name="music", description="Play music by name or URL (YouTube/Spotify).")
    @app_commands.describe(name_or_link="YouTube/Spotify URL or search text")
    async def music(self, interaction: discord.Interaction, name_or_link: str) -> None:
        await interaction.response.defer(thinking=True)

        try:
            player = self.get_player(interaction)
        except MusicPlayerError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        allowed, msg = player.check_user_voice_channel(interaction)
        if not allowed:
            await interaction.followup.send(msg, ephemeral=True)
            return

        user_voice = interaction.user.voice.channel

        try:
            await player.ensure_connected(user_voice)
            track = await player.add_query(name_or_link, interaction.user.id)
        except MusicPlayerError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        except Exception as exc:
            await interaction.followup.send(f"❌ Unexpected playback error: `{exc}`", ephemeral=True)
            return

        queue_len = len(player.queue)
        await interaction.followup.send(
            f"✅ Added **{track.title}** to queue. Position: `{queue_len if queue_len else 1}`"
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))

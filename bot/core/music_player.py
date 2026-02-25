from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import discord
import yaml
from discord import app_commands

try:
    import yt_dlp
except Exception:  # pragma: no cover - optional dependency at runtime
    yt_dlp = None

LOGGER = logging.getLogger(__name__)

DEFAULT_VOLUME = 0.5
BLUE = 0x3498DB

YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "extract_flat": False,
    "skip_download": True,
}

FFMPEG_BEFORE_OPTS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"


@dataclass
class Track:
    title: str
    url: str
    source_url: str
    requester_id: int
    duration: int | None = None
    thumbnail: str | None = None


class MusicPlayerError(Exception):
    pass


class MusicPlayerControls(discord.ui.View):
    def __init__(self, player: "GuildMusicPlayer") -> None:
        super().__init__(timeout=None)
        self.player = player

    @discord.ui.button(label="⏮ Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ok, msg = await self.player.play_previous()
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="⏯ Pause/Resume", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ok, msg = await self.player.toggle_pause()
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="⏭ Next", style=discord.ButtonStyle.secondary)
    async def next_track(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ok, msg = await self.player.skip()
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="🎚 Bass/EQ", style=discord.ButtonStyle.secondary)
    async def bass_eq(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        enabled = self.player.toggle_bass_boost()
        state = "enabled" if enabled else "disabled"
        await interaction.response.send_message(f"Bass boost {state}. Applies on next track.", ephemeral=True)

    @discord.ui.button(label="🔁 Autoplay", style=discord.ButtonStyle.success)
    async def autoplay(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        enabled = self.player.toggle_autoplay()
        state = "enabled" if enabled else "disabled"
        await interaction.response.send_message(f"Autoplay {state}.", ephemeral=True)

    @discord.ui.select(
        placeholder="Volume",
        options=[
            discord.SelectOption(label="25%", value="0.25"),
            discord.SelectOption(label="50%", value="0.5"),
            discord.SelectOption(label="75%", value="0.75"),
            discord.SelectOption(label="100%", value="1.0"),
        ],
    )
    async def volume_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        volume = float(select.values[0])
        self.player.set_volume(volume)
        await interaction.response.send_message(f"Volume set to {int(volume * 100)}%.", ephemeral=True)


class GuildMusicPlayer:
    def __init__(self, bot: discord.Client, guild: discord.Guild, text_channel: discord.TextChannel) -> None:
        self.bot = bot
        self.guild = guild
        self.text_channel = text_channel
        self.voice_client: discord.VoiceClient | None = None
        self.queue: deque[Track] = deque()
        self.history: deque[Track] = deque(maxlen=25)
        self.current: Track | None = None
        self.volume: float = DEFAULT_VOLUME
        self.bass_boost_enabled = False
        self.autoplay_enabled = False
        self.allowed_voice_channel_id = _load_music_config().get("voice_channel_id")
        self._lock = asyncio.Lock()

    async def ensure_connected(self, voice_channel: discord.VoiceChannel) -> None:
        try:
            if self.voice_client and self.voice_client.is_connected():
                if self.voice_client.channel.id != voice_channel.id:
                    await self.voice_client.move_to(voice_channel)
                return
            self.voice_client = await voice_channel.connect(reconnect=True)
        except Exception as exc:  # pragma: no cover - network-dependent
            raise MusicPlayerError(f"Could not connect to voice channel: {exc}") from exc

    def check_user_voice_channel(self, interaction: discord.Interaction) -> tuple[bool, str | None]:
        user_voice = getattr(interaction.user, "voice", None)
        if not user_voice or not user_voice.channel:
            return False, "Join the configured voice channel first."

        if self.allowed_voice_channel_id and user_voice.channel.id != int(self.allowed_voice_channel_id):
            return False, f"Music is restricted to <#{self.allowed_voice_channel_id}>."
        return True, None

    async def add_query(self, query: str, requester_id: int) -> Track:
        async with self._lock:
            track = await self._resolve_query(query, requester_id)
            self.queue.append(track)
            if not self.current and self.voice_client and not self.voice_client.is_playing():
                await self._play_next_internal()
            return track

    async def play_previous(self) -> tuple[bool, str]:
        if not self.history:
            return False, "No previous track in history."

        previous_track = self.history.pop()
        if self.current:
            self.queue.appendleft(self.current)
        self.queue.appendleft(previous_track)
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
            return True, f"Returning to **{previous_track.title}**."

        await self._play_next_internal()
        return True, f"Playing **{previous_track.title}**."

    async def skip(self) -> tuple[bool, str]:
        if not self.voice_client or not (self.voice_client.is_playing() or self.voice_client.is_paused()):
            return False, "Nothing is currently playing."
        self.voice_client.stop()
        return True, "Skipped current track."

    async def toggle_pause(self) -> tuple[bool, str]:
        if not self.voice_client:
            return False, "Not connected to voice yet."
        if self.voice_client.is_paused():
            self.voice_client.resume()
            return True, "Resumed playback."
        if self.voice_client.is_playing():
            self.voice_client.pause()
            return True, "Paused playback."
        return False, "Nothing to pause or resume."

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(volume, 1.0))
        if self.voice_client and self.voice_client.source and isinstance(self.voice_client.source, discord.PCMVolumeTransformer):
            self.voice_client.source.volume = self.volume

    def toggle_bass_boost(self) -> bool:
        self.bass_boost_enabled = not self.bass_boost_enabled
        return self.bass_boost_enabled

    def toggle_autoplay(self) -> bool:
        self.autoplay_enabled = not self.autoplay_enabled
        return self.autoplay_enabled

    def now_playing_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Now Playing",
            description=f"**{self.current.title if self.current else 'Nothing'}**",
            color=BLUE,
        )
        if self.current:
            embed.add_field(name="Requested by", value=f"<@{self.current.requester_id}>", inline=True)
            if self.current.duration:
                embed.add_field(name="Duration", value=_format_seconds(self.current.duration), inline=True)
            if self.current.thumbnail:
                embed.set_thumbnail(url=self.current.thumbnail)
            embed.url = self.current.url
        embed.add_field(name="Queue", value=str(len(self.queue)), inline=True)
        embed.add_field(name="Volume", value=f"{int(self.volume * 100)}%", inline=True)
        embed.add_field(name="Autoplay", value="On" if self.autoplay_enabled else "Off", inline=True)
        return embed

    async def send_now_playing(self) -> None:
        if not self.current:
            return
        view = MusicPlayerControls(self)
        await self.text_channel.send(embed=self.now_playing_embed(), view=view)

    async def on_track_end(self) -> None:
        async with self._lock:
            if self.current:
                self.history.append(self.current)

            if self.queue:
                await self._play_next_internal()
                return

            if self.autoplay_enabled and self.current:
                try:
                    related = await self._get_related_track(self.current)
                    if related:
                        self.queue.append(related)
                        await self._play_next_internal()
                        return
                except Exception as exc:
                    LOGGER.exception("Autoplay resolution failed: %s", exc)

            self.current = None
            await self.text_channel.send("Queue ended.")

    async def _play_next_internal(self) -> None:
        if not self.queue:
            return
        self.current = self.queue.popleft()

        ffmpeg_opts = "-vn"
        if self.bass_boost_enabled:
            ffmpeg_opts += " -af bass=g=8"

        source = discord.FFmpegPCMAudio(
            self.current.source_url,
            before_options=FFMPEG_BEFORE_OPTS,
            options=ffmpeg_opts,
        )
        wrapped = discord.PCMVolumeTransformer(source, volume=self.volume)

        if not self.voice_client:
            await self.text_channel.send("Voice client is not connected.")
            return

        def after_play(error: Exception | None) -> None:
            if error:
                LOGGER.exception("Playback error: %s", error)
                coro = self.text_channel.send(f"Playback error occurred: `{error}`")
                asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
            fut = asyncio.run_coroutine_threadsafe(self.on_track_end(), self.bot.loop)
            fut.add_done_callback(lambda _: None)

        try:
            self.voice_client.play(wrapped, after=after_play)
            await self.send_now_playing()
        except Exception as exc:
            LOGGER.exception("Failed to play track: %s", exc)
            await self.text_channel.send(f"Failed to play track: `{exc}`")
            await self.on_track_end()

    async def _resolve_query(self, query: str, requester_id: int) -> Track:
        if yt_dlp is None:
            raise MusicPlayerError("yt-dlp is required for playback but is not installed.")

        if _is_spotify_url(query):
            query = await _spotify_to_search_query(query)
            if not query:
                raise MusicPlayerError(
                    "Could not resolve Spotify URL. Ensure spotipy is installed and credentials are configured."
                )

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: _extract_ytdl_data(query))

        if not data:
            raise MusicPlayerError("No playable results found.")

        entry = data["entries"][0] if data.get("entries") else data
        if not entry:
            raise MusicPlayerError("No playable result entry found.")

        title = entry.get("title") or "Unknown Title"
        webpage_url = entry.get("webpage_url") or entry.get("url")
        media_url = entry.get("url")
        duration = entry.get("duration")
        thumbnail = entry.get("thumbnail")

        if not media_url:
            raise MusicPlayerError("Resolved track has no stream URL.")

        return Track(
            title=title,
            url=webpage_url,
            source_url=media_url,
            requester_id=requester_id,
            duration=duration,
            thumbnail=thumbnail,
        )

    async def _get_related_track(self, current: Track) -> Track | None:
        query = f"ytsearch1:{current.title} similar audio"
        try:
            return await self._resolve_query(query, current.requester_id)
        except Exception:
            return None


def _extract_ytdl_data(query: str) -> dict[str, Any] | None:
    with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
        return ydl.extract_info(query, download=False)


def _load_music_config() -> dict[str, Any]:
    cfg_path = Path("config/music.yml")
    if not cfg_path.exists():
        return {}
    try:
        return yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        LOGGER.exception("Failed to load config/music.yml")
        return {}


def _is_spotify_url(text: str) -> bool:
    return "spotify.com/" in text or text.startswith("spotify:")


async def _spotify_to_search_query(url: str) -> str | None:
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
    except Exception:
        return _spotify_url_guess(url)

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return _spotify_url_guess(url)

    auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    match = re.search(r"spotify\.com/(track|album|playlist)/([A-Za-z0-9]+)", url)
    if not match:
        return _spotify_url_guess(url)

    item_type, item_id = match.group(1), match.group(2)

    if item_type == "track":
        track = sp.track(item_id)
        artist = track["artists"][0]["name"] if track.get("artists") else ""
        return f"ytsearch1:{track['name']} {artist}"

    if item_type == "album":
        album = sp.album(item_id)
        items = album.get("tracks", {}).get("items", [])
        if items:
            first = items[0]
            artist = first["artists"][0]["name"] if first.get("artists") else ""
            return f"ytsearch1:{first['name']} {artist}"

    if item_type == "playlist":
        playlist = sp.playlist_items(item_id, limit=1)
        items = playlist.get("items", [])
        if items:
            track = items[0].get("track", {})
            artist = track.get("artists", [{}])[0].get("name", "")
            return f"ytsearch1:{track.get('name', '')} {artist}"

    return _spotify_url_guess(url)


def _spotify_url_guess(url: str) -> str | None:
    parsed = urlparse(url)
    if "spotify" not in parsed.netloc and not url.startswith("spotify:"):
        return None
    token = parsed.path.split("/")[-1] if parsed.path else "spotify song"
    token = token.split("?")[0]
    if not token:
        return None
    return f"ytsearch1:{token.replace('-', ' ')}"


def _format_seconds(total: int) -> str:
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes}:{seconds:02}"


def register_music_command(tree: app_commands.CommandTree, callback) -> None:
    tree.command(name="music", description="Play music by search or link.")(callback)

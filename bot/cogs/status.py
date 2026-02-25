from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Final

import discord
from discord import app_commands
from discord.ext import commands
from mcstatus import JavaServer

STATUS_REFRESH_SECONDS: Final[int] = 60
DEFAULT_STATUS_LIFESPAN_SECONDS: Final[int] = 10 * 60
DEFAULT_TIMEOUT_SECONDS: Final[float] = 8.0


@dataclass(slots=True)
class ServerSnapshot:
    players_online: str
    server_version: str
    server_state: str
    status_line: str
    queried_at: datetime
    icon_bytes: bytes | None = None


class Status(commands.Cog):
    """Status-related slash commands for Minecraft servers."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="status",
        description="Check and continuously update the status of a Minecraft server.",
    )
    @app_commands.describe(server_ip="Server address, e.g. play.example.net or host:port")
    async def status(self, interaction: discord.Interaction, server_ip: str) -> None:
        """Send a status embed and keep updating the same message every 60 seconds."""

        await interaction.response.defer(thinking=True)

        lifespan_seconds = int(
            getattr(
                self.bot,
                "status_update_lifespan_seconds",
                DEFAULT_STATUS_LIFESPAN_SECONDS,
            )
        )

        initial_snapshot = await self._query_server(server_ip)
        embed, file = self._build_embed(server_ip=server_ip, snapshot=initial_snapshot)

        message = await interaction.followup.send(embed=embed, file=file, wait=True)
        self.bot.loop.create_task(
            self._update_status_message(
                message=message,
                server_ip=server_ip,
                lifespan_seconds=lifespan_seconds,
            )
        )

    async def _update_status_message(
        self,
        message: discord.Message,
        server_ip: str,
        lifespan_seconds: int,
    ) -> None:
        started_at = datetime.now(tz=UTC)

        while (datetime.now(tz=UTC) - started_at).total_seconds() < lifespan_seconds:
            await asyncio.sleep(STATUS_REFRESH_SECONDS)

            snapshot = await self._query_server(server_ip)
            embed, file = self._build_embed(server_ip=server_ip, snapshot=snapshot)

            try:
                await message.edit(embed=embed, attachments=[file] if file else [])
            except discord.NotFound:
                return
            except discord.HTTPException:
                # Stop updating if Discord refuses edits repeatedly.
                return

    async def _query_server(self, server_ip: str) -> ServerSnapshot:
        try:
            server = await JavaServer.async_lookup(server_ip)
            status = await asyncio.wait_for(server.async_status(), timeout=DEFAULT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return ServerSnapshot(
                players_online="N/A",
                server_version="Unknown",
                server_state="Offline",
                status_line="Timed out while checking the server.",
                queried_at=datetime.now(tz=UTC),
            )
        except OSError:
            return ServerSnapshot(
                players_online="N/A",
                server_version="Unknown",
                server_state="Offline",
                status_line="Unable to resolve or reach the server.",
                queried_at=datetime.now(tz=UTC),
            )
        except Exception:
            return ServerSnapshot(
                players_online="N/A",
                server_version="Unknown",
                server_state="Offline",
                status_line="Server appears offline or unavailable.",
                queried_at=datetime.now(tz=UTC),
            )

        icon_bytes = self._decode_favicon(getattr(status, "favicon", None))
        version_name = getattr(getattr(status, "version", None), "name", "Unknown")
        players = getattr(getattr(status, "players", None), "online", None)

        return ServerSnapshot(
            players_online=str(players) if players is not None else "Unknown",
            server_version=version_name,
            server_state="Online",
            status_line="Server is reachable and responding.",
            queried_at=datetime.now(tz=UTC),
            icon_bytes=icon_bytes,
        )

    def _build_embed(
        self,
        server_ip: str,
        snapshot: ServerSnapshot,
    ) -> tuple[discord.Embed, discord.File | None]:
        embed = discord.Embed(
            title="Bramble SMP | Status",
            color=discord.Color.blue(),
            timestamp=snapshot.queried_at,
        )

        embed.add_field(name="Players Online", value=snapshot.players_online, inline=True)
        embed.add_field(name="Server Version", value=snapshot.server_version, inline=True)
        embed.add_field(name="Server Status", value=snapshot.server_state, inline=True)
        embed.add_field(name="Details", value=snapshot.status_line, inline=False)
        embed.set_footer(text=f"Last updated • {snapshot.queried_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        embed.set_author(name=server_ip)

        file: discord.File | None = None
        if snapshot.icon_bytes:
            file = discord.File(BytesIO(snapshot.icon_bytes), filename="server_icon.png")
            embed.set_thumbnail(url="attachment://server_icon.png")

        return embed, file

    @staticmethod
    def _decode_favicon(favicon: str | None) -> bytes | None:
        if not favicon:
            return None

        try:
            _, encoded = favicon.split(",", maxsplit=1
            ) if "," in favicon else ("", favicon)
            return base64.b64decode(encoded)
        except (ValueError, binascii.Error):
            return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Status(bot))

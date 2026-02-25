from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import discord
from discord.ext import commands

from bot.core.config_loader import load_runtime_config
from bot.core.logger import setup_logger

logger = setup_logger()
config = load_runtime_config()


class BrambleBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(
            command_prefix=config.command_prefix,
            intents=intents,
            activity=discord.Game(name=config.activity_text),
        )

    async def setup_hook(self) -> None:
        logger.info("Startup: loading cogs...")
        cogs_path = Path(__file__).parent / "cogs"
        for cog_file in cogs_path.glob("*.py"):
            if cog_file.name.startswith("_"):
                continue
            extension = f"bot.cogs.{cog_file.stem}"
            try:
                await self.load_extension(extension)
                logger.info("Loaded extension %s", extension)
            except Exception:
                logger.exception("Failed to load extension %s", extension)

        try:
            if config.guild_id:
                guild = discord.Object(id=config.guild_id)
                synced = await self.tree.sync(guild=guild)
                logger.info("Slash commands synced to guild %s (%d commands)", config.guild_id, len(synced))
            else:
                synced = await self.tree.sync()
                logger.info("Slash commands globally synced (%d commands)", len(synced))
        except Exception:
            logger.exception("Command sync failed")

    async def on_ready(self) -> None:
        logger.info("Bot online as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")

    async def close(self) -> None:
        logger.info("Shutdown: closing Discord client...")
        await super().close()
        logger.info("Shutdown complete.")


async def run_bot() -> None:
    bot = BrambleBot()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.warning("Termination signal received. Stopping bot...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            logger.warning("Signal handlers not supported on this platform.")

    bot_task = asyncio.create_task(bot.start(config.token), name="discord-bot")

    done, pending = await asyncio.wait({bot_task, asyncio.create_task(stop_event.wait())}, return_when=asyncio.FIRST_COMPLETED)

    if stop_event.is_set() and not bot.is_closed():
        await bot.close()

    for task in pending:
        task.cancel()

    for task in done:
        if task is bot_task and task.exception() is not None:
            raise task.exception()


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except Exception:
        logger.exception("Fatal error while running the bot")
        raise

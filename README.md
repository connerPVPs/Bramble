# Bramble Discord Bot (Python)

A modular Discord bot skeleton using **discord.py app commands** (slash commands), with structured cogs and shared core utilities.

## Project Layout

```text
bot/
  main.py                 # Startup entrypoint
  cogs/
    welcome.py
    tickets.py
    status.py
    music.py
    voice_create.py
    levels.py
  core/
    config_loader.py
    embeds.py
    permissions.py
    logger.py
requirements.txt
.env.example
```

## Features Included

- Slash command syncing (guild-scoped when `GUILD_ID` is set, otherwise global).
- Robust startup/shutdown logging with rotating logs (`logs/bot.log`).
- Modular cog loading at startup (`bot/cogs/*.py`).
- Example features:
  - Welcome events
  - Ticket channels
  - Minecraft server status (`mcstatus`)
  - Basic music playback (`yt-dlp` + FFmpeg)
  - Auto-create temporary voice channels
  - Basic XP/level tracking

## Local Setup

1. Install Python 3.11+.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure env vars:
   ```bash
   cp .env.example .env
   ```
4. Edit `.env` and set `DISCORD_TOKEN`.
5. Run:
   ```bash
   python -m bot.main
   ```

## Pterodactyl Deployment

Use a standard Python egg/server.

### 1) Upload Files
Upload the repository contents to your server root (or clone the repo there).

### 2) Startup Command
Set the startup command to:

```bash
pip install -r requirements.txt && python -m bot.main
```

If your panel separates install/start, use install for pip and start command only:

```bash
python -m bot.main
```

### 3) Environment Variables
In Pterodactyl "Startup" / "Environment" section, set:

- `DISCORD_TOKEN` (required)
- `GUILD_ID` (optional for fast development sync)
- `LOG_LEVEL` (optional, default `INFO`)
- `ACTIVITY_TEXT` (optional)

### 4) Notes for Music Playback
Music playback requires FFmpeg available in the container image.

- Ensure `ffmpeg` exists in PATH.
- If not available, switch to an image with FFmpeg installed or install it in your custom image.

## Slash Commands
After startup, commands are synced automatically:

- If `GUILD_ID` is set: guild-only sync (fast updates).
- If `GUILD_ID` is not set: global sync (can take longer to appear).

## Logging
- Console logs + rotating file logs under `logs/bot.log`.
- Startup, cog loading, command sync, and shutdown are all logged.

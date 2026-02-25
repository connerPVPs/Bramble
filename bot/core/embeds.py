from __future__ import annotations

import discord


class EmbedFactory:
    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        return discord.Embed(title=title, description=description, color=discord.Color.green())

    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        return discord.Embed(title=title, description=description, color=discord.Color.blurple())

    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        return discord.Embed(title=title, description=description, color=discord.Color.orange())

    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        return discord.Embed(title=title, description=description, color=discord.Color.red())

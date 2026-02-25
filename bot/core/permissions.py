from __future__ import annotations

import discord
from discord import app_commands


def admin_only() -> app_commands.Check:
    """Return a slash-command check that allows administrators only."""

    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        return bool(member and member.guild_permissions.administrator)

    return app_commands.check(predicate)

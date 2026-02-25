from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import discord
import yaml
from discord import app_commands
from discord.ext import commands


CONFIG_PATH = Path("config/tickets.yml")


@dataclass(slots=True)
class TicketOption:
    key: str
    label: str
    description: str
    category_id: int
    emoji: str | None
    channel_name_prefix: str


@dataclass(slots=True)
class TicketSettings:
    staff_role_id: int
    log_channel_id: int
    panel_title: str
    panel_description: str
    panel_color: int
    rules_title: str
    rules_lines: list[str]
    rules_color: int
    options: list[TicketOption]


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9-]", "-", value.strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned[:30] or "player"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_ticket_settings() -> TicketSettings:
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}

    panel = data.get("panel", {})
    rules = data.get("ticket_rules", {})
    options: list[TicketOption] = []

    for option in data.get("options", []):
        options.append(
            TicketOption(
                key=str(option.get("key", "ticket")),
                label=str(option.get("label", "Ticket")),
                description=str(option.get("description", "Open a support ticket.")),
                category_id=_safe_int(option.get("category_id")),
                emoji=option.get("emoji"),
                channel_name_prefix=str(option.get("channel_name_prefix", option.get("key", "ticket"))),
            )
        )

    return TicketSettings(
        staff_role_id=_safe_int(data.get("staff_role_id")),
        log_channel_id=_safe_int(data.get("log_channel_id")),
        panel_title=str(panel.get("title", "Support Tickets")),
        panel_description=str(panel.get("description", "Choose a ticket type from the dropdown below.")),
        panel_color=_safe_int(panel.get("color", 0x3498DB)),
        rules_title=str(rules.get("title", "Ticket Rules")),
        rules_lines=[str(line) for line in rules.get("lines", ["Please explain your issue clearly."])],
        rules_color=_safe_int(rules.get("color", 0x3498DB)),
        options=options,
    )


def build_panel_embed(settings: TicketSettings) -> discord.Embed:
    return discord.Embed(
        title=settings.panel_title,
        description=settings.panel_description,
        color=settings.panel_color,
    )


def build_rules_embed(settings: TicketSettings) -> discord.Embed:
    lines = "\n".join(f"• {line}" for line in settings.rules_lines)
    return discord.Embed(
        title=settings.rules_title,
        description=lines,
        color=settings.rules_color,
    )


def encode_ticket_topic(owner_id: int, minecraft_username: str, ticket_type: str) -> str:
    return f"ticket_owner:{owner_id};mc:{minecraft_username};type:{ticket_type}"


def decode_ticket_topic(topic: str | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not topic:
        return parsed
    for piece in topic.split(";"):
        if ":" not in piece:
            continue
        key, value = piece.split(":", 1)
        parsed[key] = value
    return parsed


class CloseTicketView(discord.ui.View):
    def __init__(self, cog: "Tickets") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="tickets:close")
    async def close_ticket(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not isinstance(interaction.channel, discord.TextChannel) or interaction.guild is None:
            await interaction.response.send_message("This button can only be used inside a ticket channel.", ephemeral=True)
            return

        settings = load_ticket_settings()
        topic_data = decode_ticket_topic(interaction.channel.topic)
        owner_id = _safe_int(topic_data.get("ticket_owner"))

        is_owner = interaction.user.id == owner_id
        is_staff = bool(settings.staff_role_id and any(role.id == settings.staff_role_id for role in interaction.user.roles))
        can_manage = interaction.user.guild_permissions.manage_channels

        if not (is_owner or is_staff or can_manage):
            await interaction.response.send_message("You do not have permission to close this ticket.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        archive_result = await self.cog.archive_ticket(interaction.channel, closed_by=interaction.user)

        if archive_result:
            await interaction.followup.send("Ticket archived and channel deleted.", ephemeral=True)


class TicketModal(discord.ui.Modal, title="Open Ticket"):
    minecraft_username = discord.ui.TextInput(
        label="Minecraft Username",
        required=True,
        max_length=16,
        placeholder="Enter your in-game username",
    )

    def __init__(self, cog: "Tickets", option_key: str) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.option_key = option_key

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.create_ticket_from_modal(interaction, self.option_key, str(self.minecraft_username))


class TicketTypeSelect(discord.ui.Select):
    def __init__(self, cog: "Tickets", settings: TicketSettings) -> None:
        options = [
            discord.SelectOption(
                label=option.label,
                value=option.key,
                description=option.description[:100],
                emoji=option.emoji,
            )
            for option in settings.options
        ]
        super().__init__(
            placeholder="Choose a ticket type...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="tickets:type_select",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TicketModal(self.cog, self.values[0]))


class TicketPanelView(discord.ui.View):
    def __init__(self, cog: "Tickets") -> None:
        super().__init__(timeout=None)
        settings = load_ticket_settings()
        self.add_item(TicketTypeSelect(cog, settings))


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(CloseTicketView(self))

    def get_option(self, option_key: str) -> TicketOption | None:
        settings = load_ticket_settings()
        for option in settings.options:
            if option.key == option_key:
                return option
        return None

    @app_commands.command(name="setup_tickets", description="Post the ticket panel in a channel.")
    @app_commands.describe(channel="The channel where the ticket panel should be posted")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_tickets(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        settings = load_ticket_settings()
        if not settings.options:
            await interaction.response.send_message(
                "No ticket options are configured. Please edit config/tickets.yml first.", ephemeral=True
            )
            return

        await channel.send(embed=build_panel_embed(settings), view=TicketPanelView(self))
        await interaction.response.send_message(f"Ticket panel posted in {channel.mention}.", ephemeral=True)

    async def create_ticket_from_modal(
        self,
        interaction: discord.Interaction,
        option_key: str,
        minecraft_username: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Tickets can only be opened in a server.", ephemeral=True)
            return

        settings = load_ticket_settings()
        option = next((opt for opt in settings.options if opt.key == option_key), None)
        if option is None:
            await interaction.response.send_message("That ticket type is no longer configured.", ephemeral=True)
            return

        category = interaction.guild.get_channel(option.category_id)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                f"Configured category for **{option.label}** is invalid. Ask staff to update config/tickets.yml.",
                ephemeral=True,
            )
            return

        staff_role = interaction.guild.get_role(settings.staff_role_id)
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                attach_files=True,
            ),
        }

        if staff_role is not None:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
            )

        ticket_name = f"{option.channel_name_prefix}-{_slugify(interaction.user.display_name)}"

        channel = await interaction.guild.create_text_channel(
            name=ticket_name,
            category=category,
            reason=f"Ticket opened by {interaction.user} ({option.label})",
            overwrites=overwrites,
            topic=encode_ticket_topic(interaction.user.id, minecraft_username, option.key),
        )

        mention_bits = [interaction.user.mention]
        if staff_role is not None:
            mention_bits.append(staff_role.mention)

        rules_embed = build_rules_embed(settings)
        rules_embed.add_field(name="Ticket Type", value=option.label, inline=True)
        rules_embed.add_field(name="Minecraft Username", value=minecraft_username, inline=True)
        rules_embed.add_field(name="Notice", value="Please do **not ping staff** in this ticket.", inline=False)

        await channel.send(
            content=" ".join(mention_bits),
            embed=rules_embed,
            view=CloseTicketView(self),
        )

        await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)

    async def archive_ticket(self, channel: discord.TextChannel, closed_by: discord.Member | discord.User) -> bool:
        settings = load_ticket_settings()

        log_channel = channel.guild.get_channel(settings.log_channel_id)
        if not isinstance(log_channel, discord.TextChannel):
            await channel.send("Unable to archive: log channel is misconfigured.")
            return False

        transcript_lines: list[str] = []
        async for message in channel.history(limit=None, oldest_first=True):
            timestamp = message.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            line = f"[{timestamp}] {message.author} ({message.author.id}): {message.clean_content}"
            transcript_lines.append(line)

            if message.attachments:
                for attachment in message.attachments:
                    transcript_lines.append(f"    [Attachment] {attachment.url}")

            if message.embeds:
                transcript_lines.append(f"    [Embeds] {len(message.embeds)} embed(s)")

        if not transcript_lines:
            transcript_lines.append("[No messages were found in this ticket.]")

        transcript_data = "\n".join(transcript_lines).encode("utf-8")
        filename = f"{channel.name}-transcript.txt"
        file = discord.File(io.BytesIO(transcript_data), filename=filename)

        topic = decode_ticket_topic(channel.topic)
        owner_id = topic.get("ticket_owner", "Unknown")
        ticket_type = topic.get("type", "Unknown")

        embed = discord.Embed(
            title="Ticket Closed",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Channel", value=channel.name, inline=True)
        embed.add_field(name="Closed By", value=f"{closed_by} ({closed_by.id})", inline=True)
        embed.add_field(name="Owner ID", value=str(owner_id), inline=True)
        embed.add_field(name="Type", value=ticket_type, inline=True)

        await log_channel.send(embed=embed, file=file)
        await channel.delete(reason=f"Ticket archived by {closed_by}")
        return True


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))

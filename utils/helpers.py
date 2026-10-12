"""
Utility helpers for Ava Discord Bot.
"""
import discord
from datetime import timedelta, datetime, timezone
from typing import Optional, List, Tuple
import re


def format_timedelta(td: timedelta) -> str:
    """Format a timedelta into a human-readable string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}m {seconds}s" if seconds else f"{minutes}m"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    else:
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        return f"{days}d {hours}h" if hours else f"{days}d"


def parse_time_string(time_str: str) -> Optional[timedelta]:
    """Parse a time string like '1h30m', '45m', '2h' into a timedelta."""
    pattern = r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
    match = re.fullmatch(pattern, time_str.lower().strip())
    if not match:
        return None
    days, hours, minutes, seconds = match.groups()
    return timedelta(
        days=int(days) if days else 0,
        hours=int(hours) if hours else 0,
        minutes=int(minutes) if minutes else 0,
        seconds=int(seconds) if seconds else 0
    )


AVA_COLOR = 0xFF6EC7  # Ava's signature pink — universal default for all commands


def create_embed(
    title: str = None,
    description: str = None,
    color: int = 0x5865F2,
    fields: List[Tuple[str, str, bool]] = None,
    footer: str = None,
    thumbnail: str = None,
    image: str = None,
    author: Tuple[str, str] = None,  # (name, icon_url)
) -> discord.Embed:
    """Create a standardized embed."""
    embed = discord.Embed(title=title, description=description, color=color)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    if footer:
        embed.set_footer(text=footer)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    if author:
        embed.set_author(name=author[0], icon_url=author[1])
    return embed


def ava_embed(
    title: str = None,
    description: str = None,
    color: int = AVA_COLOR,
    fields: List[Tuple[str, str, bool]] = None,
    footer_cmd: str = None,
    thumbnail: str = None,
    image: str = None,
    use_timestamp: bool = True,
) -> discord.Embed:
    """Create a standardized Ava-branded embed with footer + timestamp.

    Every command output should use this for consistent look:
    - Ava pink color by default
    - Footer showing which command was used
    - UTC timestamp for traceability
    """
    embed = discord.Embed(title=title, description=description, color=color)
    if use_timestamp:
        embed.timestamp = datetime.now(timezone.utc)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=str(value), inline=inline)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    if footer_cmd:
        embed.set_footer(text=f"⌨️ /{footer_cmd}")
    return embed


def truncate(text: str, max_length: int = 1024, suffix: str = "...") -> str:
    """Truncate text to max length."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def is_media_message(message: discord.Message) -> bool:
    """Check if a message contains media (images, videos, links to media sites)."""
    # Check attachments
    for attachment in message.attachments:
        if attachment.content_type and (
            attachment.content_type.startswith("image/") or
            attachment.content_type.startswith("video/")
        ):
            return True

    # Check embeds for media
    for embed in message.embeds:
        if embed.type in ("image", "video", "gifv"):
            return True
        if embed.url and any(domain in embed.url for domain in [
            "youtube.com", "youtu.be", "twitch.tv", "clips.twitch.tv",
            "medal.tv", "streamable.com", "x.com", "twitter.com",
            "tiktok.com", "reddit.com"
        ]):
            return True

    # Check message content for media URLs
    media_domains = [
        "youtube.com", "youtu.be", "twitch.tv", "clips.twitch.tv",
        "medal.tv", "streamable.com", "x.com", "twitter.com",
        "tiktok.com", "reddit.com", "imgur.com", "gyazo.com",
        "cdn.discordapp.com", "media.discordapp.net"
    ]
    content_lower = message.content.lower()
    for domain in media_domains:
        if domain in content_lower:
            return True

    return False


async def safe_send(
    destination: discord.abc.Messageable,
    content: str = None,
    embed: discord.Embed = None,
    view: discord.ui.View = None,
    ephemeral: bool = False,
    delete_after: float = None,
    silent: bool = False
) -> Optional[discord.Message]:
    """Safely send a message, handling exceptions."""
    try:
        if hasattr(destination, 'send'):
            return await destination.send(
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral,
                delete_after=delete_after,
                silent=silent  # Suppress push notifications
            )
        elif hasattr(destination, 'respond'):
            return await destination.response.send_message(
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral,
                silent=silent  # Suppress push notifications
            )
    except discord.errors.InteractionResponded:
        # Interaction already responded — fall back to followup
        try:
            if hasattr(destination, 'followup'):
                return await destination.followup.send(
                    content=content,
                    embed=embed,
                    view=view,
                    ephemeral=ephemeral,
                    silent=silent,
                )
        except discord.HTTPException as e:
            print(f"Failed to send followup: {e}")
    except discord.HTTPException as e:
        print(f"Failed to send message: {e}")
    return None


async def safe_edit(
    message: discord.Message,
    content: str = None,
    embed: discord.Embed = None,
    view: discord.ui.View = None
) -> bool:
    """Safely edit a message, handling exceptions."""
    try:
        await message.edit(content=content, embed=embed, view=view)
        return True
    except discord.HTTPException as e:
        print(f"Failed to edit message: {e}")
        return False


async def safe_delete(message: discord.Message) -> bool:
    """Safely delete a message, handling exceptions."""
    try:
        await message.delete()
        return True
    except discord.HTTPException as e:
        print(f"Failed to delete message: {e}")
        return False


def get_member_display_name(member: discord.Member) -> str:
    """Get a member's display name (nickname or username)."""
    return member.display_name


def format_user_mention(user_id: int) -> str:
    """Format a user mention string."""
    return f"<@{user_id}>"


def format_role_mention(role_id: int) -> str:
    """Format a role mention string."""
    return f"<@&{role_id}>"


def format_channel_mention(channel_id: int) -> str:
    """Format a channel mention string."""
    return f"<#{channel_id}>"


class PaginationView(discord.ui.View):
    """Generic pagination view for embeds."""

    def __init__(self, embeds: List[discord.Embed], timeout: float = 180):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.current_page = 0
        self._update_buttons()

    def _update_buttons(self):
        self.first_page.disabled = self.current_page == 0
        self.prev_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page == len(self.embeds) - 1
        self.last_page.disabled = self.current_page == len(self.embeds) - 1
        self.page_indicator.label = f"Page {self.current_page + 1}/{len(self.embeds)}"

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, row=0)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass  # Just for display

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.embeds) - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.embeds) - 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)


def chunk_list(lst: list, chunk_size: int) -> List[list]:
    """Split a list into chunks of specified size."""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def create_progress_bar(current: int, maximum: int, length: int = 10, filled: str = "█", empty: str = "░") -> str:
    """Create a text-based progress bar."""
    if maximum <= 0:
        return empty * length
    filled_length = int(length * current / maximum)
    return filled * filled_length + empty * (length - filled_length)
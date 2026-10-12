"""
Channel Housekeeping & Media Showcase Cog.
Handles auto-threads for media, starboard/skullboard, and message cleanup.
"""
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from typing import Optional, Set

from config.settings import settings
from database.models import Database
from utils.helpers import ava_embed, safe_send, is_media_message


class HousekeepingCog(commands.Cog):
    """Channel housekeeping and media management."""

    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.processing_messages: Set[int] = set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle incoming messages for auto-threading and media."""
        if message.author.bot:
            return

        # Auto-thread for media in clips/media channels
        if message.channel.id in (settings.channel_clips, settings.channel_media):
            if is_media_message(message) and not message.thread:
                await self._create_auto_thread(message)

        # Check for ghost pings (mentions in deleted messages)
        if message.mentions or message.role_mentions:
            # Store for ghost ping detection
            pass

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Detect ghost pings when messages are deleted."""
        if not message.mentions and not message.role_mentions:
            return

        # Check if message was from a bot or author
        if message.author.bot:
            return

        # Log ghost ping
        if settings.channel_mod_logs:
            mod_channel = self.bot.get_channel(settings.channel_mod_logs)
            if mod_channel:
                embed = ava_embed(
                    title="⚠️ Ghost Ping Detected",
                    footer_cmd="housekeeping",
                    fields=[
                        ("Message Author", message.author.mention, True),
                        ("Channel", message.channel.mention, True),
                    ],
                )

                # Include original message content
                content = message.content[:1000] if message.content else "No content"
                if message.mentions:
                    content += f"\n\nMentions: {', '.join(m.mention for m in message.mentions[:5])}"
                if message.role_mentions:
                    content += f"\n\nRole Mentions: {', '.join(r.mention for r in message.role_mentions[:5])}"

                embed.add_field(name="Original Message", value=content, inline=False)

                try:
                    await mod_channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Handle starboard/skullboard reactions."""
        if payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        # Check if in clips/media channel (skip starboard logic)
        if payload.channel_id in (settings.channel_clips, settings.channel_media):
            return

        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        # Check reaction emoji
        emoji_str = str(payload.emoji)

        # Check starboard
        if emoji_str == settings.starboard_emoji:
            await self._check_starboard_entry(message, emoji_str, settings.starboard_threshold)
        elif emoji_str == settings.skullboard_emoji:
            await self._check_starboard_entry(message, emoji_str, settings.skullboard_threshold)

    async def _create_auto_thread(self, message: discord.Message):
        """Create an auto-thread for a media message."""
        try:
            # Create public thread
            thread = await message.create_thread(
                name=f"Discussion: {message.author.display_name}'s post",
                auto_archive_duration=1440  # 24 hours
            )
            # Send welcome message
            await thread.send(
                f"💡 Auto-thread created for {message.author.mention}'s media post.",
                delete_after=30
            )
        except discord.HTTPException as e:
            print(f"Error creating thread: {e}")

    async def _check_starboard_entry(self, message: discord.Message, emoji: str, threshold: int):
        """Check if a message should be added to starboard/skullboard."""
        # Get reaction count
        reaction_count = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == emoji:
                reaction_count = reaction.count
                break

        if reaction_count < threshold:
            return

        # Check if already in starboard
        existing = await self.db.get_starboard_entry(message.id, emoji)
        if existing:
            # Update count if changed
            if reaction_count != existing["reaction_count"]:
                await self.db.update_starboard_count(message.id, emoji, reaction_count)
            return

        # Check if message is old
        if message.created_at < datetime.now(timezone.utc) - timedelta(days=7):
            return

        # Send to starboard channel
        if emoji == settings.starboard_emoji:
            target_channel_id = settings.channel_hall_of_fame
        elif emoji == settings.skullboard_emoji:
            target_channel_id = settings.channel_hall_of_fame  # Could be separate
        else:
            return

        target_channel = self.bot.get_channel(target_channel_id)
        if not target_channel:
            return

        # Build embed
        embed = ava_embed(
            title="⭐ Starboard" if emoji == settings.starboard_emoji else "💀 Skullboard",
            description=message.content[:2000] if message.content else "No content",
            color=0xFFD700 if emoji == settings.starboard_emoji else 0xFF6EC7,
            footer_cmd="starboard",
            fields=[
                ("Original Author", message.author.mention, True),
                ("Original Channel", message.channel.mention, True),
                ("Reactions", f"{emoji} {reaction_count}", True),
            ],
        )

        # Add media if present
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        for embed_msg in message.embeds:
            if embed_msg.image:
                embed.set_image(url=embed_msg.image.url)
                break
            if embed_msg.thumbnail:
                embed.set_thumbnail(url=embed_msg.thumbnail.url)

        # Add link to original message
        embed.add_field(name="Jump to Message", value=f"[Jump!]({message.jump_url})", inline=False)

        try:
            star_message = await target_channel.send(embed=embed)
            await self.db.add_starboard_entry(
                guild_id=message.guild.id,
                original_message_id=message.id,
                original_channel_id=message.channel.id,
                starboard_message_id=star_message.id,
                emoji=emoji,
                reaction_count=reaction_count
            )
        except discord.HTTPException as e:
            print(f"Error posting to starboard: {e}")

    @app_commands.command(name="clean", description="Clean up messages (mod only)")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    async def clean(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        """Bulk delete messages."""
        await interaction.response.defer(ephemeral=True)

        channel = interaction.channel
        deleted = await channel.purge(limit=amount, reason=f"Cleaned by {interaction.user}")

        embed = ava_embed(
            title="✅ Cleanup Complete",
            fields=[("Deleted Messages", str(len(deleted)), True)],
            footer_cmd="clean",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="setup-bot-channel", description="Lock a channel so only the bot can post (admin only)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel="The channel to lock down for bot-only use")
    async def setup_bot_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Lock a channel so only the bot can send messages."""
        await interaction.response.defer(ephemeral=True)

        bot_member = interaction.guild.me

        # Deny @everyone from sending messages
        overwrites_everyone = discord.PermissionOverwrite(
            send_messages=False,
            add_reactions=False,
            send_messages_in_threads=False,
        )
        # Allow bot to send messages
        overwrites_bot = discord.PermissionOverwrite(
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            read_messages=True,
        )

        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites_everyone)
        await channel.set_permissions(bot_member, overwrite=overwrites_bot)

        # Send a silent confirmation in the channel
        embed = ava_embed(
            title="🤖 Bot Commands Channel",
            description="This channel is now bot-only. Commands and responses will appear here silently.",
            footer_cmd="setup-bot-channel",
        )
        await channel.send(embed=embed, silent=True)

        confirm = ava_embed(title="🤖 Bot Channel",
                            description=f"{channel.mention} is now bot-only! ✅",
                            footer_cmd="setup-bot-channel")
        await interaction.followup.send(embed=confirm, ephemeral=True)

    async def cog_unload(self):
        """Clean up on cog unload."""
        pass


async def setup(bot: commands.Bot) -> None:
    """Setup the cog."""
    db = bot.db
    await bot.add_cog(HousekeepingCog(bot, db))
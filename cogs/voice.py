"""
Dynamic Voice Rooms & Control Panel Cog.
Handles join-to-create voice channels, auto-AFK detection, stream roles, and TTS greetings.
"""
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Set
import asyncio
import os
import re
import shutil
import tempfile

from config.settings import settings

# Script-style Unicode mapping for temp room names (style: ꧁༺𝓣𝓮𝔁𝓪𝓼༻꧂)
_FANCY_MAP = {
    'a': '𝓪', 'b': '𝓫', 'c': '𝓬', 'd': '𝓭', 'e': '𝓮', 'f': '𝓯',
    'g': '𝓰', 'h': '𝓱', 'i': '𝓲', 'j': '𝓳', 'k': '𝓴', 'l': '𝓵',
    'm': '𝓶', 'n': '𝓷', 'o': '𝓸', 'p': '𝓹', 'q': '𝓺', 'r': '𝓻',
    's': '𝓼', 't': '𝓽', 'u': '𝓾', 'v': '𝓿', 'w': '𝔀', 'x': '𝔁',
    'y': '𝔂', 'z': '𝔃',
    'A': '𝓐', 'B': '𝓑', 'C': '𝓒', 'D': '𝓓', 'E': '𝓔', 'F': '𝓕',
    'G': '𝓖', 'H': '𝓗', 'I': '𝓘', 'J': '𝓙', 'K': '𝓚', 'L': '𝓛',
    'M': '𝓜', 'N': '𝓝', 'O': '𝓞', 'P': '𝓟', 'Q': '𝓠', 'R': '𝓡',
    'S': '𝓢', 'T': '𝓣', 'U': '𝓤', 'V': '𝓥', 'W': '𝓦', 'X': '𝓧',
    'Y': '𝓨', 'Z': '𝓩',
    '0': '0', '1': '1', '2': '2', '3': '3', '4': '4',
    '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
    "'": '', '-': '-', '_': '_', ' ': ' ',
}

def _fancy_name(name: str) -> str:
    """Convert a name to the script-style Unicode, e.g. Texas → ꧁༺𝓣𝓮𝔁𝓪𝓼༻꧂."""
    converted = ''.join(_FANCY_MAP.get(ch, ch) for ch in name)
    return f"꧁༺{converted}༻꧂"
from database.models import Database
from utils.helpers import ava_embed, safe_send
from utils.personality import detect_language


class VoiceControlPanelView(discord.ui.View):
    """Interactive control panel for voice room owner."""

    def __init__(self, channel_id: int, db: Database, bot: commands.Bot):
        super().__init__(timeout=None)  # Persistent view
        self.channel_id = channel_id
        self.db = db
        self.bot = bot

    async def _is_owner(self, interaction: discord.Interaction) -> bool:
        """Check if the interacting user is the room owner."""
        owner_id = await self.db.get_voice_channel_owner(self.channel_id)
        if owner_id != interaction.user.id:
            embed = ava_embed(title="⚠️ Not Owner", description="Only the room owner can do this!",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⚙️ Customize", style=discord.ButtonStyle.blurple, row=0)
    async def customize_room(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to customize room name, limit, and bitrate."""
        await interaction.response.send_modal(RoomCustomizeModal(self.channel_id, self.db))

    @discord.ui.button(label="🔒 Lock", style=discord.ButtonStyle.blurple, row=0)
    async def toggle_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle voice channel lock."""
        await interaction.response.defer(ephemeral=True)

        if not await self._is_owner(interaction):
            return

        guild = interaction.guild
        channel = guild.get_channel(self.channel_id)
        if not channel:
            embed = ava_embed(title="🔒 Lock Room", description="Voice channel not found.",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        is_locked = await self.db.get_voice_channel_lock(self.channel_id)
        new_locked_state = not is_locked

        # Get @everyone role
        everyone_role = guild.default_role

        # Update permissions
        if new_locked_state:
            # Lock: deny connect for @everyone
            await channel.set_permissions(
                everyone_role,
                connect=False,
                reason="Voice room locked"
            )
            button.label = "🔓 Unlock"
            embed = ava_embed(title="🔒 Room Locked", description="Room is now **locked**!",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            # Unlock: allow connect for @everyone
            await channel.set_permissions(
                everyone_role,
                connect=True,
                reason="Voice room unlocked"
            )
            button.label = "🔒 Lock"
            embed = ava_embed(title="🔓 Room Unlocked", description="Room is now **unlocked**!",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)

        await self.db.set_voice_channel_lock(self.channel_id, new_locked_state)

    @discord.ui.button(label="👥 Invite", style=discord.ButtonStyle.success, row=0)
    async def invite_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to invite a user to the room."""
        await interaction.response.send_modal(InviteUserModal(self.channel_id))

    @discord.ui.button(label="🗑️ Close Room", style=discord.ButtonStyle.danger, row=1)
    async def close_room(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Delete the voice room and its control panel (owner only)."""
        await interaction.response.defer(ephemeral=True)

        if not await self._is_owner(interaction):
            return

        guild = interaction.guild
        channel = guild.get_channel(self.channel_id)
        text_channel = interaction.channel  # The control panel text channel

        # Delete the voice channel
        voice_id = channel.id if channel else None
        if channel:
            try:
                await channel.delete(reason="Room owner closed the room")
            except discord.HTTPException:
                pass

        # Delete the control panel text channel (different from voice channel)
        if text_channel and text_channel.id != voice_id:
            try:
                await text_channel.delete(reason="Room closed")
            except discord.HTTPException:
                pass

        # Unregister from database
        await self.db.unregister_voice_channel(self.channel_id)
        embed = ava_embed(title="🗑️ Room Closed", description="Room closed and deleted!",
                          footer_cmd="voice")
        await interaction.followup.send(embed=embed, ephemeral=True)


class RoomCustomizeModal(discord.ui.Modal, title="Customize Your Room"):
    """Modal for setting room name, user limit, and bitrate."""

    def __init__(self, channel_id: int, db: Database):
        super().__init__()
        self.channel_id = channel_id
        self.db = db

    room_name = discord.ui.TextInput(
        label="Room Name",
        placeholder="Enter a name for your room...",
        max_length=50,
        required=True
    )

    user_limit = discord.ui.TextInput(
        label="User Limit (0-99, 0 = unlimited)",
        placeholder="0",
        min_length=1,
        max_length=2,
        required=True
    )

    bitrate = discord.ui.TextInput(
        label="Bitrate (64/96/128/256/384 kbps)",
        placeholder="128",
        min_length=2,
        max_length=3,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Check ownership
        owner_id = await self.db.get_voice_channel_owner(self.channel_id)
        if owner_id != interaction.user.id:
            embed = ava_embed(title="⚠️ Not Owner", description="Only the room owner can customize!",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            embed = ava_embed(title="⚙️ Customize", description="Voice channel not found.",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        errors = []
        limit_val = 0
        bitrate_val = 128

        # Validate and apply user limit
        try:
            limit_val = int(self.user_limit.value)
            if not (0 <= limit_val <= 99):
                errors.append("User limit must be 0-99")
            else:
                await channel.edit(user_limit=limit_val if limit_val > 0 else None)
                await self.db.set_voice_channel_limit(self.channel_id, limit_val)
        except ValueError:
            errors.append("Invalid user limit number")

        # Validate and apply bitrate
        valid_bitrates = {64, 96, 128, 256, 384}
        try:
            bitrate_val = int(self.bitrate.value)
            if bitrate_val not in valid_bitrates:
                errors.append(f"Bitrate must be one of: {', '.join(map(str, sorted(valid_bitrates)))}")
            else:
                await channel.edit(bitrate=bitrate_val * 1000)  # Convert to bps
        except ValueError:
            errors.append("Invalid bitrate number")

        # Apply room name
        name = self.room_name.value.strip()
        if name:
            await channel.edit(name=name)

        if errors:
            embed = ava_embed(title="⚠️ Customize",
                              description="Some settings had issues:\n" + "\n".join(f"• {e}" for e in errors),
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            limit_display = "unlimited" if limit_val == 0 else f"{limit_val} users"
            embed = ava_embed(title="✅ Room Updated", footer_cmd="voice",
                              fields=[
                                  ("Name", name, True),
                                  ("Limit", limit_display, True),
                                  ("Bitrate", f"{bitrate_val} kbps", True),
                              ])
            await interaction.followup.send(embed=embed, ephemeral=True)


class InviteUserModal(discord.ui.Modal, title="Invite Someone"):
    """Modal to invite a user to the voice room."""

    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

    user_input = discord.ui.TextInput(
        label="Username, display name, or @mention",
        placeholder="e.g. @Texas or texas",
        max_length=100,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            embed = ava_embed(title="👥 Invite", description="Voice channel not found.",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        raw = self.user_input.value.strip()
        target_member = None

        # Try parsing as mention (<@123456>)
        mention_match = re.match(r"<@!?(\d+)>", raw)
        if mention_match:
            user_id = int(mention_match.group(1))
            target_member = interaction.guild.get_member(user_id)

        # Try by user ID directly
        if target_member is None and raw.isdigit():
            target_member = interaction.guild.get_member(int(raw))

        # Try by name / display name (case-insensitive)
        if target_member is None:
            raw_lower = raw.lower().lstrip("@")
            for member in interaction.guild.members:
                if member.bot:
                    continue
                if (member.name.lower() == raw_lower or
                    member.display_name.lower() == raw_lower or
                    raw_lower in member.display_name.lower()):
                    target_member = member
                    break

        if target_member is None:
            embed = ava_embed(title="👥 Invite", description=f"Could not find user **{raw}**.",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        if target_member.bot:
            embed = ava_embed(title="👥 Invite", description="Can't invite bots.",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Check if already in a voice channel in this guild
        if target_member.voice and target_member.voice.channel:
            embed = ava_embed(title="👥 Invite",
                              description=f"{target_member.display_name} is already in a voice channel.",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Grant connect permission and move them in
        try:
            await channel.set_permissions(
                target_member,
                connect=True,
                view_channel=True,
                reason=f"Invited by {interaction.user.display_name}"
            )
            await target_member.move_to(channel, reason="Invited to room")
            embed = ava_embed(title="✅ Invited",
                              description=f"Invited **{target_member.display_name}** to your room!",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.HTTPException as e:
            embed = ava_embed(title="⚠️ Invite Failed", description=f"Could not invite: {e.text}",
                              footer_cmd="voice")
            await interaction.followup.send(embed=embed, ephemeral=True)


class VoiceLimitModal(discord.ui.Modal, title="Set User Limit"):
    """Modal for setting voice channel user limit."""

    def __init__(self, channel_id: int, db: Database):
        super().__init__()
        self.channel_id = channel_id
        self.db = db

    limit_input = discord.ui.TextInput(
        label="User Limit (2-50, or 0 for unlimited)",
        placeholder="Enter number",
        min_length=1,
        max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.limit_input.value)
            if not (0 <= limit <= 50):
                embed = ava_embed(title="⚠️ Set Limit", description="Limit must be between 0-50!",
                                  footer_cmd="voice")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            channel = interaction.guild.get_channel(self.channel_id)
            if channel:
                await channel.edit(user_limit=limit)
                await self.db.set_voice_channel_limit(self.channel_id, limit)
                limit_text = "unlimited" if limit == 0 else f"{limit} users"
                embed = ava_embed(title="✅ Limit Set",
                                  description=f"User limit set to **{limit_text}**!",
                                  footer_cmd="voice")
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError:
            embed = ava_embed(title="⚠️ Set Limit", description="Please enter a valid number!",
                              footer_cmd="voice")
            await interaction.response.send_message(embed=embed, ephemeral=True)


class VoiceCog(commands.Cog):
    """Dynamic voice rooms and management."""

    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.afk_check.start()
        self.recent_activity: Dict[int, datetime] = {}  # Track member activity
        self._lobby_locks: Set[int] = set()  # Debounce: members currently being processed
        self._greeting_locks: Set[int] = set()  # Debounce: channels being greeted
        self._greeted_members: Set[int] = set()  # Members who already got their welcome — don't repeat

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Handle voice state changes."""
        guild = member.guild

        # Join-to-create: user joined lobby creation channel
        if after.channel and after.channel.id == settings.channel_lobby_create:
            # Debounce: Discord fires multiple voice-state events on a single join
            if member.id in self._lobby_locks:
                return
            self._lobby_locks.add(member.id)
            print(f"[Voice] {member.display_name} joined lobby create (ch={after.channel.id}), creating lobby...")
            try:
                await self._create_lobby_channel(member, guild)
            finally:
                self._lobby_locks.discard(member.id)
            return

        # TTS greeting: only the person who OPENED (created) a temp lobby gets greeted.
        # Other people joining the room or joining regular VCs get nothing.
        # Use `before.channel != after.channel` so the auto-move after creation counts.
        # Only greet ONCE per member — if they leave and rejoin (or make a second room),
        # Ava doesn't welcome them again.
        if (after.channel and before.channel != after.channel and not member.bot
                and after.channel.id != settings.channel_lobby_create
                and after.channel.id != settings.channel_afk):
            owner_id = await self.db.get_voice_channel_owner(after.channel.id)
            if owner_id and member.id == owner_id and member.id not in self._greeted_members:
                self._greeted_members.add(member.id)
                print(f"[Voice] {member.display_name} opened their lobby {after.channel.id}, triggering TTS greeting...", flush=True)
                # Fire-and-forget TTS greeting
                asyncio.create_task(self._greet_lobby_join(member, after.channel, owner_id))

        # Check if user left a dynamic voice channel
        if before.channel and before.channel.id != settings.channel_lobby_create:
            owner_id = await self.db.get_voice_channel_owner(before.channel.id)
            if owner_id:  # This is a dynamic voice channel
                # Check if channel is empty
                if len(before.channel.members) == 0:
                    try:
                        # Also clean up the associated text control panel channel.
                        # Control panel text channels are named "💬-{name}-party" and have
                        # restricted permissions (only owner can view). We match by:
                        # 1) name pattern 💬-*-party  2) topic contains "Control panel"
                        # 3) only visible to one member (the owner)
                        if before.channel.category:
                            for tc in before.channel.category.text_channels:
                                if (tc.name.startswith("💬-") and tc.name.endswith("-party")
                                        and tc.topic and "Control panel" in tc.topic):
                                    # Only delete if it has restricted permissions (private)
                                    overwrites = tc.overwrites
                                    non_default_overwrites = [o for o in overwrites if o != tc.guild.default_role]
                                    if len(non_default_overwrites) <= 2:  # @everyone + owner only
                                        await tc.delete(reason="Dynamic voice channel emptied")
                                        break
                        await before.channel.delete(reason="Dynamic voice channel emptied")
                        await self.db.unregister_voice_channel(before.channel.id)
                    except discord.HTTPException:
                        pass

        # Track activity for AFK detection
        if after.channel:
            self.recent_activity[member.id] = datetime.now(timezone.utc)

        # Generic greeting for regular (non-temp) voice channels — DISABLED.
        # Ava only greets people who open their own temp lobby room.
        # if after.channel and not before.channel:
        #     if (after.channel.id != settings.channel_lobby_create and
        #         after.channel.id != settings.channel_afk and
        #         not member.bot):
        #         owner_id = await self.db.get_voice_channel_owner(after.channel.id)
        #         if not owner_id:
        #             await self.greet_in_voice(member, after.channel)

        # Handle streaming role
        if after.self_video and not before.self_video:
            # User started streaming
            await self._add_stream_role(member)
        elif not after.self_video and before.self_video:
            # User stopped streaming
            await self._remove_stream_role(member)

        # Check for deafening (AFK indicator)
        if after.self_deaf and not before.self_deaf:
            # User deafened themselves
            pass  # Will be caught by AFK check

    async def _create_lobby_channel(self, member: discord.Member, guild: discord.Guild):
        """Create a new lobby voice channel for a member."""
        log_path = os.path.join(os.path.dirname(__file__), "..", "voice_debug.log")

        def log(msg: str):
            line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
            print(line, flush=True)
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

        log(f"_create_lobby_channel START for {member.display_name} (id={member.id})")
        log(f"Bot top role: {guild.me.top_role.name} (pos={guild.me.top_role.position})")
        log(f"Member top role: {member.top_role.name} (pos={member.top_role.position})")

        lobby_ch = guild.get_channel(settings.channel_lobby_create)
        if not lobby_ch:
            log(f"ERROR: lobby create channel {settings.channel_lobby_create} not found")
            return

        # Use the dedicated lobby category if configured, else fall back to the lobby channel's category
        if settings.channel_lobby_category:
            category = guild.get_channel(settings.channel_lobby_category)
            if not category:
                log(f"ERROR: lobby category {settings.channel_lobby_category} not found")
                return
        else:
            category = lobby_ch.category
            if not category:
                log("ERROR: lobby create channel has no category and CHANNEL_LOBBY_CATEGORY not set")
                return

        # If this member already owns a lobby, delete the old one first so there's only ever one per person
        existing_ch_id = await self.db.get_voice_channel_by_owner(member.id)
        if existing_ch_id and existing_ch_id != 0:
            log(f"Member already owns lobby {existing_ch_id}, cleaning up old one first...")
            await self._delete_lobby_channel(guild, existing_ch_id)

        # Create channel — fancy Unicode style based on the member's display name
        channel_name = f"{_fancy_name(member.display_name)}'s Room"
        log(f"About to create channel '{channel_name}' in category '{category.name}' (cat_id={category.id})")

        # Public temp channel: anyone can join, auto-deletes when empty.
        # manage_channel/manage_permissions are guild-level perms, NOT overwrites,
        # so they can't be set here. We just give @everyone normal voice access.
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
            ),
        }
        # Make sure the bot itself can see, connect & move members
        me = guild.me
        overwrites[me] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True,
            manage_permissions=True,
        )

        try:
            log("Step 1: calling guild.create_voice_channel (private, owner-only)...")
            new_channel = await guild.create_voice_channel(
                channel_name,
                category=category,
                overwrites=overwrites,
            )
            log(f"Step 1 OK: created #{channel_name} ({new_channel.id})")

            # Register in database
            log("Step 2: registering in DB...")
            await self.db.register_voice_channel(guild.id, new_channel.id, member.id)
            log("Step 2 OK: registered")

            # Move member to new channel
            log("Step 3: moving member...")
            try:
                await member.move_to(new_channel, reason="Auto-move to personal lobby")
                log(f"Step 3 OK: moved {member.display_name} to #{channel_name}")
            except discord.Forbidden as e:
                log(f"Step 3 WARN: could not move member — {e} (bot needs Move Members + role above member)")
            except discord.HTTPException as e:
                log(f"Step 3 WARN: move failed — {e.text}")

            log("=== _create_lobby_channel COMPLETE ===")

        except discord.Forbidden as e:
            log(f"ERROR creating voice channel: Forbidden — {e}")
            import traceback; traceback.print_exc()
        except discord.HTTPException as e:
            log(f"ERROR creating voice channel: {e.text} (status={e.status} code={e.code})")
            import traceback; traceback.print_exc()
        except Exception as e:
            log(f"ERROR unexpected: {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()

    async def _delete_lobby_channel(self, guild: discord.Guild, channel_id: int):
        """Delete a lobby voice channel and unregister it (best-effort, swallows errors)."""
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                await channel.delete(reason="Replaced by new lobby / cleanup")
            except discord.HTTPException:
                pass
        await self.db.unregister_voice_channel(channel_id)

    async def _add_stream_role(self, member: discord.Member):
        """Add stream role to a member."""
        if settings.role_live_in_vc == 0:
            return
        role = member.guild.get_role(settings.role_live_in_vc)
        if role and role not in member.roles:
            try:
                await member.add_roles(role)
            except discord.HTTPException:
                pass

    async def _remove_stream_role(self, member: discord.Member):
        """Remove stream role from a member."""
        if settings.role_live_in_vc == 0:
            return
        role = member.guild.get_role(settings.role_live_in_vc)
        if role and role in member.roles:
            try:
                await member.remove_roles(role)
            except discord.HTTPException:
                pass

    # ========== TTS Voice ==========

    async def speak(self, text: str, language: str = "en", voice_name: str = None) -> Optional[str]:
        """Generate TTS audio using gTTS and return path to temp file.

        Returns path to MP3 file, or None on failure.
        """
        try:
            from gtts import gTTS

            # Create temp file
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                temp_path = f.name

            # Generate speech (gTTS is synchronous, run in executor to not block)
            lang = "ar" if language == "ar" else "en"
            tts = gTTS(text=text, lang=lang)
            # gTTS.save is blocking I/O — offload to a thread
            await asyncio.get_event_loop().run_in_executor(None, tts.save, temp_path)

            return temp_path
        except Exception as e:
            print(f"[Voice] TTS error: {e}")
            return None

    async def greet_in_voice(self, member: discord.Member, channel: discord.VoiceChannel):
        """Greet a user by name in a voice channel using TTS."""
        try:
            # Check if bot is already in a voice channel in this guild
            voice_client = channel.guild.voice_client
            if voice_client and voice_client.channel == channel:
                # Already in the channel, just play greeting
                pass
            elif voice_client and voice_client.channel != channel:
                # In a different channel, move
                await voice_client.move_to(channel)
            else:
                # Not connected, join
                voice_client = await channel.connect()

            # Determine language from user's recent messages or default to English
            # For now, use a simple greeting
            ai_cog = self.bot.get_cog("AICog")
            greeting_text = ""
            language = "en"

            if ai_cog:
                # Get a random greeting from Ava's personality
                import random
                from utils.personality import OPENERS
                # Pick a casual greeting
                openers = OPENERS.get("greet_chill", []) + OPENERS.get("greet_hype", [])
                if openers:
                    opener = random.choice(openers)
                    greeting_text = f"{opener} {member.display_name}"
                else:
                    greeting_text = f"Hey {member.display_name}, welcome to the voice channel!"

                # Try to detect language from recent messages in the server
                # For now, default to English
                language = "en"
            else:
                greeting_text = f"Hey {member.display_name}, welcome!"

            # Generate and play TTS
            audio_path = await self.speak(greeting_text, language)
            if audio_path and voice_client and voice_client.is_connected():
                # Play the audio
                source = discord.FFmpegPCMAudio(audio_path)
                voice_client.play(source)

                # Wait for playback to finish
                while voice_client.is_playing():
                    await asyncio.sleep(0.1)

                # Clean up temp file
                try:
                    os.unlink(audio_path)
                except Exception:
                    pass

        except Exception as e:
            print(f"[Voice] Greeting error: {e}")

    async def _greet_lobby_join(self, member: discord.Member, channel: discord.VoiceChannel, owner_id: int):
        """TTS greeting when someone joins a temp lobby: 'Hey X, welcome to Y's party!'"""
        def log(msg: str):
            print(f"[VoiceGreet] {msg}", flush=True)

        # Debounce: if a greeting is already running for this channel, skip
        if channel.id in self._greeting_locks:
            log(f"skipping duplicate greeting for ch={channel.id}")
            return
        self._greeting_locks.add(channel.id)

        try:
            # Resolve the owner's display name for a personal touch
            owner = channel.guild.get_member(owner_id)
            owner_name = owner.display_name if owner else "the host"

            # Pick a greeting — hype style for party vibe
            import random
            from utils.personality import OPENERS
            if member.id == owner_id:
                greetings = [
                    f"Hey {member.display_name}, welcome to your party!",
                    f"What's up {member.display_name}! Your room is ready!",
                    f"Welcome to your lobby {member.display_name}!",
                ]
            else:
                greetings = (
                    OPENERS.get("greet_hype", [])
                    + OPENERS.get("greet_chill", [])
                    + [
                        f"Hey {member.display_name}, welcome to {owner_name}'s party!",
                        f"What's up {member.display_name}! Welcome to {owner_name}'s room!",
                        f"Welcome {member.display_name}, you've joined {owner_name}'s party!",
                    ]
                )
            greeting_text = random.choice(greetings) if greetings else f"Hey {member.display_name}, welcome to {owner_name}'s party!"
            log(f"greeting='{greeting_text}'")

            # Generate TTS first (before connecting — faster, avoids blocking)
            log("generating TTS...")
            audio_path = await self.speak(greeting_text, "en")
            log(f"TTS result: audio_path={audio_path}")
            if not audio_path:
                log("FAIL: no audio generated")
                return

            # Connect (or move) Ava to the channel
            log("connecting to voice...")
            voice_client = channel.guild.voice_client
            if voice_client and voice_client.channel == channel:
                log("already in channel")
            elif voice_client and voice_client.channel != channel:
                log("moving to channel...")
                await voice_client.move_to(channel)
                # Wait for connection to stabilize
                for _ in range(20):
                    if voice_client.is_connected() and voice_client.channel == channel:
                        break
                    await asyncio.sleep(0.1)
            else:
                log("connecting fresh...")
                voice_client = await channel.connect()
                # Wait for connection to stabilize
                for _ in range(20):
                    if voice_client.is_connected():
                        break
                    await asyncio.sleep(0.1)
            log(f"connected (is_connected={voice_client.is_connected()}, channel={voice_client.channel})")

            if not voice_client or not voice_client.is_connected():
                log("FAIL: not connected after connect")
                return

            # Play the audio and wait for it to finish
            log("playing audio...")
            # Find ffmpeg — winget install puts it here but may not be on PATH yet
            _ffmpeg_path = shutil.which("ffmpeg") or os.path.expandvars(
                r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"
            )
            if not _ffmpeg_path or not os.path.exists(_ffmpeg_path):
                log(f"FAIL: ffmpeg not found (looked in PATH and winget default)")
                return
            log(f"using ffmpeg: {_ffmpeg_path}")
            source = discord.FFmpegPCMAudio(audio_path, executable=_ffmpeg_path)
            voice_client.play(source)
            while voice_client.is_playing():
                await asyncio.sleep(0.1)
            log("playback done")

            # Clean up temp file
            try:
                os.unlink(audio_path)
            except Exception:
                pass

            # Leave the channel after greeting so Ava doesn't linger
            try:
                await voice_client.disconnect()
                log("disconnected")
            except Exception:
                pass

        except Exception as e:
            import traceback
            log(f"ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            self._greeting_locks.discard(channel.id)

    @tasks.loop(minutes=5)
    async def afk_check(self):
        """AFK auto-move is disabled. Loop kept for future use."""
        # Previously moved deafened/idle members to the AFK channel.
        # Disabled on user request — no action taken.
        return

    @afk_check.before_loop
    async def before_afk_check(self):
        """Wait until bot is ready."""
        await self.bot.wait_until_ready()

    async def cog_unload(self):
        """Clean up on cog unload."""
        self.afk_check.cancel()


async def setup(bot: commands.Bot) -> None:
    """Setup the cog."""
    db = bot.db
    await bot.add_cog(VoiceCog(bot, db))
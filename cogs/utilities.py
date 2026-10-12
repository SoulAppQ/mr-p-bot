"""
Server Utility, Moderation Cog for MR P Bot.
Handles match history, roulette, debt tracking, Steam stats, and events.
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta, timezone
import random
import json
from typing import Optional, List

from config.settings import settings
from database.models import Database
from utils.helpers import ava_embed, safe_send
from utils.steam_api import SteamAPI, get_steam_api


class UtilitiesCog(commands.Cog):
    """Utilities, moderation, and match history commands."""

    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    @app_commands.command(name="gg", description="Log a match result (win/loss)")
    @app_commands.describe(
        result="The match result",
        game="The game played (optional)",
        notes="Additional notes about the match"
    )
    @app_commands.choices(result=[
        app_commands.Choice(name="Win", value="win"),
        app_commands.Choice(name="Loss", value="loss"),
    ])
    async def gg(
        self,
        interaction: discord.Interaction,
        result: app_commands.Choice[str],
        game: Optional[str] = None,
        notes: Optional[str] = None
    ):
        """Log a match result."""
        await interaction.response.defer()

        if not game:
            game = "general"
        elif len(game) > 50:
            game = game[:50]

        match_id = await self.db.add_match(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
            game=game.lower(),
            result=result.value,
            notes=notes
        )

        embed = ava_embed(
            title="📊 Match Logged",
            color=0x57F287 if result.value == "win" else 0xED4245,
            footer_cmd="gg",
            thumbnail=interaction.user.display_avatar.url,
            fields=[
                ("Result", result.name, True),
                ("Game", game.capitalize(), True),
            ]
        )
        if notes:
            embed.add_field(name="Notes", value=notes, inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="stats", description="View your match statistics")
    @app_commands.describe(
        user="The user to check (defaults to you)",
        game="Filter by game (optional)"
    )
    async def stats(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.User] = None,
        game: Optional[str] = None
    ):
        """View match statistics."""
        await interaction.response.defer()

        target = user or interaction.user
        stats = await self.db.get_user_stats(
            guild_id=interaction.guild.id,
            user_id=target.id,
            game=game
        )

        win_rate = 0
        if stats["total"] > 0:
            win_rate = int(stats["wins"] / stats["total"] * 100)

        embed = ava_embed(
            title=f"📊 {target.display_name}'s Stats",
            footer_cmd="stats",
            thumbnail=str(target.display_avatar.url),
            fields=[
                ("Total Matches", str(stats["total"]), True),
                ("Wins", str(stats["wins"]), True),
                ("Losses", str(stats["losses"]), True),
                ("Win Rate", f"{win_rate}%", True),
            ],
        )
        if game:
            embed.title = f"📊 {target.display_name}'s {game.capitalize()} Stats"

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="leaderboard", description="View the match leaderboard")
    @app_commands.describe(
        game="Filter by game (optional)",
        limit="Number of results to show (1-20, default: 10)"
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        game: Optional[str] = None,
        limit: app_commands.Range[int, 1, 20] = 10
    ):
        """View the match leaderboard."""
        await interaction.response.defer()

        leaderboard = await self.db.get_leaderboard(
            guild_id=interaction.guild.id,
            game=game,
            limit=limit
        )

        if not leaderboard:
            embed = ava_embed(title="🏆 Leaderboard",
                              description="No match data found yet. Start logging matches with `/gg`!",
                              footer_cmd="leaderboard")
            await interaction.followup.send(embed=embed)
            return

        entries = []
        for i, entry in enumerate(leaderboard, 1):
            user = self.bot.get_user(entry["user_id"])
            user_name = user.display_name if user else f"User {entry['user_id']}"
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"#{i}")
            entries.append(f"{medal} **{user_name}** — {entry['wins']}W / {entry['losses']}L / {entry['total']} total")

        embed = ava_embed(
            title="🏆 Match Leaderboard",
            description="\n".join(entries),
            footer_cmd="leaderboard",
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="roulette", description="Randomly pick an option when you can't decide")
    @app_commands.describe(options="Comma-separated options to choose from")
    async def roulette(self, interaction: discord.Interaction, options: str):
        """Spin the squad roulette."""
        await interaction.response.defer()

        choice_list = [opt.strip() for opt in options.split(",") if opt.strip()]
        if len(choice_list) < 2:
            embed = ava_embed(title="🎡 Roulette",
                              description="Please provide at least 2 options!",
                              footer_cmd="roulette")
            await interaction.followup.send(embed=embed)
            return

        winner = random.choice(choice_list)
        embed = ava_embed(
            title="🎡 Roulette",
            description=f"🎯 We've decided: **{winner}**!",
            footer_cmd="roulette",
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="debt", description="Track bets and debts")
    @app_commands.describe(
        action="Action to take (add, list, settle)",
        debtor="Who owes (for add action)",
        creditor="Who is owed (for add action)",
        amount="What's owed (for add action)",
        reason="Reason for the debt (for add action)",
        debt_id="Debt ID to settle (for settle action)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="List", value="list"),
        app_commands.Choice(name="Settle", value="settle"),
    ])
    async def debt(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        debtor: Optional[discord.User] = None,
        creditor: Optional[discord.User] = None,
        amount: Optional[str] = None,
        reason: Optional[str] = None,
        debt_id: Optional[int] = None
    ):
        """Track squad debts and bets."""
        await interaction.response.defer()

        if action.value == "add":
            if not all([debtor, creditor, amount]):
                embed = ava_embed(title="💰 Debt Add",
                                  description="Usage: `/debt add <debtor> <creditor> <amount> [reason]`",
                                  footer_cmd="debt")
                await interaction.followup.send(embed=embed)
                return

            debt_id = await self.db.add_debt(
                guild_id=interaction.guild.id,
                debtor_id=debtor.id,
                creditor_id=creditor.id,
                amount=amount,
                reason=reason or "Squad bet"
            )

            embed = ava_embed(
                title="💰 Debt Added",
                footer_cmd="debt",
                fields=[
                    ("Debtor", debtor.mention, True),
                    ("Creditor", creditor.mention, True),
                    ("Amount", amount, True),
                ]
            )
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)

            await interaction.followup.send(embed=embed)

        elif action.value == "list":
            debts = await self.db.get_debts(interaction.guild.id, interaction.user.id)

            if not debts:
                embed = ava_embed(title="💰 Your Debts",
                                  description="No debts found! You're all clear 🎉",
                                  footer_cmd="debt")
                await interaction.followup.send(embed=embed)
                return

            embed = ava_embed(
                title="💰 Your Debts",
                footer_cmd="debt",
            )

            for debt in debts[:10]:
                debtor = self.bot.get_user(debt.debtor_id)
                creditor = self.bot.get_user(debt.creditor_id)
                status = "✅ Settled" if debt.settled else "❌ Unsettled"
                embed.add_field(
                    name=f"#{debt.id} - {status}",
                    value=f"{debtor.mention if debtor else f'User {debt.debtor_id}'} owes "
                          f"{creditor.mention if creditor else f'User {debt.creditor_id}'} "
                          f"**{debt.amount}**\n*{debt.reason}*",
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        elif action.value == "settle":
            if not debt_id:
                embed = ava_embed(title="💰 Debt Settle",
                                  description="Usage: `/debt settle <debt_id>`",
                                  footer_cmd="debt")
                await interaction.followup.send(embed=embed)
                return

            success = await self.db.settle_debt(debt_id, interaction.guild.id)
            if success:
                embed = ava_embed(
                    title="💰 Debt Settled",
                    description=f"Debt #{debt_id} has been settled! 🎉",
                    footer_cmd="debt",
                )
                await interaction.followup.send(embed=embed)
            else:
                embed = ava_embed(title="💰 Debt Settle",
                                  description="Could not find or settle that debt.",
                                  footer_cmd="debt")
                await interaction.followup.send(embed=embed)

    # ========== Steam Commands ==========

    @app_commands.command(name="link-steam", description="Link your Steam profile to Discord")
    @app_commands.describe(steam_id="Your Steam ID, vanity URL, or profile URL")
    async def link_steam(self, interaction: discord.Interaction, steam_id: str):
        """Link a Steam profile to your Discord account."""
        await interaction.response.defer()

        async with await get_steam_api() as steam:
            resolved_id = await steam.resolve_vanity_url(steam_id)
            if not resolved_id:
                embed = ava_embed(title="🔗 Steam Link",
                                  description="Could not resolve that Steam ID. Try your profile URL or custom ID.",
                                  color=0x1B2838, footer_cmd="link-steam")
                await interaction.followup.send(embed=embed)
                return

            profile = await steam.get_player_summary(resolved_id)
            if not profile:
                embed = ava_embed(title="🔗 Steam Link",
                                  description="Could not fetch that Steam profile.",
                                  color=0x1B2838, footer_cmd="link-steam")
                await interaction.followup.send(embed=embed)
                return

            await self.db.link_steam(
                guild_id=interaction.guild.id,
                user_id=interaction.user.id,
                username=interaction.user.display_name,
                steam_id=resolved_id,
                vanity_url=steam_id
            )

            embed = ava_embed(
                title="🔗 Steam Profile Linked",
                color=0x1B2838,
                footer_cmd="link-steam",
                fields=[
                    ("Steam Name", profile.personaname, True),
                    ("Steam ID", resolved_id, True),
                    ("Profile", f"[View Profile]({profile.profile_url})", True),
                ],
                thumbnail=profile.avatar_url
            )
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="steam-stats", description="View Steam stats for a user")
    @app_commands.describe(user="User to check (defaults to you)")
    async def steam_stats(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        """View Steam profile and game stats."""
        await interaction.response.defer()
        target = user or interaction.user

        link = await self.db.get_steam_link(interaction.guild.id, target.id)
        if not link:
            embed = ava_embed(title="🎮 Steam Stats",
                              description=f"{target.mention} hasn't linked their Steam profile. Use `/link-steam` first.",
                              color=0x1B2838, footer_cmd="steam-stats")
            await interaction.followup.send(embed=embed)
            return

        async with await get_steam_api() as steam:
            profile = await steam.get_player_summary(link["steam_id"])
            if not profile:
                embed = ava_embed(title="🎮 Steam Stats",
                                  description="Could not fetch Steam profile.",
                                  color=0x1B2838, footer_cmd="steam-stats")
                await interaction.followup.send(embed=embed)
                return

            games = await steam.get_owned_games(link["steam_id"])
            cs2_game = next((g for g in games if g.appid == 730), None)
            recent = await steam.get_recently_played(link["steam_id"], 5)

        top_games = sorted(games, key=lambda g: g.playtime_forever, reverse=True)[:5]
        top_games_str = "\n".join(
            f"**{g.name}** — {await self._format_playtime(g.playtime_forever)}"
            for g in top_games
        ) or "No games found"

        recent_str = "\n".join(
            f"**{g.name}** — {await self._format_playtime(g.playtime_2weeks)} (2 weeks)"
            for g in recent
        ) or "Nothing recently"

        status_emoji = {0: "🔴 Offline", 1: "🟢 Online", 2: "🟡 Busy", 3: "🟠 Away", 4: "🟣 Snooze"}.get(profile.personastate, "❓ Unknown")

        embed = ava_embed(
            title=f"🎮 {profile.personaname}'s Steam Profile",
            color=0x1B2838,
            footer_cmd="steam-stats",
            thumbnail=profile.avatar_url,
            fields=[
                ("Status", status_emoji, True),
                ("Steam ID", link["steam_id"], True),
                ("Top Games (All Time)", top_games_str, False),
                ("Recent Activity (2 Weeks)", recent_str, False),
            ]
        )

        if cs2_game:
            embed.add_field(
                name="🎯 CS2",
                value=f"Playtime: {await self._format_playtime(cs2_game.playtime_forever)}",
                inline=True
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="cs2-stats", description="View detailed CS2 stats for a user")
    @app_commands.describe(user="User to check (defaults to you)")
    async def cs2_stats(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        """View detailed CS2 statistics."""
        await interaction.response.defer()
        target = user or interaction.user

        link = await self.db.get_steam_link(interaction.guild.id, target.id)
        if not link:
            embed = ava_embed(title="🎯 CS2 Stats",
                              description=f"{target.mention} hasn't linked their Steam profile. Use `/link-steam` first.",
                              footer_cmd="cs2-stats")
            await interaction.followup.send(embed=embed)
            return

        async with await get_steam_api() as steam:
            stats = await steam.get_cs2_stats(link["steam_id"])
            profile = await steam.get_player_summary(link["steam_id"])

        kd = 0
        if stats.total_deaths > 0:
            kd = round(stats.total_kills / stats.total_deaths, 2)

        hs_pct = 0
        if stats.total_kills > 0:
            hs_pct = round(stats.headshot_kills / stats.total_kills * 100, 1)

        accuracy = 0
        if stats.shots_fired > 0:
            accuracy = round(stats.shots_hit / stats.shots_fired * 100, 1)

        win_rate = 0
        if stats.total_rounds_played > 0:
            win_rate = round(stats.total_wins / stats.total_rounds_played * 100, 1)

        embed = ava_embed(
            title=f"🎯 {target.display_name}'s CS2 Stats",
            footer_cmd="cs2-stats",
            thumbnail=profile.avatar_url if profile else None,
            fields=[
                ("Kills / Deaths", f"{stats.total_kills:,} / {stats.total_deaths:,}", True),
                ("K/D Ratio", f"{kd:.2f}", True),
                ("Headshot %", f"{hs_pct}%", True),
                ("MVPs", f"{stats.total_mvps:,}", True),
                ("Rounds Won", f"{stats.total_wins:,} / {stats.total_rounds_played:,}", True),
                ("Win Rate", f"{win_rate}%", True),
                ("Accuracy", f"{accuracy}%", True),
                ("Favorite Weapon", stats.favorite_weapon or "Unknown", True),
            ]
        )
        await interaction.followup.send(embed=embed)

    async def _format_playtime(self, minutes: int) -> str:
        """Format minutes into human-readable playtime."""
        hours = minutes // 60
        mins = minutes % 60
        if hours >= 1000:
            return f"{hours // 1000}k hrs"
        elif hours > 0:
            return f"{hours}h {mins}m" if mins else f"{hours}h"
        return f"{mins}m"

    # ========== Event Commands ==========

    @app_commands.command(name="event", description="Create and manage events")
    @app_commands.describe(
        action="Action to take",
        title="Event title",
        minutes_from_now="Minutes from now when event starts",
        description="Event description",
        event_id="Event ID to cancel"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Create", value="create"),
        app_commands.Choice(name="List", value="list"),
        app_commands.Choice(name="Cancel", value="cancel"),
    ])
    async def event(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        title: Optional[str] = None,
        minutes_from_now: Optional[int] = None,
        description: Optional[str] = None,
        event_id: Optional[int] = None
    ):
        """Create, list, or cancel scheduled events with RSVP."""
        await interaction.response.defer()

        if action.value == "create":
            if not title or not minutes_from_now:
                embed = ava_embed(title="📅 Event Create",
                                  description="Usage: `/event create <title> <minutes_from_now> [description]`",
                                  footer_cmd="event")
                await interaction.followup.send(embed=embed)
                return

            if minutes_from_now < 1 or minutes_from_now > 10080:
                embed = ava_embed(title="📅 Event Create",
                                  description="Minutes must be between 1 and 10080 (1 week).",
                                  footer_cmd="event")
                await interaction.followup.send(embed=embed)
                return

            scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)

            event_id = await self.db.create_event(
                guild_id=interaction.guild.id,
                creator_id=interaction.user.id,
                creator_name=interaction.user.display_name,
                title=title,
                description=description or "",
                scheduled_at=scheduled_at.isoformat(),
                channel_id=interaction.channel.id,
            )

            from discord.ui import View, Button

            class RSVPView(View):
                def __init__(self, event_id, db, bot):
                    super().__init__(timeout=None)
                    self.event_id = event_id
                    self.db = db
                    self.bot = bot

                @discord.ui.button(label="✅ Going", style=discord.ButtonStyle.success, custom_id=f"rsvp_going_{event_id}")
                async def going(self, interaction: discord.Interaction, button: Button):
                    await self.db.rsvp_event(self.event_id, interaction.user.id, interaction.user.display_name, "going")
                    embed = ava_embed(title="📅 RSVP", description="You're going! 🎉", footer_cmd="event")
                    await interaction.response.send_message(embed=embed, ephemeral=True)

                @discord.ui.button(label="❓ Maybe", style=discord.ButtonStyle.secondary, custom_id=f"rsvp_maybe_{event_id}")
                async def maybe(self, interaction: discord.Interaction, button: Button):
                    await self.db.rsvp_event(self.event_id, interaction.user.id, interaction.user.display_name, "maybe")
                    embed = ava_embed(title="📅 RSVP", description="You're a maybe 🤔", footer_cmd="event")
                    await interaction.response.send_message(embed=embed, ephemeral=True)

                @discord.ui.button(label="❌ Can't Make It", style=discord.ButtonStyle.danger, custom_id=f"rsvp_declined_{event_id}")
                async def declined(self, interaction: discord.Interaction, button: Button):
                    await self.db.rsvp_event(self.event_id, interaction.user.id, interaction.user.display_name, "declined")
                    embed = ava_embed(title="📅 RSVP", description="Marked as declined.", footer_cmd="event")
                    await interaction.response.send_message(embed=embed, ephemeral=True)

            view = RSVPView(event_id, self.db, self.bot)

            embed = ava_embed(
                title=f"📅 {title}",
                description=description or "No description provided.",
                footer_cmd="event",
                fields=[
                    ("When", f"<t:{int(scheduled_at.timestamp())}:F> (<t:{int(scheduled_at.timestamp())}:R>)", True),
                    ("Created by", interaction.user.mention, True),
                ],
            )

            msg = await interaction.followup.send(embed=embed, view=view)
            await self.db.set_event_message_id(event_id, msg.id)

        elif action.value == "list":
            events = await self.db.get_upcoming_events(interaction.guild.id)

            if not events:
                embed = ava_embed(title="📅 Upcoming Events",
                                  description="No upcoming events. Create one with `/event create`!",
                                  footer_cmd="event")
                await interaction.followup.send(embed=embed)
                return

            embed = ava_embed(
                title="📅 Upcoming Events",
                footer_cmd="event",
            )

            for event in events[:10]:
                rsvps = await self.db.get_all_event_rsvps(event["id"])
                going = len([r for r in rsvps if r["status"] == "going"])
                maybe = len([r for r in rsvps if r["status"] == "maybe"])
                scheduled = datetime.fromisoformat(event["scheduled_at"])
                if scheduled.tzinfo is None:
                    scheduled = scheduled.replace(tzinfo=timezone.utc)

                embed.add_field(
                    name=f"#{event['id']} — {event['title']}",
                    value=f"⏰ <t:{int(scheduled.timestamp())}:F> (<t:{int(scheduled.timestamp())}:R>)\n"
                          f"👥 {going} going · {maybe} maybe\n"
                          f"📝 {event['description'][:100]}{'...' if len(event['description']) > 100 else ''}",
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        elif action.value == "cancel":
            if not event_id:
                embed = ava_embed(title="📅 Event Cancel",
                                  description="Usage: `/event cancel <event_id>`",
                                  footer_cmd="event")
                await interaction.followup.send(embed=embed)
                return

            await self.db.delete_event(event_id, interaction.guild.id)
            embed = ava_embed(title="📅 Event Cancelled",
                              description=f"Event #{event_id} has been cancelled.",
                              footer_cmd="event")
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    """Setup the cog."""
    db = bot.db
    await bot.add_cog(UtilitiesCog(bot, db))

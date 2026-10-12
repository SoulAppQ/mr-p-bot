"""
MR P Discord Bot - Main entry point.
A lightweight server management bot: voice rooms, roles, housekeeping, utilities, events.
Deploys free on Railway/Render. No AI, no Ollama, no Instagram.
"""
import discord
from discord.ext import commands
import asyncio
import sys
import io
from pathlib import Path

from config.settings import settings
from database.models import Database


# Configure intents
intents = discord.Intents.all()
intents.message_content = True
intents.members = True
intents.voice_states = True


class MrPBot(commands.Bot):
    """MR P — 24/7 server management bot."""

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            application_id=settings.application_id
        )
        self.db: Database = None

    async def setup_hook(self):
        """Setup hook for initializing the bot."""
        print("[START] Setting up MR P...")

        # Initialize database
        self.db = Database(settings.database_path)
        await self.db.initialize()

        # Load cogs
        cogs_to_load = [
            "cogs.voice",
            "cogs.roles",
            "cogs.housekeeping",
            "cogs.utilities",
        ]

        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
                print(f"[OK] Loaded cog: {cog}")
            except Exception as e:
                print(f"[ERROR] Failed to load cog {cog}: {e}")

        # Sync commands to guild if specified
        if settings.guild_id:
            guild = discord.Object(id=settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"[OK] Synced commands to guild {settings.guild_id}")
        else:
            await self.tree.sync()
            print("[OK] Synced commands globally")

        print("[OK] MR P is ready!")

    async def on_ready(self):
        """Called when the bot is ready."""
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")
        print(f"🔄 Serving {len(self.guilds)} guilds")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name="Server Manager | /help"
            )
        )

    async def close(self):
        """Clean up before closing."""
        if self.db:
            await self.db.close()
        await super().close()

    async def on_command_error(self, ctx, error):
        """Handle command errors."""
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use that command!")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("❌ I don't have permission to do that!")
        else:
            print(f"Command error: {error}")
            await ctx.send("❌ An error occurred while executing that command.")


async def main():
    """Main entry point."""
    # Set stdout to UTF-8 to handle emoji on Windows
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

    print("[START] Starting MR P Bot...")

    # Create required directories
    Path("database").mkdir(ex_ok=True)

    # Initialize bot
    bot = MrPBot()

    try:
        await bot.start(settings.discord_token)
    except discord.LoginFailure:
        print("[ERROR] Invalid Discord token!")
    except KeyboardInterrupt:
        print("[STOP] Bot stopped by user")
    except Exception as e:
        print(f"[ERROR] Bot crashed: {e}")
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())

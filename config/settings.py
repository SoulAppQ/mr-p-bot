"""
Configuration settings for MR P Discord Bot.
Loads environment variables and provides type-safe access to configuration.
"""
import os
from dataclasses import dataclass
from typing import List, Dict, Optional
from pathlib import Path

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use system env vars


@dataclass
class Settings:
    """Main bot settings loaded from environment variables."""

    # Discord
    discord_token: str
    application_id: int
    guild_id: Optional[int] = None

    # Database
    database_path: str = "database/mr_p.db"

    # Channel IDs
    channel_lobby_create: int = 0
    channel_lobby_category: int = 0
    channel_afk: int = 0
    channel_hall_of_fame: int = 0
    channel_mod_logs: int = 0
    channel_clips: int = 0
    channel_media: int = 0
    channel_roles_directory: int = 0
    channel_bot_commands: int = 0
    channel_general: int = 0

    # Role IDs
    role_live_in_vc: int = 0
    game_roles: Dict[str, int] = None

    # Starboard/Skullboard
    starboard_emoji: str = "⭐"
    starboard_threshold: int = 3
    skullboard_emoji: str = "💀"
    skullboard_threshold: int = 3

    # Timeouts
    afk_timeout: int = 900  # 15 minutes

    def __post_init__(self):
        # Parse game roles from environment
        if self.game_roles is None:
            self.game_roles = {}
            game_roles_env = os.getenv("GAME_ROLES", "")
            if game_roles_env:
                for pair in game_roles_env.split(","):
                    if ":" in pair:
                        name, role_id = pair.split(":", 1)
                        self.game_roles[name.upper()] = int(role_id)


def load_settings() -> Settings:
    """Load settings from environment variables."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN environment variable is required")

    app_id = os.getenv("APPLICATION_ID")
    if not app_id:
        raise ValueError("APPLICATION_ID environment variable is required")

    guild_id = os.getenv("GUILD_ID")

    return Settings(
        discord_token=token,
        application_id=int(app_id),
        guild_id=int(guild_id) if guild_id else None,
        database_path=os.getenv("DATABASE_PATH", "database/mr_p.db"),
        channel_lobby_create=int(os.getenv("CHANNEL_LOBBY_CREATE", "0")),
        channel_lobby_category=int(os.getenv("CHANNEL_LOBBY_CATEGORY", "0")),
        channel_afk=int(os.getenv("CHANNEL_AFK", "0")),
        channel_hall_of_fame=int(os.getenv("CHANNEL_HALL_OF_FAME", "0")),
        channel_mod_logs=int(os.getenv("CHANNEL_MOD_LOGS", "0")),
        channel_clips=int(os.getenv("CHANNEL_CLIPS", "0")),
        channel_media=int(os.getenv("CHANNEL_MEDIA", "0")),
        channel_roles_directory=int(os.getenv("CHANNEL_ROLES_DIRECTORY", "0")),
        channel_bot_commands=int(os.getenv("CHANNEL_BOT_COMMANDS", "0")),
        channel_general=int(os.getenv("CHANNEL_GENERAL", "0")),
        role_live_in_vc=int(os.getenv("ROLE_LIVE_IN_VC", "0")),
        afk_timeout=int(os.getenv("AFK_TIMEOUT", "900")),
        starboard_emoji=os.getenv("STARBOARD_EMOJI", "⭐"),
        starboard_threshold=int(os.getenv("STARBOARD_THRESHOLD", "3")),
        skullboard_emoji=os.getenv("SKULLBOARD_EMOJI", "💀"),
        skullboard_threshold=int(os.getenv("SKULLBOARD_THRESHOLD", "3")),
    )


# Global settings instance
settings = load_settings()


# Game launch URLs mapping
GAME_LAUNCH_URLS: Dict[str, Dict[str, str]] = {
    "palworld": {
        "name": "Palworld",
        "steam_app_id": "1623730",
        "launch_url": "steam://run/1623730",
        "image": "https://cdn.cloudflare.steamstatic.com/steam/apps/1623730/header.jpg",
        "color": 0xFFA500,
    },
    "cs2": {
        "name": "Counter-Strike 2",
        "steam_app_id": "730",
        "launch_url": "steam://run/730",
        "image": "https://cdn.cloudflare.steamstatic.com/steam/apps/730/header.jpg",
        "color": 0xFF4444,
    },
    "l4d2": {
        "name": "Left 4 Dead 2",
        "steam_app_id": "550",
        "launch_url": "steam://run/550",
        "image": "https://cdn.cloudflare.steamstatic.com/steam/apps/550/header.jpg",
        "color": 0xCC0000,
    },
    "gta5": {
        "name": "Grand Theft Auto V",
        "steam_app_id": "271590",
        "launch_url": "steam://run/271590",
        "image": "https://cdn.cloudflare.steamstatic.com/steam/apps/271590/header.jpg",
        "color": 0x00AA00,
    },
    "valheim": {
        "name": "Valheim",
        "steam_app_id": "892970",
        "launch_url": "steam://run/892970",
        "image": "https://cdn.cloudflare.steamstatic.com/steam/apps/892970/header.jpg",
        "color": 0x8B4513,
    },
    "deep rock galactic": {
        "name": "Deep Rock Galactic",
        "steam_app_id": "548430",
        "launch_url": "steam://run/548430",
        "image": "https://cdn.cloudflare.steamstatic.com/steam/apps/548430/header.jpg",
        "color": 0xFFD700,
    },
    "vermont": {
        "name": "Vermont",
        "steam_app_id": "2394010",
        "launch_url": "steam://run/2394010",
        "image": "https://cdn.cloudflare.steamstatic.com/steam/apps/2394010/header.jpg",
        "color": 0x4A90D9,
    },
    "roblox": {
        "name": "Roblox",
        "launch_url": "roblox://placeID=1818",
        "image": "https://tr.rbxcdn.com/180DAY-1e8a8b8b5b5b5b5b5b5b5b5b5b5b5b5b/420/420/Image/Png",
        "color": 0x00A2FF,
    },
    "fortnite": {
        "name": "Fortnite",
        "launch_url": "com.epicgames.launcher://apps/Fortnite?action=launch",
        "image": "https://cdn.cloudflare.steamstatic.com/steam/apps/1879720/header.jpg",
        "color": 0x00D9FF,
    },
    "overwatch2": {
        "name": "Overwatch 2",
        "launch_url": "battlenet://pro/overwatch2",
        "image": "https://bnetcmsus-a.akamaihd.net/cms/gallery/OW2_KeyArt.jpg",
        "color": 0xFF6EC7,
    },
    "valorant": {
        "name": "VALORANT",
        "launch_url": "valorant://launch",
        "image": "https://media.valorant-api.com/agents/1e3d0c7f-433b-4c7e-8c7e-8c7e8c7e8c7e/displayicon.png",
        "color": 0xFF4655,
    },
    "minecraft": {
        "name": "Minecraft",
        "launch_url": "minecraft://",
        "image": "https://www.minecraft.net/etc.clientlibs/minecraft/clientlibs/main/resources/img/minecraft-logo.svg",
        "color": 0x62B474,
    },
}


def get_game_info(game_key: str) -> Optional[Dict[str, str]]:
    """Get game launch info by key (case-insensitive)."""
    return GAME_LAUNCH_URLS.get(game_key.lower())


def get_all_games() -> Dict[str, Dict[str, str]]:
    """Get all available games."""
    return GAME_LAUNCH_URLS


def get_role_name_for_game(game_key: str) -> str:
    """Get the Discord role name for a game."""
    game = get_game_info(game_key)
    if game:
        return game["name"]
    return game_key.upper()

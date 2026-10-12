"""
Steam Web API wrapper — free, no key required for public profiles.
"""
import aiohttp
import asyncio
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime


STEAM_API_BASE = "https://api.steampowered.com"
CS2_APP_ID = 730


@dataclass
class SteamUser:
    """Steam user summary."""
    steam_id: str
    personaname: str
    avatar_url: str
    profile_url: str
    personastate: int  # 0=offline, 1=online, 2=busy, 3=away, 4=snooze, 5=looking to trade, 6=looking to play
    gameid: Optional[str] = None
    gameextrainfo: Optional[str] = None


@dataclass
class OwnedGame:
    """An owned Steam game."""
    appid: int
    name: str
    playtime_forever: int  # minutes
    playtime_2weeks: int = 0
    img_icon_url: str = ""
    img_logo_url: str = ""


@dataclass
class CS2Stats:
    """CS2-specific stats."""
    total_kills: int = 0
    total_deaths: int = 0
    total_mvps: int = 0
    total_wins: int = 0
    total_rounds_played: int = 0
    favorite_weapon: str = ""
    headshot_kills: int = 0
    shots_fired: int = 0
    shots_hit: int = 0
    last_match: Optional[str] = None


class SteamAPI:
    """Steam Web API client."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _params(self, extra: Dict = None) -> Dict:
        """Build query parameters with optional API key."""
        params = {}
        if self.api_key:
            params["key"] = self.api_key
        if extra:
            params.update(extra)
        return params

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """GET request to Steam API."""
        if not self.session:
            self.session = aiohttp.ClientSession()

        url = f"{STEAM_API_BASE}{endpoint}"
        try:
            async with self.session.get(url, params=self._params(params), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json()
                print(f"[SteamAPI] HTTP {resp.status} for {endpoint}")
                return None
        except asyncio.TimeoutError:
            print(f"[SteamAPI] Timeout for {endpoint}")
            return None
        except Exception as e:
            print(f"[SteamAPI] Error for {endpoint}: {e}")
            return None

    async def resolve_vanity_url(self, vanity_url: str) -> Optional[str]:
        """Convert a vanity URL or custom ID to 64-bit Steam ID.

        Accepts:
        - Full URL: https://steamcommunity.com/id/username
        - Vanity: username
        - SteamID64: 76561198xxxxxxxxx
        - SteamID32: STEAM_0:0:xxxxx
        """
        # Already a 64-bit Steam ID
        if vanity_url.isdigit() and len(vanity_url) == 17 and vanity_url.startswith("7656119"):
            return vanity_url

        # SteamID32 format: STEAM_0:0:123456
        steam32_match = re.match(r"STEAM_[01]:[01]:(\d+)", vanity_url)
        if steam32_match:
            steam32 = int(steam32_match.group(1))
            return str(76561197960265728 + steam32)

        # Extract vanity from URL
        vanity = vanity_url
        if "steamcommunity.com" in vanity_url:
            # https://steamcommunity.com/id/vanityname
            # https://steamcommunity.com/profiles/76561198...
            match = re.search(r"steamcommunity\.com/(?:id|profiles)/([^/?#]+)", vanity_url)
            if match:
                vanity = match.group(1)
                # If it's already a 64-bit ID from /profiles/
                if vanity.isdigit() and len(vanity) == 17:
                    return vanity

        # Resolve vanity URL
        data = await self._get("/ISteamUser/ResolveVanityURL/v1/", {"vanityurl": vanity})
        if data and data.get("response", {}).get("success") == 1:
            return data["response"]["steamid"]
        return None

    async def get_player_summary(self, steam_id: str) -> Optional[SteamUser]:
        """Get player summary (profile info)."""
        data = await self._get("/ISteamUser/GetPlayerSummaries/v2/", {"steamids": steam_id})
        if data:
            players = data.get("response", {}).get("players", [])
            if players:
                p = players[0]
                return SteamUser(
                    steam_id=p.get("steamid", steam_id),
                    personaname=p.get("personaname", "Unknown"),
                    avatar_url=p.get("avatarfull", ""),
                    profile_url=p.get("profileurl", f"https://steamcommunity.com/profiles/{steam_id}"),
                    personastate=p.get("personastate", 0),
                    gameid=p.get("gameid"),
                    gameextrainfo=p.get("gameextrainfo"),
                )
        return None

    async def get_owned_games(self, steam_id: str, include_played_free: bool = True) -> List[OwnedGame]:
        """Get list of owned games with playtime."""
        params = {
            "steamid": steam_id,
            "include_appinfo": "true",
            "include_played_free_games": "true" if include_played_free else "false",
        }
        data = await self._get("/IPlayerService/GetOwnedGames/v1/", params)
        games = []
        if data:
            for g in data.get("response", {}).get("games", []):
                games.append(OwnedGame(
                    appid=g.get("appid", 0),
                    name=g.get("name", "Unknown"),
                    playtime_forever=g.get("playtime_forever", 0),
                    playtime_2weeks=g.get("playtime_2weeks", 0),
                    img_icon_url=g.get("img_icon_url", ""),
                    img_logo_url=g.get("img_logo_url", ""),
                ))
        return games

    async def get_cs2_stats(self, steam_id: str) -> CS2Stats:
        """Get CS2 stats from Steam Web API (requires API key for private profiles)."""
        stats = CS2Stats()

        # Get CS2 global stats
        data = await self._get("/ISteamUserStats/GetUserStatsForGame/v2/", {
            "steamid": steam_id,
            "appid": CS2_APP_ID,
        })

        if data:
            playerstats = data.get("playerstats", {})
            stat_list = playerstats.get("stats", [])

            stat_map = {s["name"]: s["value"] for s in stat_list}

            stats.total_kills = stat_map.get("total_kills", 0)
            stats.total_deaths = stat_map.get("total_deaths", 0)
            stats.total_mvps = stat_map.get("total_mvps", 0)
            stats.total_wins = stat_map.get("total_wins", 0)
            stats.total_rounds_played = stat_map.get("total_rounds_played", 0)
            stats.headshot_kills = stat_map.get("total_kills_headshot", 0)
            stats.shots_fired = stat_map.get("total_shots_fired", 0)
            stats.shots_hit = stat_map.get("total_shots_hit", 0)

            # Favorite weapon
            weapon_stats = [
                (k.replace("total_kills_", ""), v)
                for k, v in stat_map.items()
                if k.startswith("total_kills_") and not k.endswith("_headshot")
            ]
            if weapon_stats:
                stats.favorite_weapon = max(weapon_stats, key=lambda x: x[1])[0].replace("_", " ").title()

        # Get recent matches from GetMatchHistory (requires API key)
        if self.api_key:
            match_data = await self._get("/IDOTA2Match_570/GetMatchHistory/v1/", {
                "steamid": steam_id,
                "key": self.api_key,
            })
            # Note: CS2 uses a different endpoint, but Valve hasn't officially documented it
            # This is a placeholder for future expansion

        return stats

    async def get_recently_played(self, steam_id: str, count: int = 10) -> List[OwnedGame]:
        """Get recently played games."""
        data = await self._get("/IPlayerService/GetRecentlyPlayedGames/v1/", {
            "steamid": steam_id,
            "count": count,
        })
        games = []
        if data:
            for g in data.get("response", {}).get("games", []):
                games.append(OwnedGame(
                    appid=g.get("appid", 0),
                    name=g.get("name", "Unknown"),
                    playtime_forever=g.get("playtime_forever", 0),
                    playtime_2weeks=g.get("playtime_2weeks", 0),
                    img_icon_url=g.get("img_icon_url", ""),
                    img_logo_url=g.get("img_logo_url", ""),
                ))
        return games

    async def get_friend_list(self, steam_id: str) -> List[str]:
        """Get friend list (requires API key, friends list must be public)."""
        data = await self._get("/ISteamUser/GetFriendList/v1/", {
            "steamid": steam_id,
            "relationship": "friend",
        })
        friends = []
        if data:
            for f in data.get("friendslist", {}).get("friends", []):
                friends.append(f.get("steamid"))
        return friends

    async def get_player_bans(self, steam_id: str) -> Dict:
        """Get VAC/ban status."""
        data = await self._get("/ISteamUser/GetPlayerBans/v1/", {
            "steamids": steam_id,
        })
        if data:
            bans = data.get("players", [])
            if bans:
                return bans[0]
        return {}

    async def get_global_achievements(self, appid: int = CS2_APP_ID) -> Dict[str, float]:
        """Get global achievement percentages for a game."""
        data = await self._get("/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/", {
            "gameid": appid,
        })
        if data:
            return {a["name"]: a["percent"] for a in data.get("achievementpercentages", {}).get("achievements", [])}
        return {}

    async def get_user_achievements(self, steam_id: str, appid: int = CS2_APP_ID) -> List[Dict]:
        """Get user's achievements for a game."""
        params = {"steamid": steam_id, "appid": appid}
        if self.api_key:
            params["key"] = self.api_key
        data = await self._get("/ISteamUserStats/GetPlayerAchievements/v1/", params)
        if data:
            return data.get("playerstats", {}).get("achievements", [])
        return []


async def format_playtime(minutes: int) -> str:
    """Format minutes into human-readable playtime."""
    hours = minutes // 60
    mins = minutes % 60
    if hours >= 1000:
        return f"{hours // 1000}k hrs"
    elif hours > 0:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    return f"{mins}m"


async def get_steam_api(api_key: Optional[str] = None) -> SteamAPI:
    """Factory function for SteamAPI."""
    return SteamAPI(api_key)
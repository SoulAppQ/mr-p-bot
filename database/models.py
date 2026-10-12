"""
Database models for MR P Discord Bot.
Uses SQLite with aiosqlite for async operations.
"""
import aiosqlite
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List
from pathlib import Path


@dataclass
class MatchRecord:
    """A match/session record."""
    id: Optional[int]
    guild_id: int
    user_id: int
    game: str
    result: str  # "win" or "loss"
    notes: Optional[str]
    created_at: datetime


@dataclass
class DebtRecord:
    """A debt/bet record between users."""
    id: Optional[int]
    guild_id: int
    debtor_id: int  # Who owes
    creditor_id: int  # Who is owed
    amount: str  # Description of what's owed (e.g., "pizza", "1v1 rematch")
    reason: str
    settled: bool
    created_at: datetime
    settled_at: Optional[datetime]


class Database:
    """Database manager for MR P bot."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._pool: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        """Initialize database connection and create tables."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._pool = await aiosqlite.connect(self.db_path)
        self._pool.row_factory = aiosqlite.Row
        await self._create_tables()
        await self._pool.commit()

    async def _create_tables(self):
        """Create all necessary tables."""
        # Match history table
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS match_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                result TEXT NOT NULL CHECK (result IN ('win', 'loss')),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_match_history_guild_user
            ON match_history(guild_id, user_id)
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_match_history_game
            ON match_history(game)
        """)

        # Debts/bets table
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                debtor_id INTEGER NOT NULL,
                creditor_id INTEGER NOT NULL,
                amount TEXT NOT NULL,
                reason TEXT NOT NULL,
                settled BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settled_at TIMESTAMP
            )
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_debts_guild_debtor
            ON debts(guild_id, debtor_id)
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_debts_guild_creditor
            ON debts(guild_id, creditor_id)
        """)

        # Starboard/Skullboard entries
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS starboard_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                original_message_id INTEGER NOT NULL,
                original_channel_id INTEGER NOT NULL,
                starboard_message_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                reaction_count INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(original_message_id, emoji)
            )
        """)

        # Voice channel ownership (for dynamic voice rooms)
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS voice_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                is_locked BOOLEAN DEFAULT FALSE,
                user_limit INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id)
            )
        """)

        # Bot persistent state
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS ava_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Steam profile links
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS steam_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                steam_id TEXT NOT NULL,
                vanity_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, user_id)
            )
        """)

        # Scheduled events
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                creator_name TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                scheduled_at TIMESTAMP NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER DEFAULT 0,
                notified INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Event RSVPs
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS event_rsvps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                status TEXT DEFAULT 'going',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_id, user_id)
            )
        """)

        # Name aliases — map a nickname/alias to a member's user_id
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS name_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                alias TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, alias)
            )
        """)

        # Chat log — ambient channel messages for context
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS chat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                message_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_log_guild_time
            ON chat_log(guild_id, created_at DESC)
        """)

        await self._pool.commit()

    async def close(self):
        """Close database connection."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ========== Match History ==========

    async def add_match(self, guild_id: int, user_id: int, game: str, result: str, notes: Optional[str] = None) -> int:
        cursor = await self._pool.execute(
            "INSERT INTO match_history (guild_id, user_id, game, result, notes) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, game.lower(), result.lower(), notes)
        )
        await self._pool.commit()
        return cursor.lastrowid

    async def get_user_stats(self, guild_id: int, user_id: int, game: Optional[str] = None) -> dict:
        query = "SELECT result, COUNT(*) as count FROM match_history WHERE guild_id = ? AND user_id = ?"
        params = [guild_id, user_id]
        if game:
            query += " AND game = ?"
            params.append(game.lower())
        query += " GROUP BY result"
        cursor = await self._pool.execute(query, params)
        rows = await cursor.fetchall()
        stats = {"wins": 0, "losses": 0, "total": 0}
        for row in rows:
            if row["result"] == "win":
                stats["wins"] = row["count"]
            elif row["result"] == "loss":
                stats["losses"] = row["count"]
        stats["total"] = stats["wins"] + stats["losses"]
        return stats

    async def get_leaderboard(self, guild_id: int, game: Optional[str] = None, limit: int = 10) -> List[dict]:
        query = """
            SELECT user_id,
                   SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) as losses,
                   COUNT(*) as total
            FROM match_history
            WHERE guild_id = ?
        """
        params = [guild_id]
        if game:
            query += " AND game = ?"
            params.append(game.lower())
        query += " GROUP BY user_id ORDER BY wins DESC, total DESC LIMIT ?"
        params.append(limit)
        cursor = await self._pool.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_recent_matches(self, guild_id: int, limit: int = 10) -> List[MatchRecord]:
        cursor = await self._pool.execute(
            "SELECT * FROM match_history WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?",
            (guild_id, limit)
        )
        rows = await cursor.fetchall()
        return [MatchRecord(**dict(row)) for row in rows]

    # ========== Debts ==========

    async def add_debt(self, guild_id: int, debtor_id: int, creditor_id: int, amount: str, reason: str) -> int:
        cursor = await self._pool.execute(
            "INSERT INTO debts (guild_id, debtor_id, creditor_id, amount, reason) VALUES (?, ?, ?, ?, ?)",
            (guild_id, debtor_id, creditor_id, amount, reason)
        )
        await self._pool.commit()
        return cursor.lastrowid

    async def get_debts(self, guild_id: int, user_id: Optional[int] = None) -> List[DebtRecord]:
        query = "SELECT * FROM debts WHERE guild_id = ?"
        params = [guild_id]
        if user_id:
            query += " AND (debtor_id = ? OR creditor_id = ?)"
            params.extend([user_id, user_id])
        query += " ORDER BY created_at DESC"
        cursor = await self._pool.execute(query, params)
        rows = await cursor.fetchall()
        return [DebtRecord(**dict(row)) for row in rows]

    async def settle_debt(self, debt_id: int, guild_id: int) -> bool:
        cursor = await self._pool.execute(
            "UPDATE debts SET settled = TRUE, settled_at = CURRENT_TIMESTAMP WHERE id = ? AND guild_id = ?",
            (debt_id, guild_id)
        )
        await self._pool.commit()
        return cursor.rowcount > 0

    # ========== Starboard ==========

    async def add_starboard_entry(self, guild_id: int, original_message_id: int,
                                   original_channel_id: int, starboard_message_id: int,
                                   emoji: str, reaction_count: int) -> int:
        cursor = await self._pool.execute(
            """INSERT INTO starboard_entries (guild_id, original_message_id, original_channel_id,
               starboard_message_id, emoji, reaction_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild_id, original_message_id, original_channel_id, starboard_message_id, emoji, reaction_count)
        )
        await self._pool.commit()
        return cursor.lastrowid

    async def get_starboard_entry(self, original_message_id: int, emoji: str) -> Optional[dict]:
        cursor = await self._pool.execute(
            "SELECT * FROM starboard_entries WHERE original_message_id = ? AND emoji = ?",
            (original_message_id, emoji)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_starboard_count(self, original_message_id: int, emoji: str, count: int) -> bool:
        cursor = await self._pool.execute(
            "UPDATE starboard_entries SET reaction_count = ? WHERE original_message_id = ? AND emoji = ?",
            (count, original_message_id, emoji)
        )
        await self._pool.commit()
        return cursor.rowcount > 0

    async def delete_starboard_entry(self, original_message_id: int, emoji: str) -> bool:
        cursor = await self._pool.execute(
            "DELETE FROM starboard_entries WHERE original_message_id = ? AND emoji = ?",
            (original_message_id, emoji)
        )
        await self._pool.commit()
        return cursor.rowcount > 0

    # ========== Voice Channels ==========

    async def register_voice_channel(self, guild_id: int, channel_id: int, owner_id: int) -> bool:
        try:
            await self._pool.execute(
                "INSERT INTO voice_channels (guild_id, channel_id, owner_id) VALUES (?, ?, ?)",
                (guild_id, channel_id, owner_id)
            )
            await self._pool.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def unregister_voice_channel(self, channel_id: int) -> bool:
        cursor = await self._pool.execute(
            "DELETE FROM voice_channels WHERE channel_id = ?",
            (channel_id,)
        )
        await self._pool.commit()
        return cursor.rowcount > 0

    async def get_voice_channel_owner(self, channel_id: int) -> Optional[int]:
        cursor = await self._pool.execute(
            "SELECT owner_id FROM voice_channels WHERE channel_id = ?",
            (channel_id,)
        )
        row = await cursor.fetchone()
        return row["owner_id"] if row else None

    async def get_voice_channel_by_owner(self, owner_id: int) -> Optional[int]:
        cursor = await self._pool.execute(
            "SELECT channel_id FROM voice_channels WHERE owner_id = ?",
            (owner_id,)
        )
        row = await cursor.fetchone()
        return row["channel_id"] if row else None

    async def set_voice_channel_lock(self, channel_id: int, locked: bool) -> bool:
        cursor = await self._pool.execute(
            "UPDATE voice_channels SET is_locked = ? WHERE channel_id = ?",
            (locked, channel_id)
        )
        await self._pool.commit()
        return cursor.rowcount > 0

    async def get_voice_channel_lock(self, channel_id: int) -> bool:
        cursor = await self._pool.execute(
            "SELECT is_locked FROM voice_channels WHERE channel_id = ?",
            (channel_id,)
        )
        row = await cursor.fetchone()
        return row["is_locked"] if row else False

    async def set_voice_channel_limit(self, channel_id: int, limit: int) -> bool:
        cursor = await self._pool.execute(
            "UPDATE voice_channels SET user_limit = ? WHERE channel_id = ?",
            (limit, channel_id)
        )
        await self._pool.commit()
        return cursor.rowcount > 0

    async def get_voice_channel_limit(self, channel_id: int) -> int:
        cursor = await self._pool.execute(
            "SELECT user_limit FROM voice_channels WHERE channel_id = ?",
            (channel_id,)
        )
        row = await cursor.fetchone()
        return row["user_limit"] if row else 0

    # ========== Bot State ==========

    async def get_ava_state(self, key: str) -> Optional[str]:
        cursor = await self._pool.execute("SELECT value FROM ava_state WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_ava_state(self, key: str, value: str):
        await self._pool.execute(
            "INSERT INTO ava_state (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (key, value)
        )
        await self._pool.commit()

    # ========== Steam Links ==========

    async def link_steam(self, guild_id: int, user_id: int, username: str, steam_id: str, vanity_url: str = ""):
        await self._pool.execute(
            "INSERT INTO steam_links (guild_id, user_id, username, steam_id, vanity_url) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
            "steam_id = excluded.steam_id, vanity_url = excluded.vanity_url, username = excluded.username",
            (guild_id, user_id, username, steam_id, vanity_url)
        )
        await self._pool.commit()

    async def get_steam_link(self, guild_id: int, user_id: int) -> Optional[dict]:
        cursor = await self._pool.execute(
            "SELECT * FROM steam_links WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_steam_links(self, guild_id: int) -> List[dict]:
        cursor = await self._pool.execute(
            "SELECT * FROM steam_links WHERE guild_id = ?",
            (guild_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ========== Name Aliases ==========

    async def add_name_alias(self, guild_id: int, user_id: int, alias: str):
        await self._pool.execute(
            "INSERT OR REPLACE INTO name_aliases (guild_id, user_id, alias) VALUES (?, ?, ?)",
            (guild_id, user_id, alias.lower().strip())
        )
        await self._pool.commit()

    async def get_name_aliases(self, guild_id: int) -> dict:
        cursor = await self._pool.execute(
            "SELECT user_id, alias FROM name_aliases WHERE guild_id = ?",
            (guild_id,)
        )
        rows = await cursor.fetchall()
        return {row["alias"].lower(): row["user_id"] for row in rows}

    # ========== Events ==========

    async def create_event(self, guild_id: int, creator_id: int, creator_name: str,
                           title: str, description: str, scheduled_at: str,
                           channel_id: int, message_id: int = 0) -> int:
        cursor = await self._pool.execute(
            """INSERT INTO events (guild_id, creator_id, creator_name, title, description,
               scheduled_at, channel_id, message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, creator_id, creator_name, title, description, scheduled_at, channel_id, message_id)
        )
        await self._pool.commit()
        return cursor.lastrowid

    async def get_upcoming_events(self, guild_id: int) -> List[dict]:
        cursor = await self._pool.execute(
            "SELECT * FROM events WHERE guild_id = ? AND scheduled_at > ? ORDER BY scheduled_at ASC",
            (guild_id, datetime.now(timezone.utc).isoformat())
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_event(self, event_id: int) -> Optional[dict]:
        cursor = await self._pool.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete_event(self, event_id: int, guild_id: int):
        await self._pool.execute("DELETE FROM event_rsvps WHERE event_id = ?", (event_id,))
        await self._pool.execute("DELETE FROM events WHERE id = ? AND guild_id = ?", (event_id, guild_id))
        await self._pool.commit()

    async def mark_event_notified(self, event_id: int):
        await self._pool.execute("UPDATE events SET notified = 1 WHERE id = ?", (event_id,))
        await self._pool.commit()

    async def set_event_message_id(self, event_id: int, message_id: int):
        await self._pool.execute("UPDATE events SET message_id = ? WHERE id = ?", (message_id, event_id))
        await self._pool.commit()

    # ========== Event RSVPs ==========

    async def rsvp_event(self, event_id: int, user_id: int, username: str, status: str):
        await self._pool.execute(
            "INSERT INTO event_rsvps (event_id, user_id, username, status) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(event_id, user_id) DO UPDATE SET status = excluded.status",
            (event_id, user_id, username, status)
        )
        await self._pool.commit()

    async def get_event_rsvps(self, event_id: int, status: str = "going") -> List[dict]:
        cursor = await self._pool.execute(
            "SELECT * FROM event_rsvps WHERE event_id = ? AND status = ?",
            (event_id, status)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_all_event_rsvps(self, event_id: int) -> List[dict]:
        cursor = await self._pool.execute(
            "SELECT * FROM event_rsvps WHERE event_id = ?",
            (event_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ========== Chat Log ==========

    async def log_chat(self, guild_id: int, channel_id: int, user_id: int,
                       username: str, message_text: str):
        await self._pool.execute(
            "INSERT INTO chat_log (guild_id, channel_id, user_id, username, message_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild_id, channel_id, user_id, username, message_text[:500])
        )
        await self._pool.commit()
        await self.prune_chat_log(guild_id, keep=1000)

    async def get_chat_log(self, guild_id: int, limit: int = 50,
                           channel_id: Optional[int] = None) -> List[dict]:
        if channel_id:
            cursor = await self._pool.execute(
                "SELECT * FROM chat_log WHERE guild_id = ? AND channel_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (guild_id, channel_id, limit)
            )
        else:
            cursor = await self._pool.execute(
                "SELECT * FROM chat_log WHERE guild_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (guild_id, limit)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_chat_log_since(self, guild_id: int, since: datetime) -> List[dict]:
        cursor = await self._pool.execute(
            "SELECT * FROM chat_log WHERE guild_id = ? AND created_at >= ? "
            "ORDER BY created_at ASC",
            (guild_id, since.isoformat())
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_chat_activity_stats(self, guild_id: int, since: datetime) -> dict:
        cursor = await self._pool.execute(
            "SELECT COUNT(*) as total_messages, "
            "COUNT(DISTINCT user_id) as unique_users, "
            "COUNT(DISTINCT channel_id) as active_channels "
            "FROM chat_log WHERE guild_id = ? AND created_at >= ?",
            (guild_id, since.isoformat())
        )
        row = await cursor.fetchone()

        cursor2 = await self._pool.execute(
            "SELECT username, COUNT(*) as msg_count FROM chat_log "
            "WHERE guild_id = ? AND created_at >= ? "
            "GROUP BY user_id ORDER BY msg_count DESC LIMIT 5",
            (guild_id, since.isoformat())
        )
        top_users = await cursor2.fetchall()

        return {
            "total_messages": row["total_messages"] if row else 0,
            "unique_users": row["unique_users"] if row else 0,
            "active_channels": row["active_channels"] if row else 0,
            "top_users": [(r["username"], r["msg_count"]) for r in top_users]
        }

    async def prune_chat_log(self, guild_id: int, keep: int = 1000):
        await self._pool.execute(
            "DELETE FROM chat_log WHERE guild_id = ? AND id NOT IN "
            "(SELECT id FROM chat_log WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?)",
            (guild_id, guild_id, keep)
        )
        await self._pool.commit()

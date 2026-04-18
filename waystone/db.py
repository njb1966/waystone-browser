"""Database connection and schema initialization."""

import aiosqlite
from pathlib import Path

DB_PATH = Path.home() / ".local" / "share" / "waystone" / "waystone.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookmarks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL DEFAULT '',
    url        TEXT    NOT NULL UNIQUE,
    folder     TEXT             DEFAULT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT    NOT NULL,
    title      TEXT             DEFAULT '',
    visited_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS gemini_certs (
    host         TEXT    NOT NULL,
    port         INTEGER NOT NULL DEFAULT 1965,
    fingerprint  TEXT    NOT NULL,
    first_seen_at INTEGER NOT NULL DEFAULT (unixepoch()),
    last_seen_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (host, port)
);
"""


class Database:
    def __init__(self):
        self._conn: aiosqlite.Connection | None = None

    async def connect(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(DB_PATH)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self):
        """Add columns introduced after initial release without dropping existing data."""
        async with self._conn.execute("PRAGMA table_info(bookmarks)") as cur:
            cols = {row["name"] for row in await cur.fetchall()}
        if "folder" not in cols:
            await self._conn.execute(
                "ALTER TABLE bookmarks ADD COLUMN folder TEXT DEFAULT NULL"
            )

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() has not been called")
        return self._conn

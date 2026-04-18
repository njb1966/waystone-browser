"""Append-only history with search."""

from .db import Database


class HistoryService:
    def __init__(self, db: Database):
        self._db = db

    async def record(self, url: str, title: str = "") -> None:
        await self._db.conn.execute(
            "INSERT INTO history (url, title) VALUES (?, ?)",
            (url, title or ""),
        )
        await self._db.conn.commit()

    async def list_recent(self, limit: int = 200) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT id, url, title, visited_at FROM history "
            "ORDER BY visited_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def search(self, query: str, limit: int = 100) -> list[dict]:
        pattern = f"%{query}%"
        async with self._db.conn.execute(
            "SELECT id, url, title, visited_at FROM history "
            "WHERE url LIKE ? OR title LIKE ? "
            "ORDER BY visited_at DESC LIMIT ?",
            (pattern, pattern, limit),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def clear(self) -> None:
        await self._db.conn.execute("DELETE FROM history")
        await self._db.conn.commit()

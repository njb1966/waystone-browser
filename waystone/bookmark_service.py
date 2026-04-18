"""CRUD operations for bookmarks, with optional folder support."""

from typing import Optional
from .db import Database


class BookmarkService:
    def __init__(self, db: Database):
        self._db = db

    async def add(self, url: str, title: str = "", folder: Optional[str] = None) -> None:
        await self._db.conn.execute(
            "INSERT INTO bookmarks (url, title, folder) VALUES (?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET title=excluded.title, "
            "folder=excluded.folder, updated_at=unixepoch()",
            (url, title, folder),
        )
        await self._db.conn.commit()

    async def remove(self, url: str) -> None:
        await self._db.conn.execute(
            "DELETE FROM bookmarks WHERE url = ?", (url,)
        )
        await self._db.conn.commit()

    async def is_bookmarked(self, url: str) -> bool:
        async with self._db.conn.execute(
            "SELECT 1 FROM bookmarks WHERE url = ?", (url,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def list_all(self) -> list[dict]:
        """Return all bookmarks ordered by folder name then newest-first."""
        async with self._db.conn.execute(
            "SELECT id, title, url, folder, created_at FROM bookmarks "
            "ORDER BY COALESCE(folder, '') ASC, created_at DESC"
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def list_folders(self) -> list[str]:
        """Return sorted list of distinct folder names (excludes NULL)."""
        async with self._db.conn.execute(
            "SELECT DISTINCT folder FROM bookmarks "
            "WHERE folder IS NOT NULL ORDER BY folder"
        ) as cursor:
            rows = await cursor.fetchall()
        return [row["folder"] for row in rows]

    async def set_folder(self, url: str, folder: Optional[str]) -> None:
        """Move a bookmark to a folder (or to Unfiled when folder is None)."""
        await self._db.conn.execute(
            "UPDATE bookmarks SET folder = ?, updated_at = unixepoch() WHERE url = ?",
            (folder, url),
        )
        await self._db.conn.commit()

    async def rename_folder(self, old_name: str, new_name: Optional[str]) -> None:
        """Rename a folder across all its bookmarks (pass None to move to Unfiled)."""
        await self._db.conn.execute(
            "UPDATE bookmarks SET folder = ?, updated_at = unixepoch() "
            "WHERE folder = ?",
            (new_name, old_name),
        )
        await self._db.conn.commit()

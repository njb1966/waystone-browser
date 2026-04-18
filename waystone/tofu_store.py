"""TOFU (Trust On First Use) certificate store for Gemini."""

from .db import Database


class TOFUStore:
    def __init__(self, db: Database):
        self._db = db

    async def check(self, host: str, port: int, fingerprint: str) -> str:
        """
        Returns:
          'trusted'  — known host, fingerprint matches
          'new'      — host not seen before
          'changed'  — host known, fingerprint differs
        """
        async with self._db.conn.execute(
            "SELECT fingerprint FROM gemini_certs WHERE host = ? AND port = ?",
            (host, port),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return "new"
        if row["fingerprint"] == fingerprint:
            return "trusted"
        return "changed"

    async def trust(self, host: str, port: int, fingerprint: str) -> None:
        """Insert or update the stored fingerprint for host:port."""
        await self._db.conn.execute(
            """
            INSERT INTO gemini_certs (host, port, fingerprint)
            VALUES (?, ?, ?)
            ON CONFLICT(host, port) DO UPDATE SET
                fingerprint   = excluded.fingerprint,
                last_seen_at  = unixepoch()
            """,
            (host, port, fingerprint),
        )
        await self._db.conn.commit()

    async def forget(self, host: str, port: int) -> None:
        """Remove a stored cert (for settings UI later)."""
        await self._db.conn.execute(
            "DELETE FROM gemini_certs WHERE host = ? AND port = ?",
            (host, port),
        )
        await self._db.conn.commit()

    async def list_all(self) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT host, port, fingerprint, first_seen_at, last_seen_at "
            "FROM gemini_certs ORDER BY host"
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

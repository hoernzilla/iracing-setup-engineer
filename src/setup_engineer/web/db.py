"""SQLite-Datenbank des Portals (eine Datei im Datenordner, keine Installation nötig)."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    discord_id   TEXT PRIMARY KEY,
    username     TEXT NOT NULL,
    display_name TEXT,
    avatar       TEXT,
    roles        TEXT,
    first_login  TEXT NOT NULL,
    last_login   TEXT NOT NULL,
    consent_at   TEXT
);
CREATE TABLE IF NOT EXISTS uploads (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(discord_id),
    filename      TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    size          INTEGER NOT NULL,
    uploaded_at   TEXT NOT NULL,
    test_type     TEXT NOT NULL,
    pair_id       TEXT,
    description   TEXT,
    feeling       TEXT,
    status        TEXT NOT NULL,
    error         TEXT,
    car           TEXT,
    track         TEXT,
    session_start TEXT,
    laps_total    INTEGER,
    laps_valid    INTEGER,
    best_lap_s    REAL,
    report_path   TEXT,
    ab_report_path TEXT,
    ab_summary    TEXT,
    analysis_version TEXT
);
CREATE INDEX IF NOT EXISTS uploads_user ON uploads(user_id);
CREATE INDEX IF NOT EXISTS uploads_sha ON uploads(user_id, sha256);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------- Nutzer
    def upsert_user(self, discord_id: str, username: str, display_name: str | None, avatar: str | None, roles: list[str]) -> None:
        t = now()
        with self._conn() as c:
            c.execute(
                """INSERT INTO users(discord_id, username, display_name, avatar, roles, first_login, last_login)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(discord_id) DO UPDATE SET username=excluded.username,
                     display_name=excluded.display_name, avatar=excluded.avatar, roles=excluded.roles,
                     last_login=excluded.last_login""",
                (discord_id, username, display_name, avatar, json.dumps(roles), t, t),
            )

    def get_user(self, discord_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM users WHERE discord_id=?", (discord_id,)).fetchone()
        return dict(r) if r else None

    def set_consent(self, discord_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET consent_at=? WHERE discord_id=?", (now(), discord_id))

    def users_with_stats(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT u.*, COUNT(up.id) AS uploads,
                          COALESCE(SUM(CASE WHEN up.status='fertig' THEN up.laps_valid END),0) AS laps,
                          COUNT(DISTINCT CASE WHEN up.ab_summary IS NOT NULL THEN COALESCE(up.pair_id, up.id) END) AS tests,
                          MAX(up.uploaded_at) AS last_upload
                   FROM users u LEFT JOIN uploads up ON up.user_id=u.discord_id
                   GROUP BY u.discord_id ORDER BY last_upload DESC NULLS LAST, u.last_login DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ Uploads
    def add_upload(self, row: dict[str, Any]) -> None:
        cols = ",".join(row)
        with self._conn() as c:
            c.execute(f"INSERT INTO uploads({cols}) VALUES({','.join('?' * len(row))})", tuple(row.values()))

    def update_upload(self, upload_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets = ",".join(f"{k}=?" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE uploads SET {sets} WHERE id=?", (*fields.values(), upload_id))

    def get_upload(self, upload_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
        return dict(r) if r else None

    def find_duplicate(self, user_id: str, sha256: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM uploads WHERE user_id=? AND sha256=?", (user_id, sha256)).fetchone()
        return dict(r) if r else None

    def uploads_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM uploads WHERE user_id=? ORDER BY uploaded_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def uploads_by_status(self, *statuses: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM uploads WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY uploaded_at",
                statuses,
            ).fetchall()
        return [dict(r) for r in rows]

    def pair_members(self, pair_id: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM uploads WHERE pair_id=?", (pair_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_upload(self, upload_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM uploads WHERE id=?", (upload_id,))

    # ---------------------------------------------------------- Datenlage
    def coverage(self) -> list[dict[str, Any]]:
        """Datenlage je Auto: Fahrer, Sessions, gewertete Runden, Tests."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT car,
                          COUNT(DISTINCT user_id) AS drivers,
                          COUNT(*) AS sessions,
                          COUNT(DISTINCT track) AS tracks,
                          COALESCE(SUM(laps_valid),0) AS laps,
                          COUNT(DISTINCT CASE WHEN ab_summary IS NOT NULL THEN COALESCE(pair_id, id) END) AS tests
                   FROM uploads WHERE status='fertig' AND car IS NOT NULL
                   GROUP BY car ORDER BY tests DESC, laps DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def totals(self) -> dict[str, int]:
        with self._conn() as c:
            r = c.execute(
                """SELECT COUNT(DISTINCT user_id) AS drivers, COUNT(*) AS sessions,
                          COALESCE(SUM(laps_valid),0) AS laps,
                          COUNT(DISTINCT CASE WHEN ab_summary IS NOT NULL THEN COALESCE(pair_id, id) END) AS tests
                   FROM uploads WHERE status='fertig'"""
            ).fetchone()
        return dict(r)

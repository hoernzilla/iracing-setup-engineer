"""SQLite-Datenbank des Portals (eine Datei im Datenordner, keine Installation nötig)."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS admin_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT NOT NULL,
    admin_id      TEXT,
    admin_name    TEXT,
    action        TEXT NOT NULL,
    target_user   TEXT,
    target_name   TEXT,
    target_upload TEXT,
    detail        TEXT
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
            self._migrate(c)

    @staticmethod
    def _migrate(c: sqlite3.Connection) -> None:
        """Spalten nachrüsten, die nach der ersten Version dazugekommen sind."""
        wanted = {
            "users": {
                "guidelines_version": "TEXT",
                "guidelines_at": "TEXT",
                "is_admin": "INTEGER NOT NULL DEFAULT 0",
                "admin_note": "TEXT",
                "banned_at": "TEXT",
                "banned_until": "TEXT",
                "ban_reason": "TEXT",
                "banned_by": "TEXT",
            },
            "uploads": {"next_test": "TEXT", "excluded_at": "TEXT", "excluded_reason": "TEXT", "excluded_by": "TEXT"},
        }
        for table, cols in wanted.items():
            have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

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

    def set_guidelines(self, discord_id: str, version: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE users SET guidelines_version=?, guidelines_at=? WHERE discord_id=?", (version, now(), discord_id)
            )

    def users_with_stats(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT u.*, COUNT(up.id) AS uploads,
                          COALESCE(SUM(CASE WHEN up.status='fertig' THEN up.laps_valid END),0) AS laps,
                          COUNT(DISTINCT CASE WHEN up.ab_summary IS NOT NULL THEN COALESCE(up.pair_id, up.id) END) AS tests,
                          COUNT(up.excluded_at) AS excluded,
                          COALESCE(SUM(up.size),0) AS bytes,
                          MAX(up.uploaded_at) AS last_upload
                   FROM users u LEFT JOIN uploads up ON up.user_id=u.discord_id
                   GROUP BY u.discord_id ORDER BY last_upload DESC NULLS LAST, u.last_login DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------- Verwaltung
    def ban_user(self, discord_id: str, reason: str, until: str | None, by: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE users SET banned_at=?, banned_until=?, ban_reason=?, banned_by=? WHERE discord_id=?",
                (now(), until, reason, by, discord_id),
            )

    def unban_user(self, discord_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE users SET banned_at=NULL, banned_until=NULL, ban_reason=NULL, banned_by=NULL WHERE discord_id=?",
                (discord_id,),
            )

    def set_user_admin(self, discord_id: str, flag: bool) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET is_admin=? WHERE discord_id=?", (1 if flag else 0, discord_id))

    def set_user_note(self, discord_id: str, note: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET admin_note=? WHERE discord_id=?", (note or None, discord_id))

    def reset_guidelines(self, discord_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET guidelines_version=NULL, guidelines_at=NULL WHERE discord_id=?", (discord_id,))

    def delete_user(self, discord_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM uploads WHERE user_id=?", (discord_id,))
            c.execute("DELETE FROM users WHERE discord_id=?", (discord_id,))

    def exclude_upload(self, upload_id: str, reason: str, by: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE uploads SET excluded_at=?, excluded_reason=?, excluded_by=? WHERE id=? AND excluded_at IS NULL",
                (now(), reason or None, by, upload_id),
            )

    def include_upload(self, upload_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE uploads SET excluded_at=NULL, excluded_reason=NULL, excluded_by=NULL WHERE id=?", (upload_id,))

    def all_uploads(self, status: str = "", user_id: str = "", car: str = "", excluded: str = "", q: str = "", limit: int = 500) -> list[dict[str, Any]]:
        where, args = [], []
        if status:
            where.append("up.status=?")
            args.append(status)
        if user_id:
            where.append("up.user_id=?")
            args.append(user_id)
        if car:
            where.append("up.car=?")
            args.append(car)
        if excluded == "ja":
            where.append("up.excluded_at IS NOT NULL")
        elif excluded == "nein":
            where.append("up.excluded_at IS NULL")
        if q:
            where.append("(up.filename LIKE ? OR u.username LIKE ? OR u.display_name LIKE ? OR up.track LIKE ? OR up.description LIKE ?)")
            args += [f"%{q}%"] * 5
        sql = (
            "SELECT up.*, u.username, u.display_name, u.banned_at FROM uploads up LEFT JOIN users u ON u.discord_id=up.user_id"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY up.uploaded_at DESC LIMIT ?"
        )
        with self._conn() as c:
            rows = c.execute(sql, (*args, limit)).fetchall()
        return [dict(r) for r in rows]

    def cars(self) -> list[str]:
        with self._conn() as c:
            return [r[0] for r in c.execute("SELECT DISTINCT car FROM uploads WHERE car IS NOT NULL ORDER BY car")]

    def admin_stats(self) -> dict[str, Any]:
        with self._conn() as c:
            u = c.execute(
                """SELECT COUNT(*) AS users,
                          SUM(CASE WHEN banned_at IS NOT NULL THEN 1 ELSE 0 END) AS banned,
                          SUM(CASE WHEN last_login >= ? THEN 1 ELSE 0 END) AS active7
                   FROM users""",
                ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds"),),
            ).fetchone()
            up = c.execute(
                """SELECT COUNT(*) AS uploads, COALESCE(SUM(size),0) AS bytes,
                          SUM(CASE WHEN excluded_at IS NOT NULL THEN 1 ELSE 0 END) AS excluded,
                          SUM(CASE WHEN status='fehler' THEN 1 ELSE 0 END) AS failed,
                          SUM(CASE WHEN status IN ('wartet','läuft') THEN 1 ELSE 0 END) AS queued
                   FROM uploads"""
            ).fetchone()
        return {**{k: (u[k] or 0) for k in u.keys()}, **{k: (up[k] or 0) for k in up.keys()}}

    # ------------------------------------------------------- Einstellungen
    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as c:
            r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r and r[0] is not None else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # ------------------------------------------------------------ Protokoll
    def log(self, admin: dict, action: str, target: dict | None = None, upload_id: str | None = None, detail: str = "") -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO admin_log(at, admin_id, admin_name, action, target_user, target_name, target_upload, detail)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    now(),
                    admin["discord_id"],
                    admin.get("display_name") or admin["username"],
                    action,
                    target["discord_id"] if target else None,
                    (target.get("display_name") or target["username"]) if target else None,
                    upload_id,
                    detail or None,
                ),
            )

    def log_entries(self, limit: int = 200, target_user: str = "") -> list[dict[str, Any]]:
        with self._conn() as c:
            if target_user:
                rows = c.execute("SELECT * FROM admin_log WHERE target_user=? ORDER BY id DESC LIMIT ?", (target_user, limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM admin_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
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

    def next_tests(self, user_id: str) -> list[dict[str, Any]]:
        """Neuester Testvorschlag je Auto und Strecke."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT car, track, next_test, MAX(COALESCE(session_start, uploaded_at)) AS seen
                   FROM uploads WHERE user_id=? AND status='fertig' AND next_test IS NOT NULL
                   GROUP BY car, track ORDER BY seen DESC LIMIT 3""",
                (user_id,),
            ).fetchall()
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
                   FROM uploads WHERE status='fertig' AND car IS NOT NULL AND excluded_at IS NULL
                   GROUP BY car ORDER BY tests DESC, laps DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def totals(self) -> dict[str, int]:
        with self._conn() as c:
            r = c.execute(
                """SELECT COUNT(DISTINCT user_id) AS drivers, COUNT(*) AS sessions,
                          COALESCE(SUM(laps_valid),0) AS laps,
                          COUNT(DISTINCT CASE WHEN ab_summary IS NOT NULL THEN COALESCE(pair_id, id) END) AS tests
                   FROM uploads WHERE status='fertig' AND excluded_at IS NULL"""
            ).fetchone()
        return dict(r)

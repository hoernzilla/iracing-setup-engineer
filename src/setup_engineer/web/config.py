"""Konfiguration des Community-Portals.

Werte kommen aus der Datei `portal.env` im Projektordner (siehe portal.env.example)
und können durch Umgebungsvariablen überschrieben werden.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Eigener Port statt 80/443, damit das Portal bei einem Port-Scan nicht als Standard-Webserver auffällt
DEFAULT_PORT = 29630


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "ja", "yes", "on")


@dataclass
class Settings:
    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_redirect_uri: str = f"http://localhost:{DEFAULT_PORT}/auth/callback"
    discord_guild_id: str = ""
    discord_required_role_ids: set[str] = field(default_factory=set)  # leer = alle Server-Mitglieder
    admin_discord_ids: set[str] = field(default_factory=set)
    community_name: str = "unsere Community"
    operator_name: str = ""  # Verantwortlicher für Datenschutzerklärung
    operator_contact: str = ""  # E-Mail oder Discord-Name für Anfragen
    data_dir: Path = PROJECT_ROOT / "portal-data"
    max_upload_mb: int = 400
    max_files_per_upload: int = 10
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    https_only: bool = False  # True, sobald das Portal über HTTPS erreichbar ist
    session_secret: str = ""
    dev_login: bool = False  # nur zum lokalen Testen ohne Discord
    timezone: str = "Europe/Berlin"  # Anzeige von Datum und Uhrzeit (gespeichert wird UTC)
    discord_api_base: str = "https://discord.com/api/v10"
    discord_authorize_url: str = "https://discord.com/oauth2/authorize"

    @property
    def discord_configured(self) -> bool:
        return bool(self.discord_client_id and self.discord_client_secret and self.discord_guild_id)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "portal.sqlite3"

    @property
    def history_path(self) -> Path:
        return self.data_dir / "community-history.json"


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    path = Path(env_file) if env_file else Path(os.environ.get("PORTAL_ENV", PROJECT_ROOT / "portal.env"))
    raw = _read_env_file(path)
    raw.update({k: v for k, v in os.environ.items() if k.startswith(("DISCORD_", "PORTAL_"))})

    def get(key: str, default: str = "") -> str:
        value = raw.get(key, "")
        return value if value != "" else default  # leere Einträge = Standardwert

    def id_set(key: str) -> set[str]:
        return {x.strip() for x in get(key).replace(";", ",").split(",") if x.strip()}

    s = Settings(
        discord_client_id=get("DISCORD_CLIENT_ID"),
        discord_client_secret=get("DISCORD_CLIENT_SECRET"),
        discord_redirect_uri=get("DISCORD_REDIRECT_URI", Settings.discord_redirect_uri),
        discord_guild_id=get("DISCORD_GUILD_ID"),
        discord_required_role_ids=id_set("DISCORD_REQUIRED_ROLE_IDS"),
        admin_discord_ids=id_set("PORTAL_ADMIN_DISCORD_IDS"),
        community_name=get("PORTAL_COMMUNITY_NAME", Settings.community_name),
        operator_name=get("PORTAL_OPERATOR_NAME"),
        operator_contact=get("PORTAL_OPERATOR_CONTACT"),
        timezone=get("PORTAL_TIMEZONE", Settings.timezone) or Settings.timezone,
        data_dir=Path(get("PORTAL_DATA_DIR", str(Settings.data_dir))),
        max_upload_mb=int(get("PORTAL_MAX_UPLOAD_MB", "400")),
        host=get("PORTAL_HOST", "127.0.0.1"),
        port=int(get("PORTAL_PORT", str(DEFAULT_PORT))),
        https_only=_bool(get("PORTAL_HTTPS_ONLY"), False),
        session_secret=get("PORTAL_SESSION_SECRET"),
        dev_login=_bool(get("PORTAL_DEV_LOGIN"), False),
        discord_api_base=get("DISCORD_API_BASE", Settings.discord_api_base),
        discord_authorize_url=get("DISCORD_AUTHORIZE_URL", Settings.discord_authorize_url),
    )
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.uploads_dir.mkdir(parents=True, exist_ok=True)
    s.reports_dir.mkdir(parents=True, exist_ok=True)
    if not s.session_secret:
        # Geheimnis einmalig erzeugen und im Datenordner aufbewahren (übersteht Neustarts)
        key_file = s.data_dir / "session.key"
        if not key_file.exists():
            key_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        s.session_secret = key_file.read_text(encoding="utf-8").strip()
    return s

"""Discord-Anmeldung (OAuth2) und Prüfung der Server-Mitgliedschaft.

Ablauf
1. Nutzer klickt „Mit Discord anmelden“ -> Weiterleitung zu Discord
2. Discord leitet mit einem einmaligen Code zurück
3. Server tauscht den Code gegen ein Zugangstoken (nur serverseitig, mit Client-Secret)
4. Mit dem Token: Nutzerprofil + Mitgliedschaft auf DEM Community-Server abfragen
   (Scope guilds.members.read – liefert Spitzname und Rollen, nur für diesen Server)

Es werden nur die Scopes `identify` und `guilds.members.read` angefragt – keine
E-Mail-Adresse, keine Liste aller Server des Nutzers.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .config import Settings

SCOPES = "identify guilds.members.read"
USER_AGENT = "SetupEngineerPortal (https://github.com/hoernzilla/iracing-setup-engineer, 0.4)"


class DiscordError(RuntimeError):
    pass


@dataclass
class DiscordProfile:
    id: str
    username: str
    display_name: str
    avatar_url: str | None
    is_member: bool
    roles: list[str]


def authorize_url(s: Settings, state: str) -> str:
    q = urllib.parse.urlencode(
        {
            "client_id": s.discord_client_id,
            "redirect_uri": s.discord_redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "prompt": "none",
        }
    )
    return f"{s.discord_authorize_url}?{q}"


def _request(url: str, *, data: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except ValueError:
            payload = {}
        return e.code, payload
    except (urllib.error.URLError, TimeoutError) as e:
        raise DiscordError(f"Discord nicht erreichbar: {e}") from e


def exchange_code(s: Settings, code: str) -> str:
    status, payload = _request(
        f"{s.discord_api_base}/oauth2/token",
        data={
            "client_id": s.discord_client_id,
            "client_secret": s.discord_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": s.discord_redirect_uri,
        },
    )
    if status != 200 or "access_token" not in payload:
        raise DiscordError(f"Anmeldung bei Discord fehlgeschlagen ({status}: {payload.get('error_description') or payload.get('error') or 'unbekannt'})")
    return str(payload["access_token"])


def _avatar(user_id: str, avatar: str | None, guild_id: str | None = None, member_avatar: str | None = None) -> str | None:
    if member_avatar and guild_id:
        return f"https://cdn.discordapp.com/guilds/{guild_id}/users/{user_id}/avatars/{member_avatar}.png?size=96"
    if avatar:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=96"
    return None


def fetch_profile(s: Settings, token: str) -> DiscordProfile:
    status, user = _request(f"{s.discord_api_base}/users/@me", token=token)
    if status != 200 or "id" not in user:
        raise DiscordError(f"Discord-Profil konnte nicht gelesen werden ({status})")
    uid = str(user["id"])
    status, member = _request(f"{s.discord_api_base}/users/@me/guilds/{s.discord_guild_id}/member", token=token)
    is_member = status == 200 and isinstance(member, dict) and "roles" in member
    if status not in (200, 404) and not is_member:
        raise DiscordError(f"Mitgliedschaft konnte nicht geprüft werden ({status})")
    display = (member.get("nick") if is_member else None) or user.get("global_name") or user.get("username")
    return DiscordProfile(
        id=uid,
        username=str(user.get("username", uid)),
        display_name=str(display),
        avatar_url=_avatar(uid, user.get("avatar"), s.discord_guild_id, member.get("avatar") if is_member else None),
        is_member=is_member,
        roles=[str(r) for r in member.get("roles", [])] if is_member else [],
    )


def has_required_role(s: Settings, profile: DiscordProfile) -> bool:
    if not s.discord_required_role_ids:
        return True
    return bool(s.discord_required_role_ids & set(profile.roles))

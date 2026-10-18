"""Community-Portal: Anmeldung über Discord, Upload von iRacing-Telemetrie, Auswertung."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import markdown as md
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .. import __version__
from ..classes import GT3_EXCLUDE, GT3_MARKER, GTP_MARKERS
from ..ibt import IbtError, IbtFile
from ..recommend.history import History
from . import discord, progress, retention
from .config import Settings, load_settings
from .db import Database, now
from .worker import DONE, FAILED, QUEUED, Worker, report_text

log = logging.getLogger("portal")
HERE = Path(__file__).resolve().parent
CHUNK = 1024 * 1024
TEST_TYPES = {
    "normal": "Normale Runs",
    "aba": "A-B-A-Test im Auto",
    "garage": "Garagen-Test (drei Runs: A, B, A)",
    "archiv": "Archiv (Altdaten)",
}
# Stand der ersten Bestätigung – bleibt fest. Erneut bestätigen müssen alle nur, wenn ein Admin das in der
# Verwaltung auslöst (Einstellung guidelines_round); Text-Änderungen am Leitfaden allein lösen nichts aus.
GUIDELINES_VERSION = "2026-10-15"
# Ziele aus der Datenplanung: Stufe 1 ≈ 30 Tests, Stufe 2 ≈ 70 Tests je Auto
GOAL_STAGE1, GOAL_STAGE2 = 30, 70


def _hero_trace() -> dict:
    data = json.loads((HERE / "hero_trace.json").read_text(encoding="utf-8"))
    pts = data["points"]
    vmin, vmax = 80.0, 320.0
    w, h = 1000.0, 260.0

    def xy(p: float, v: float) -> tuple[float, float]:
        return p * w, h - (v - vmin) / (vmax - vmin) * h

    coords = [xy(p, v) for p, v in pts]
    data["path"] = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    data["area"] = data["path"] + f" L{w:.0f},{h:.0f} L0,{h:.0f} Z"
    prev = None
    for c in data["corners"]:
        c["x"], c["y"] = xy(c["pct"], c["kmh"])
        # auf schmalen Bildschirmen: Beschriftung weglassen, wenn die Kurve zu dicht an der vorigen liegt
        c["tight"] = prev is not None and c["pct"] - prev < 0.06
        if not c["tight"]:
            prev = c["pct"]
    m, s = divmod(data["lap"], 60)
    data["lap_text"] = f"{int(m)}:{s:06.3f}"
    return data


def fmt_lap(sec: float | None) -> str:
    if sec is None:
        return "–"
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:06.3f}"


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "–"
    d = iso[:16].replace("T", " ")
    y, mo, rest = d[:4], d[5:7], d[8:]
    return f"{rest[:2]}.{mo}.{y} {rest[3:]}" if len(rest) >= 8 else d


def safe_report_html(text: str) -> str:
    """Markdown -> HTML. Inhalte stammen teils aus der hochgeladenen Datei -> alles escapen,
    keine Links/Bilder zulassen."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = md.markdown(escaped, extensions=["tables"])
    html = re.sub(r"<a\b[^>]*>", "", html).replace("</a>", "")
    html = re.sub(r"<img\b[^>]*>", "", html)
    return html


def create_app(settings: Settings | None = None) -> Starlette:
    s = settings or load_settings()
    db = Database(s.db_path)
    worker = Worker(s, db)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["lap"] = fmt_lap
    templates.env.filters["datum"] = fmt_date
    templates.env.globals.update(
        community=s.community_name,
        operator_name=s.operator_name,
        operator_contact=s.operator_contact,
        version=__version__,
        test_types=TEST_TYPES,
    )
    hero = _hero_trace()

    # ------------------------------------------------------------ Hilfen
    def current_user(request: Request) -> dict | None:
        uid = request.session.get("uid")
        return db.get_user(uid) if uid else None

    def is_banned(user: dict | None) -> bool:
        if not user or not user.get("banned_at"):
            return False
        until = user.get("banned_until")
        if until and until <= now():
            db.unban_user(user["discord_id"])  # Befristung abgelaufen
            user["banned_at"] = None
            return False
        return True

    def is_owner(user: dict | None) -> bool:
        """Haupt-Admin aus portal.env – kann über die Oberfläche nicht gesperrt oder entfernt werden."""
        return bool(user and user["discord_id"] in s.admin_discord_ids)

    def is_admin(user: dict | None) -> bool:
        return bool(user and (is_owner(user) or user.get("is_admin")) and not is_banned(user))

    def guidelines_version() -> str:
        rnd = db.get_setting("guidelines_round", "0")
        return GUIDELINES_VERSION if rnd in ("", "0") else f"{GUIDELINES_VERSION}.{rnd}"

    def ban_message(request: Request, user: dict) -> Response:
        until = f" bis {fmt_date(user['banned_until'])}" if user.get("banned_until") else ""
        reason = f" Grund: {user['ban_reason'].rstrip('.')}." if user.get("ban_reason") else ""
        return message(
            request,
            "Zugang gesperrt",
            f"Dein Zugang zum Portal ist{until} gesperrt.{reason} Bei Fragen meld dich bei den Admins im Discord.",
            403,
        )

    def csrf_token(request: Request) -> str:
        tok = request.session.get("csrf")
        if not tok:
            tok = secrets.token_urlsafe(24)
            request.session["csrf"] = tok
        return tok

    def csrf_ok(request: Request, sent: str | None) -> bool:
        tok = request.session.get("csrf")
        return bool(tok and sent and secrets.compare_digest(tok, sent))

    def render(request: Request, name: str, status_code: int = 200, **ctx) -> Response:
        user = current_user(request)
        ctx.update(
            request=request,
            user=user,
            admin=is_admin(user),
            csrf=csrf_token(request),
            announcement=db.get_setting("announcement"),
            max_upload_mb=max_mb(),
            max_files=max_files(),
        )
        return templates.TemplateResponse(request, name, ctx, status_code=status_code)

    def message(request: Request, title: str, text: str, status_code: int = 200, action: tuple[str, str] | None = None) -> Response:
        return render(request, "message.html", status_code=status_code, title=title, text=text, action=action)

    def guidelines_ok(user: dict | None) -> bool:
        """Einmal bestätigt reicht – bis ein Admin eine neue Runde auslöst. Gezählt wird nur die Runde
        (Teil nach dem Punkt), damit auch ältere gespeicherte Stände gültig bleiben."""
        stored = (user or {}).get("guidelines_version") or ""
        if not stored:
            return False
        rnd = lambda v: int(v.split(".", 1)[1]) if "." in v and v.split(".", 1)[1].isdigit() else 0  # noqa: E731
        return rnd(stored) >= rnd(guidelines_version())

    def require_user(request: Request) -> dict | Response:
        user = current_user(request)
        if user is None:
            return RedirectResponse("/", status_code=303)
        if is_banned(user):
            return ban_message(request, user)
        if not user["consent_at"]:
            return RedirectResponse("/einwilligung", status_code=303)
        return user

    def require_admin(request: Request) -> dict | Response:
        user = require_user(request)
        if isinstance(user, Response):
            return user
        if not is_admin(user):
            return message(request, "Kein Zugriff", "Diese Seite ist nur für die Projekt-Admins.", 403)
        return user

    # ----------------------------------------------------------- Seiten
    async def landing(request: Request) -> Response:
        user = current_user(request)
        data = await asyncio.to_thread(progress.build, db, s.history_path, GOAL_STAGE1, GOAL_STAGE2)
        return render(
            request,
            "landing.html",
            hero=hero,
            p=data,
            phase=next((ph for ph in data["phases"] if ph["state"] == "aktiv"), data["phases"][-1]),
            next_tests=db.next_tests(user["discord_id"]) if user and user.get("consent_at") else [],
            discord_ready=s.discord_configured,
        )

    async def project(request: Request) -> Response:
        return render(
            request,
            "projekt.html",
            totals=db.totals(),
            coverage=db.coverage(),
            goal1=GOAL_STAGE1,
            goal2=GOAL_STAGE2,
            discord_ready=s.discord_configured,
        )

    async def login(request: Request) -> Response:
        if not s.discord_configured:
            return message(
                request,
                "Discord-Anmeldung noch nicht eingerichtet",
                "Im Server fehlen noch die Discord-Zugangsdaten (portal.env). Die Einrichtung ist in PORTAL.md beschrieben.",
                status_code=503,
            )
        state = secrets.token_urlsafe(24)
        request.session["oauth_state"] = state
        return RedirectResponse(discord.authorize_url(s, state), status_code=303)

    async def callback(request: Request) -> Response:
        if request.query_params.get("error"):
            return message(request, "Anmeldung abgebrochen", "Die Anmeldung bei Discord wurde nicht abgeschlossen.", action=("/", "Zur Startseite"))
        state, code = request.query_params.get("state"), request.query_params.get("code")
        expected = request.session.pop("oauth_state", None)
        if not code or not state or not expected or not secrets.compare_digest(state, expected):
            return message(request, "Anmeldung abgelaufen", "Der Anmeldevorgang ist abgelaufen oder ungültig. Bitte noch einmal anmelden.", 400, ("/login", "Erneut anmelden"))
        try:
            token = await asyncio.to_thread(discord.exchange_code, s, code)
            profile = await asyncio.to_thread(discord.fetch_profile, s, token)
        except discord.DiscordError as e:
            log.warning("Discord-Anmeldung fehlgeschlagen: %s", e)
            return message(request, "Discord hat nicht geantwortet", f"{e}. Bitte in ein paar Minuten erneut versuchen.", 502, ("/login", "Erneut anmelden"))
        if not profile.is_member:
            return message(
                request,
                "Nur für Mitglieder",
                f"Das Portal ist für Mitglieder von {s.community_name} auf Discord. Dein Konto „{profile.username}“ ist dort nicht Mitglied.",
                403,
            )
        if not discord.has_required_role(s, profile):
            return message(
                request,
                "Noch nicht freigeschaltet",
                "Du bist Mitglied, hast aber noch nicht die Rolle für das Telemetrie-Projekt. Melde dich bei den Admins im Discord.",
                403,
            )
        db.upsert_user(profile.id, profile.username, profile.display_name, profile.avatar_url, profile.roles)
        known = db.get_user(profile.id)
        if is_banned(known):
            request.session.clear()
            return ban_message(request, known)
        request.session.clear()
        request.session["uid"] = profile.id
        user = db.get_user(profile.id)
        return RedirectResponse("/meine-daten" if user and user["consent_at"] else "/einwilligung", status_code=303)

    async def dev_login(request: Request) -> Response:
        client = request.client.host if request.client else ""
        if not s.dev_login or client not in ("127.0.0.1", "::1", "localhost", "testclient"):
            return PlainTextResponse("Nicht verfügbar", status_code=404)
        uid = request.query_params.get("id", "100000000000000001")
        name = request.query_params.get("name", "Testfahrer")
        db.upsert_user(uid, name.lower(), name, None, [])
        request.session.clear()
        request.session["uid"] = uid
        return RedirectResponse("/meine-daten", status_code=303)

    async def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    async def consent(request: Request) -> Response:
        user = current_user(request)
        if user is None:
            return RedirectResponse("/", status_code=303)
        if request.method == "POST":
            form = await request.form()
            if not csrf_ok(request, form.get("csrf")):
                return message(request, "Sitzung abgelaufen", "Bitte die Seite neu laden.", 400)
            if form.get("zustimmung") == "ja":
                db.set_consent(user["discord_id"])
                return RedirectResponse("/meine-daten", status_code=303)
            return render(request, "consent.html", missing=True)
        return render(request, "consent.html", missing=False)

    async def dashboard(request: Request) -> Response:
        user = require_user(request)
        if isinstance(user, Response):
            return user
        uploads = db.uploads_for_user(user["discord_id"])
        rcfg = retention.config(db)
        for u in uploads:
            u["ab"] = json.loads(u["ab_summary"]) if u["ab_summary"] else None
            u["keep"] = retention.status(u, rcfg)
        return render(
            request,
            "dashboard.html",
            uploads=uploads,
            coverage=db.coverage(),
            goal1=GOAL_STAGE1,
            goal2=GOAL_STAGE2,
            guidelines_ok=guidelines_ok(user),
            guidelines_renewed=bool(user.get("guidelines_version")) and not guidelines_ok(user),
            next_tests=db.next_tests(user["discord_id"]),
            retention_cfg=rcfg,
            urgent=[u for u in uploads if u["keep"]["kind"] == "frist"],
            paused=uploads_paused(user),
            pause_message=db.get_setting("pause_message"),
        )

    def archive_open(user: dict | None) -> bool:
        return db.get_setting("archive_open", "1") == "1" or is_admin(user)

    async def archive_page(request: Request) -> Response:
        user = require_user(request)
        if isinstance(user, Response):
            return user
        rows = [r for r in db.uploads_for_user(user["discord_id"]) if r["test_type"] == "archiv"]
        tests = {r["pair_id"] or r["id"] for r in rows if r["ab_summary"] and not r["excluded_at"]}
        stats = {
            "files": len(rows),
            "used": sum(1 for r in rows if r["status"] == DONE and not r["excluded_at"]),
            "skipped": sum(1 for r in rows if r["excluded_at"]),
            "running": sum(1 for r in rows if r["status"] in (QUEUED, "läuft")),
            "tests": len(tests),
        }
        reasons: dict[str, int] = {}
        for r in rows:
            if r["excluded_at"]:
                key = (r["excluded_reason"] or "aussortiert").removeprefix("Archiv: ")
                reasons[key] = reasons.get(key, 0) + 1
        return render(
            request,
            "archiv.html",
            open=archive_open(user),
            paused=uploads_paused(user),
            stats=stats,
            reasons=sorted(reasons.items(), key=lambda x: -x[1]),
            markers={"gtp": list(GTP_MARKERS), "gt3": GT3_MARKER, "gt3_exclude": list(GT3_EXCLUDE)},
        )

    async def download_script(request: Request) -> Response:
        data = (HERE / "static" / "Telemetrie-Pruefen.bat").read_bytes()
        return Response(data, media_type="application/octet-stream",
                        headers={"Content-Disposition": 'attachment; filename="Telemetrie-Pruefen.bat"'})

    def max_mb() -> int:
        """Größenlimit pro Datei: Einstellung aus der Verwaltung, sonst portal.env."""
        v = db.get_setting("max_upload_mb")
        return int(v) if v.isdigit() and int(v) > 0 else s.max_upload_mb

    def max_files() -> int:
        v = db.get_setting("max_files")
        return int(v) if v.isdigit() and int(v) > 0 else s.max_files_per_upload

    def uploads_paused(user: dict | None) -> bool:
        return db.get_setting("uploads_paused") == "1" and not is_admin(user)

    async def progress_page(request: Request) -> Response:
        data = await asyncio.to_thread(progress.build, db, s.history_path, GOAL_STAGE1, GOAL_STAGE2)
        members = sum(1 for p in db.users_with_stats() if p["consent_at"] and not p["banned_at"])
        return render(request, "fortschritt.html", p=data, members=members)

    async def guidelines(request: Request) -> Response:
        return render(request, "leitfaden.html")

    async def guidelines_confirm(request: Request) -> Response:
        user = require_user(request)
        if isinstance(user, Response):
            return user
        form = await request.form()
        if not csrf_ok(request, form.get("csrf")):
            return message(request, "Sitzung abgelaufen", "Bitte die Seite neu laden.", 400)
        if form.get("gelesen") != "ja":
            return RedirectResponse("/meine-daten?leitfaden=fehlt#leitfaden", status_code=303)
        db.set_guidelines(user["discord_id"], guidelines_version())
        return RedirectResponse("/meine-daten#upload", status_code=303)

    async def report(request: Request) -> Response:
        user = require_user(request)
        if isinstance(user, Response):
            return user
        row = db.get_upload(request.path_params["upload_id"])
        if row is None or (row["user_id"] != user["discord_id"] and not is_admin(user)):
            return message(request, "Nicht gefunden", "Diese Auswertung gibt es nicht oder sie gehört zu einem anderen Konto.", 404)
        kind = request.path_params.get("kind", "analyse")
        text = report_text(row["ab_report_path"] if kind == "vergleich" else row["report_path"])
        if text is None:
            return message(request, "Noch nicht fertig", "Die Auswertung läuft noch. Die Seite „Meine Daten“ zeigt den Stand.", 404, ("/meine-daten", "Zu meinen Daten"))
        return render(request, "report.html", row=row, kind=kind, html=safe_report_html(text))

    async def delete_upload(request: Request) -> Response:
        user = require_user(request)
        if isinstance(user, Response):
            return user
        form = await request.form()
        if not csrf_ok(request, form.get("csrf")):
            return message(request, "Sitzung abgelaufen", "Bitte die Seite neu laden.", 400)
        row = db.get_upload(request.path_params["upload_id"])
        if row is None or row["user_id"] != user["discord_id"]:
            return message(request, "Nicht gefunden", "Diese Datei gibt es nicht.", 404)
        _remove_upload_files(s, row)
        db.delete_upload(row["id"])
        return RedirectResponse("/meine-daten", status_code=303)

    # ------------------------------------------------------- Verwaltung
    def person_view(p: dict) -> dict:
        p = dict(p)
        p["banned"] = is_banned(p)
        p["owner"] = is_owner(p)
        p["is_admin_any"] = p["owner"] or bool(p.get("is_admin"))
        p["guide_ok"] = guidelines_ok(p)
        return p

    def upload_view(u: dict) -> dict:
        u = dict(u)
        u["ab"] = json.loads(u["ab_summary"]) if u.get("ab_summary") else None
        return u

    async def admin_home(request: Request) -> Response:
        user = require_admin(request)
        if isinstance(user, Response):
            return user
        recent = [upload_view(u) for u in db.all_uploads(limit=8)]
        return render(
            request,
            "admin/uebersicht.html",
            section="uebersicht",
            stats=db.admin_stats(),
            totals=db.totals(),
            coverage=db.coverage(),
            goal1=GOAL_STAGE1,
            goal2=GOAL_STAGE2,
            failed=[upload_view(u) for u in db.all_uploads(status=FAILED, limit=50)],
            recent=recent,
            log=db.log_entries(limit=8),
            paused=db.get_setting("uploads_paused") == "1",
            store=retention.overview(db, s.data_dir),
        )

    async def admin_people(request: Request) -> Response:
        user = require_admin(request)
        if isinstance(user, Response):
            return user
        q = request.query_params.get("q", "").strip().lower()
        filt = request.query_params.get("filter", "")
        people = [person_view(p) for p in db.users_with_stats()]
        if q:
            people = [p for p in people if q in (p["username"] or "").lower() or q in (p["display_name"] or "").lower() or q in p["discord_id"]]
        if filt == "gesperrt":
            people = [p for p in people if p["banned"]]
        elif filt == "admins":
            people = [p for p in people if p["is_admin_any"]]
        elif filt == "ohne-upload":
            people = [p for p in people if not p["uploads"]]
        return render(request, "admin/teilnehmer.html", section="teilnehmer", people=people, q=q, filt=filt)

    async def admin_person(request: Request) -> Response:
        user = require_admin(request)
        if isinstance(user, Response):
            return user
        uid = request.path_params["uid"]
        row = next((p for p in db.users_with_stats() if p["discord_id"] == uid), None)
        if row is None:
            return message(request, "Nicht gefunden", "Diesen Teilnehmer gibt es nicht (mehr).", 404, ("/admin/teilnehmer", "Zu den Teilnehmern"))
        return render(
            request,
            "admin/person.html",
            section="teilnehmer",
            p=person_view(row),
            uploads=[upload_view(u) for u in db.all_uploads(user_id=uid)],
            log=db.log_entries(limit=50, target_user=uid),
            self_view=uid == user["discord_id"],
        )

    async def admin_uploads(request: Request) -> Response:
        user = require_admin(request)
        if isinstance(user, Response):
            return user
        qp = request.query_params
        f = {k: qp.get(k, "").strip() for k in ("status", "car", "excluded", "q")}
        rows = [upload_view(u) for u in db.all_uploads(**f, limit=500)]
        return render(request, "admin/uploads.html", section="uploads", uploads=rows, f=f, cars=db.cars(), statuses=[QUEUED, "läuft", DONE, FAILED])

    async def admin_log(request: Request) -> Response:
        user = require_admin(request)
        if isinstance(user, Response):
            return user
        return render(request, "admin/protokoll.html", section="protokoll", log=db.log_entries(limit=500))

    async def admin_settings(request: Request) -> Response:
        user = require_admin(request)
        if isinstance(user, Response):
            return user
        return render(
            request,
            "admin/einstellungen.html",
            section="einstellungen",
            announcement=db.get_setting("announcement"),
            paused=db.get_setting("uploads_paused") == "1",
            pause_message=db.get_setting("pause_message"),
            archive_is_open=db.get_setting("archive_open", "1") == "1",
            env_max_mb=s.max_upload_mb,
            store=retention.overview(db, s.data_dir),
            env_max_files=s.max_files_per_upload,
            guide_version=guidelines_version(),
            guide_confirmed=sum(1 for p in db.users_with_stats() if guidelines_ok(p)),
            owners=sorted(s.admin_discord_ids),
            saved=request.query_params.get("ok") == "1",
        )

    # Wissen aus Uploads entfernen bzw. neu aufbauen
    def forget_tests(rows: list[dict]) -> None:
        refs = {f"{r['user_id']}/{r['filename']}" for r in rows}
        h = History(s.history_path)
        before = len(h.records)
        h.records = [rec for rec in h.records if rec.file_a not in refs and rec.file_b not in refs]
        if len(h.records) != before:
            h.save()

    def with_pair(row: dict) -> list[dict]:
        return db.pair_members(row["pair_id"]) if row.get("pair_id") else [row]

    def reanalyse(rows: list[dict]) -> bool:
        """Neu auswerten – nur möglich, solange alle Rohdateien noch da sind."""
        if any(r.get("raw_deleted_at") or not Path(r["stored_path"]).exists() for r in rows):
            return False
        forget_tests(rows)
        for r in rows:
            db.update_upload(r["id"], status=QUEUED, error=None, ab_summary=None, ab_report_path=None, next_test=None, test_note=None)
        for r in rows:
            worker.submit(r["id"])
        return True

    def delete_uploads(rows: list[dict]) -> None:
        for r in rows:
            _remove_upload_files(s, r)
            if r.get("pair_id") and r.get("ab_report_path"):
                Path(r["ab_report_path"]).unlink(missing_ok=True)
            db.delete_upload(r["id"])

    BAN_DAYS = {"1": 1, "7": 7, "30": 30}

    async def admin_action(request: Request) -> Response:
        admin_user = require_admin(request)
        if isinstance(admin_user, Response):
            return admin_user
        form = await request.form()
        if not csrf_ok(request, form.get("csrf")):
            return message(request, "Sitzung abgelaufen", "Bitte die Seite neu laden.", 400)
        action = str(form.get("action") or "")
        back = str(form.get("back") or "/admin")
        if not back.startswith("/admin"):
            back = "/admin"
        reason = str(form.get("reason") or "").strip()[:500]

        def deny(text: str) -> Response:
            return message(request, "Nicht möglich", text, 400, (back, "Zurück"))

        # ---------------------------------------------------- Einstellungen
        if action == "einstellungen":
            ann = str(form.get("announcement") or "").strip()[:600]
            paused = form.get("paused") == "1"
            arch = form.get("archive_open") == "1"
            changes = []
            if arch != (db.get_setting("archive_open", "1") == "1"):
                db.log(admin_user, "Archiv-Upload " + ("geöffnet" if arch else "geschlossen"))
            db.set_setting("archive_open", "1" if arch else "0")
            for key, label, lo, hi in (("max_upload_mb", "Max. MB pro Datei", 10, 4000), ("max_files", "Max. Dateien pro Upload", 1, 50)):
                raw = str(form.get(key) or "").strip()
                if raw.isdigit():
                    val = str(min(max(int(raw), lo), hi))
                    if val != db.get_setting(key):
                        changes.append(f"{label}: {val}")
                    db.set_setting(key, val)
            for key, label, lo, hi in (("retention_keep_days", "Aufbewahrung komplett (Tage)", 1, 365),
                                       ("retention_limit_gb", "Grenze unvollständig (GB)", 1, 10000),
                                       ("retention_grace_days", "Frist unvollständig (Tage)", 1, 365)):
                raw = str(form.get(key) or "").strip()
                if raw.isdigit():
                    val = str(min(max(int(raw), lo), hi))
                    if val != db.get_setting(key):
                        changes.append(f"{label}: {val}")
                    db.set_setting(key, val)
            if "retention_move_to" in form:
                mv = str(form.get("retention_move_to") or "").strip()[:300]
                if mv != db.get_setting("retention_move_to"):
                    changes.append("Sicherungsordner: " + (mv or "keiner – Rohdateien werden gelöscht"))
                db.set_setting("retention_move_to", mv)
            note = str(form.get("pause_message") or "").strip()[:300]
            if ann != db.get_setting("announcement"):
                changes.append("Ankündigung " + ("gesetzt" if ann else "entfernt"))
            if paused != (db.get_setting("uploads_paused") == "1"):
                changes.append("Uploads " + ("pausiert" if paused else "wieder offen"))
            db.set_setting("announcement", ann)
            db.set_setting("uploads_paused", "1" if paused else "0")
            db.set_setting("pause_message", note)
            if changes:
                db.log(admin_user, "Einstellungen", detail=", ".join(changes))
            return RedirectResponse("/admin/einstellungen?ok=1", status_code=303)
        if action == "aufraeumen":
            res = await asyncio.to_thread(retention.run, db)
            db.set_setting("retention_last_run", now())
            db.log(admin_user, "Rohdateien aufgeräumt (von Hand)",
                   detail=f"{res['removed']} gelöscht ({res['freed_gb']:.1f} GB frei), {res['flagged']} mit Frist")
            return RedirectResponse("/admin/einstellungen?ok=1#speicher", status_code=303)
        if action == "leitfaden_alle":
            rnd = int(db.get_setting("guidelines_round", "0") or 0) + 1
            db.set_setting("guidelines_round", str(rnd))
            db.log(admin_user, "Leitfaden von allen neu bestätigen lassen", detail=reason)
            return RedirectResponse("/admin/einstellungen?ok=1", status_code=303)
        if action == "alles_neu":
            # nur, wo die Rohdatei noch da ist – Ergebnisse gelöschter Dateien bleiben im Wissen
            rows = [r for r in db.all_uploads(limit=1_000_000) if not r.get("raw_deleted_at") and Path(r["stored_path"]).exists()]
            have = {r["id"] for r in rows}
            rows = [r for r in rows if not r["pair_id"] or all(m["id"] in have for m in db.pair_members(r["pair_id"]))]
            forget_tests(rows)
            for r in rows:
                db.update_upload(r["id"], status=QUEUED, error=None, ab_summary=None, ab_report_path=None, next_test=None, test_note=None)
            for r in rows:
                worker.submit(r["id"])
            db.log(admin_user, "Alle Uploads neu auswerten", detail=f"{len(rows)} Dateien")
            return RedirectResponse("/admin/uploads", status_code=303)

        # ---------------------------------------------------------- Uploads
        if form.get("upload_id"):
            row = db.get_upload(str(form.get("upload_id")))
            if row is None:
                return deny("Diesen Upload gibt es nicht mehr.")
            owner = db.get_user(row["user_id"])
            group = with_pair(row)
            label = row["filename"] + (" (Garagen-Test)" if row.get("pair_id") else "")
            if action == "aussortieren":
                forget_tests(group)
                for r in group:
                    db.exclude_upload(r["id"], reason, admin_user["discord_id"])
                db.log(admin_user, "Upload aussortiert", owner, row["id"], f"{label}" + (f" – {reason}" if reason else ""))
            elif action == "werten":
                for r in group:
                    db.include_upload(r["id"])
                if not reanalyse(group):
                    return deny("Die Rohdatei ist schon gelöscht – der Upload ist wieder freigegeben, kann aber nicht neu ausgewertet werden. "
                                "Für eine Neuauswertung die Datei aus der Sicherung zurückspielen.")
                db.log(admin_user, "Upload wieder gewertet", owner, row["id"], label)
            elif action == "neu_auswerten":
                if not reanalyse(group):
                    return deny("Die Rohdatei ist schon gelöscht – die bisherige Auswertung bleibt bestehen.")
                db.log(admin_user, "Upload neu ausgewertet", owner, row["id"], label)
            elif action == "loeschen":
                delete_uploads(group)
                db.log(admin_user, "Upload gelöscht", owner, row["id"], f"{label}" + (f" – {reason}" if reason else ""))
            else:
                return deny("Unbekannte Aktion.")
            return RedirectResponse(back, status_code=303)

        # -------------------------------------------------------- Teilnehmer
        target = db.get_user(str(form.get("user_id") or ""))
        if target is None:
            return deny("Diesen Teilnehmer gibt es nicht (mehr).")
        is_self = target["discord_id"] == admin_user["discord_id"]
        if action in ("sperren", "rauswerfen", "admin_nehmen") and (is_self or is_owner(target)):
            return deny("Haupt-Admins aus portal.env und das eigene Konto lassen sich hier nicht sperren, entfernen oder herabstufen.")
        uploads = db.all_uploads(user_id=target["discord_id"], limit=1_000_000)
        if action == "sperren":
            days = BAN_DAYS.get(str(form.get("days") or ""))
            until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds") if days else None
            db.ban_user(target["discord_id"], reason, until, admin_user["discord_id"])
            extra = []
            if form.get("exclude") == "1":
                forget_tests(uploads)
                for r in uploads:
                    db.exclude_upload(r["id"], "Teilnehmer gesperrt" + (f": {reason}" if reason else ""), admin_user["discord_id"])
                extra.append("Daten aussortiert")
            if form.get("delete") == "1":
                delete_uploads(uploads)
                extra.append("Dateien gelöscht")
            dauer = f"{days} Tage" if days else "dauerhaft"
            db.log(admin_user, "Gesperrt", target, detail=f"{dauer}" + (f" – {reason}" if reason else "") + (f" ({', '.join(extra)})" if extra else ""))
        elif action == "entsperren":
            db.unban_user(target["discord_id"])
            db.log(admin_user, "Entsperrt", target, detail=reason)
        elif action == "rauswerfen":
            delete_uploads(uploads)
            db.delete_user(target["discord_id"])
            db.log(admin_user, "Entfernt (Konto und Daten gelöscht)", target, detail=(f"{len(uploads)} Dateien" + (f" – {reason}" if reason else "")))
            return RedirectResponse("/admin/teilnehmer", status_code=303)
        elif action == "daten_aussortieren":
            forget_tests(uploads)
            for r in uploads:
                db.exclude_upload(r["id"], reason, admin_user["discord_id"])
            db.log(admin_user, "Alle Daten aussortiert", target, detail=reason)
        elif action == "daten_werten":
            ex = [r for r in uploads if r["excluded_at"]]
            for r in ex:
                db.include_upload(r["id"])
            reanalyse([r for r in ex if not r.get("raw_deleted_at")])
            db.log(admin_user, "Alle Daten wieder gewertet", target, detail=f"{len(ex)} Dateien")
        elif action == "admin_geben":
            db.set_user_admin(target["discord_id"], True)
            db.log(admin_user, "Zum Admin gemacht", target)
        elif action == "admin_nehmen":
            db.set_user_admin(target["discord_id"], False)
            db.log(admin_user, "Admin-Rechte entzogen", target)
        elif action == "leitfaden_zuruecksetzen":
            db.reset_guidelines(target["discord_id"])
            db.log(admin_user, "Leitfaden muss neu bestätigt werden", target, detail=reason)
        elif action == "notiz":
            note = str(form.get("note") or "").strip()[:2000]
            db.set_user_note(target["discord_id"], note)
            db.log(admin_user, "Notiz geändert", target)
        else:
            return deny("Unbekannte Aktion.")
        return RedirectResponse(back, status_code=303)

    async def privacy(request: Request) -> Response:
        return render(request, "privacy.html")

    # -------------------------------------------------------------- API
    async def reject(request: Request, text: str, status_code: int) -> Response:
        """Ablehnen, aber kleinere Anfragen zu Ende lesen – sonst sieht der Browser nur
        „Verbindung abgebrochen“ statt der Meldung. Große Uploads nicht durchschleusen."""
        drained = 0
        async for chunk in request.stream():
            drained += len(chunk)
            if drained > 32 * 1024 * 1024:
                break
        return JSONResponse({"error": text}, status_code=status_code)

    async def api_upload(request: Request) -> Response:
        user = current_user(request)
        if user is None or not user["consent_at"]:
            return await reject(request, "Du bist nicht mehr angemeldet – bitte die Seite neu laden und anmelden.", 401)
        if not csrf_ok(request, request.headers.get("x-csrf-token")):
            return await reject(request, "Sitzung abgelaufen – bitte die Seite neu laden.", 400)
        if is_banned(user):
            return await reject(request, "Dein Zugang ist gesperrt.", 403)
        is_archive = request.query_params.get("art") == "archiv"
        if is_archive and not archive_open(user):
            return await reject(request, "Der Archiv-Upload ist gerade geschlossen.", 403)
        if not is_archive and not guidelines_ok(user):
            return await reject(request, "Bitte zuerst den Test-Leitfaden lesen und bestätigen.", 403)
        if uploads_paused(user):
            note = db.get_setting("pause_message")
            return await reject(request, "Uploads sind gerade pausiert." + (f" {note}" if note else ""), 503)
        limit_mb, nfiles = max_mb(), max_files()
        limit = limit_mb * 1024 * 1024
        declared = int(request.headers.get("content-length") or 0)
        if declared > limit * nfiles + 1024 * 1024:
            return JSONResponse({"error": f"Zu groß – höchstens {limit_mb} MB pro Datei und {nfiles} Dateien auf einmal."}, status_code=413)

        form = await request.form(max_files=nfiles, max_fields=20)
        files = [f for f in form.getlist("files") if hasattr(f, "filename") and f.filename]
        test_type = str(form.get("test_type") or "normal")
        if test_type not in TEST_TYPES or (test_type == "archiv") != is_archive:
            test_type = "archiv" if is_archive else "normal"
        description = str(form.get("description") or "")[:1000]
        feeling = str(form.get("feeling") or "")[:1000]
        if not files:
            return JSONResponse({"error": "Keine Datei ausgewählt."}, status_code=400)
        if test_type == "garage" and len(files) != 3:
            return JSONResponse({"error": "Für einen Garagen-Test bitte genau drei Dateien hochladen: Run A, Run B und das zweite A."}, status_code=400)

        pair_id = uuid.uuid4().hex if test_type == "garage" else None
        user_dir = s.uploads_dir / user["discord_id"]
        user_dir.mkdir(parents=True, exist_ok=True)
        items = []
        for f in files:
            name = Path(f.filename).name[:200]
            if not name.lower().endswith(".ibt"):
                items.append({"filename": name, "ok": False, "message": "Keine .ibt-Datei – bitte die Datei aus Dokumente\\iRacing\\telemetry nehmen."})
                continue
            upload_id = uuid.uuid4().hex
            dest = user_dir / f"{upload_id}.ibt"
            sha, size, too_big = hashlib.sha256(), 0, False
            with open(dest, "wb") as out:
                while chunk := await f.read(CHUNK):
                    size += len(chunk)
                    if size > limit:
                        too_big = True
                        break
                    sha.update(chunk)
                    out.write(chunk)
            await f.close()
            if too_big:
                dest.unlink(missing_ok=True)
                items.append({"filename": name, "ok": False, "message": f"Größer als {limit_mb} MB."})
                continue
            digest = sha.hexdigest()
            dup = db.find_duplicate(user["discord_id"], digest)
            if dup is not None and test_type != "garage":
                dest.unlink(missing_ok=True)
                items.append({"filename": name, "ok": True, "id": dup["id"], "status": dup["status"], "message": "Schon hochgeladen."})
                continue
            try:
                await asyncio.to_thread(IbtFile.open, dest)
            except (IbtError, OSError, ValueError) as e:
                dest.unlink(missing_ok=True)
                items.append({"filename": name, "ok": False, "message": f"Keine lesbare iRacing-Telemetrie ({e})."})
                continue
            db.add_upload(
                dict(
                    id=upload_id,
                    user_id=user["discord_id"],
                    filename=name,
                    stored_path=str(dest),
                    sha256=digest,
                    size=size,
                    uploaded_at=now(),
                    test_type=test_type,
                    pair_id=pair_id,
                    description=description,
                    feeling=feeling,
                    status=QUEUED,
                )
            )
            worker.submit(upload_id)
            items.append({"filename": name, "ok": True, "id": upload_id, "status": QUEUED, "message": "Hochgeladen – Auswertung läuft."})
        ok = any(i["ok"] for i in items)
        return JSONResponse({"items": items}, status_code=200 if ok else 400)

    async def api_status(request: Request) -> Response:
        user = current_user(request)
        if user is None:
            return JSONResponse({"error": "Du bist nicht mehr angemeldet – bitte die Seite neu laden und anmelden."}, status_code=401)
        rows = db.uploads_for_user(user["discord_id"])
        return JSONResponse(
            {
                "uploads": [
                    {"id": r["id"], "status": r["status"], "error": r["error"], "has_ab": bool(r["ab_summary"])}
                    for r in rows
                ]
            }
        )

    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True, "version": __version__, "discord": s.discord_configured})

    async def cleanup_loop() -> None:
        """Rohdateien nach den Aufbewahrungsregeln aufräumen – beim Start und dann stündlich."""
        while True:
            try:
                res = await asyncio.to_thread(retention.run, db)
                db.set_setting("retention_last_run", now())
                if res["removed"] or res["flagged"]:
                    log.info("Aufräumen: %s", res)
                    db.log({"discord_id": "system", "username": "Automatik"}, "Rohdateien aufgeräumt",
                           detail=f"{res['removed']} gelöscht ({res['freed_gb']:.1f} GB frei), {res['flagged']} mit Frist")
            except Exception:  # noqa: BLE001
                log.exception("Aufräumen fehlgeschlagen")
            await asyncio.sleep(3600)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        worker.resume()
        task = asyncio.create_task(cleanup_loop())
        yield
        task.cancel()
        worker.shutdown()

    routes = [
        Route("/", landing),
        Route("/login", login),
        Route("/auth/callback", callback),
        Route("/dev-login", dev_login),
        Route("/logout", logout),
        Route("/einwilligung", consent, methods=["GET", "POST"]),
        Route("/meine-daten", dashboard),
        Route("/bericht/{upload_id}", report),
        Route("/bericht/{upload_id}/{kind}", report),
        Route("/upload/{upload_id}/loeschen", delete_upload, methods=["POST"]),
        Route("/projekt", project),
        Route("/archiv", archive_page),
        Route("/download/telemetrie-pruefen", download_script),
        Route("/fortschritt", progress_page),
        Route("/admin", admin_home),
        Route("/admin/teilnehmer", admin_people),
        Route("/admin/teilnehmer/{uid}", admin_person),
        Route("/admin/uploads", admin_uploads),
        Route("/admin/protokoll", admin_log),
        Route("/admin/einstellungen", admin_settings),
        Route("/admin/aktion", admin_action, methods=["POST"]),
        Route("/datenschutz", privacy),
        Route("/leitfaden", guidelines),
        Route("/leitfaden/bestaetigen", guidelines_confirm, methods=["POST"]),
        Route("/api/upload", api_upload, methods=["POST"]),
        Route("/api/status", api_status),
        Route("/health", health),
        Mount("/static", StaticFiles(directory=str(HERE / "static")), name="static"),
    ]
    middleware = [
        Middleware(
            SessionMiddleware,
            secret_key=s.session_secret,
            session_cookie="se_session",
            max_age=30 * 24 * 3600,
            same_site="lax",
            https_only=s.https_only,
        )
    ]
    app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
    app.state.settings, app.state.db, app.state.worker = s, db, worker
    return app


def _remove_upload_files(s: Settings, row: dict) -> None:
    """Datei, Berichte und den daraus abgeleiteten Test aus dem Community-Wissen entfernen."""
    for key in ("stored_path", "report_path"):
        if row.get(key):
            Path(row[key]).unlink(missing_ok=True)
    if row.get("ab_report_path") and not row.get("pair_id"):
        Path(row["ab_report_path"]).unlink(missing_ok=True)
    ref = f"{row['user_id']}/{row['filename']}"
    h = History(s.history_path)
    before = len(h.records)
    h.records = [r for r in h.records if ref not in (r.file_a, r.file_b)]
    if len(h.records) != before:
        h.save()

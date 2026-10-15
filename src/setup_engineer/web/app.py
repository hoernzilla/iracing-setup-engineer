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
from ..ibt import IbtError, IbtFile
from ..recommend.history import History
from . import discord
from .config import Settings, load_settings
from .db import Database, now
from .worker import DONE, FAILED, QUEUED, Worker, report_text

log = logging.getLogger("portal")
HERE = Path(__file__).resolve().parent
CHUNK = 1024 * 1024
TEST_TYPES = {
    "normal": "Normale Runs",
    "aba": "A-B-A-Test im Auto",
    "garage": "Garage-Test (zwei Runs)",
}
# Bei inhaltlichen Änderungen am Leitfaden erhöhen -> alle bestätigen neu
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
        max_upload_mb=s.max_upload_mb,
        max_files=s.max_files_per_upload,
    )
    hero = _hero_trace()

    # ------------------------------------------------------------ Hilfen
    def current_user(request: Request) -> dict | None:
        uid = request.session.get("uid")
        return db.get_user(uid) if uid else None

    def is_admin(user: dict | None) -> bool:
        return bool(user and user["discord_id"] in s.admin_discord_ids)

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
        ctx.update(request=request, user=user, admin=is_admin(user), csrf=csrf_token(request))
        return templates.TemplateResponse(request, name, ctx, status_code=status_code)

    def message(request: Request, title: str, text: str, status_code: int = 200, action: tuple[str, str] | None = None) -> Response:
        return render(request, "message.html", status_code=status_code, title=title, text=text, action=action)

    def guidelines_ok(user: dict | None) -> bool:
        return bool(user and user.get("guidelines_version") == GUIDELINES_VERSION)

    def require_user(request: Request) -> dict | Response:
        user = current_user(request)
        if user is None:
            return RedirectResponse("/", status_code=303)
        if not user["consent_at"]:
            return RedirectResponse("/einwilligung", status_code=303)
        return user

    # ----------------------------------------------------------- Seiten
    async def landing(request: Request) -> Response:
        user = current_user(request)
        if user and user["consent_at"]:
            return RedirectResponse("/meine-daten", status_code=303)
        return render(request, "landing.html", hero=hero, totals=db.totals(), discord_ready=s.discord_configured)

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
        for u in uploads:
            u["ab"] = json.loads(u["ab_summary"]) if u["ab_summary"] else None
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
        )

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
        db.set_guidelines(user["discord_id"], GUIDELINES_VERSION)
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

    async def admin(request: Request) -> Response:
        user = require_user(request)
        if isinstance(user, Response):
            return user
        if not is_admin(user):
            return message(request, "Kein Zugriff", "Diese Seite ist nur für die Projekt-Admins.", 403)
        return render(
            request,
            "admin.html",
            people=db.users_with_stats(),
            guidelines_version=GUIDELINES_VERSION,
            coverage=db.coverage(),
            totals=db.totals(),
            goal1=GOAL_STAGE1,
            goal2=GOAL_STAGE2,
            failed=db.uploads_by_status(FAILED),
        )

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
        if not guidelines_ok(user):
            return await reject(request, "Bitte zuerst den Test-Leitfaden lesen und bestätigen.", 403)
        limit = s.max_upload_mb * 1024 * 1024
        declared = int(request.headers.get("content-length") or 0)
        if declared > limit * s.max_files_per_upload + 1024 * 1024:
            return JSONResponse({"error": f"Zu groß – höchstens {s.max_upload_mb} MB pro Datei."}, status_code=413)

        form = await request.form(max_files=s.max_files_per_upload, max_fields=20)
        files = [f for f in form.getlist("files") if hasattr(f, "filename") and f.filename]
        test_type = str(form.get("test_type") or "normal")
        if test_type not in TEST_TYPES:
            test_type = "normal"
        description = str(form.get("description") or "")[:1000]
        feeling = str(form.get("feeling") or "")[:1000]
        if not files:
            return JSONResponse({"error": "Keine Datei ausgewählt."}, status_code=400)
        if test_type == "garage" and len(files) != 2:
            return JSONResponse({"error": "Für einen Garage-Test bitte genau zwei Dateien hochladen: den Run vorher und den Run nachher."}, status_code=400)

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
                items.append({"filename": name, "ok": False, "message": f"Größer als {s.max_upload_mb} MB."})
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

    @asynccontextmanager
    async def lifespan(app: Starlette):
        worker.resume()
        yield
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
        Route("/admin", admin),
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

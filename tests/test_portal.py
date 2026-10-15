"""Ende-zu-Ende-Test des Community-Portals mit nachgebautem Discord.

Startet das Portal (uvicorn) und einen Schein-Discord-Server, meldet sich als
Mitglied und als Fremder an, lädt synthetische IBT-Dateien hoch und prüft
Auswertung, A-B-A-Vergleich, Garage-Paar, Rechte und Schutz gegen Fremdzugriffe.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn  # noqa: E402

from setup_engineer.synth import SynthConfig, make_file  # noqa: E402
from setup_engineer.web.app import create_app, safe_report_html  # noqa: E402
from setup_engineer.web.config import Settings  # noqa: E402

GUILD = "900000000000000000"
MEMBER = {"id": "111111111111111111", "username": "racer_one", "global_name": "Racer One", "avatar": None}
OUTSIDER = {"id": "222222222222222222", "username": "fremder", "global_name": "Fremder", "avatar": None}
SECOND = {"id": "333333333333333333", "username": "racer_two", "global_name": "Racer Two", "avatar": None}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeDiscord(BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:  # leise
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _who(self) -> dict | None:
        tok = self.headers.get("Authorization", "").removeprefix("Bearer ")
        return {"tok-member": MEMBER, "tok-outsider": OUTSIDER, "tok-second": SECOND}.get(tok)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        if self.path.endswith("/oauth2/token") and form.get("client_secret") == ["geheim"]:
            code = form.get("code", [""])[0]
            if code in ("member", "outsider", "second"):
                return self._json(200, {"access_token": f"tok-{code}", "token_type": "Bearer"})
        self._json(400, {"error": "invalid_grant"})

    def do_GET(self) -> None:
        who = self._who()
        if who is None:
            return self._json(401, {"message": "401: Unauthorized"})
        if self.path.endswith("/users/@me"):
            return self._json(200, who)
        if self.path.endswith(f"/users/@me/guilds/{GUILD}/member"):
            if who is MEMBER:
                return self._json(200, {"nick": "Racer #1", "roles": ["555"], "avatar": None})
            if who is SECOND:
                return self._json(200, {"nick": None, "roles": [], "avatar": None})
            return self._json(404, {"message": "Unknown Guild", "code": 10004})
        self._json(404, {})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Browser:
    def __init__(self, base: str) -> None:
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)

    def req(self, path: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None):
        r = urllib.request.Request(self.base + path, data=data, headers=headers or {}, method=method)
        try:
            resp = self.opener.open(r, timeout=60)
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8", "replace")

    def form(self, path: str, fields: dict) -> tuple:
        return self.req(path, urllib.parse.urlencode(fields).encode(), {"Content-Type": "application/x-www-form-urlencoded"})

    def upload(self, files: list[tuple[str, bytes]], fields: dict, csrf: str | None):
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for name, content in files:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n"
            )
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        status, _, text = self.req("/api/upload", body, headers)
        return status, json.loads(text)

    def login(self, code: str) -> tuple:
        status, headers, _ = self.req("/login")
        assert status == 303, status
        state = urllib.parse.parse_qs(urllib.parse.urlparse(headers["location"]).query)["state"][0]
        return self.req(f"/auth/callback?code={code}&state={state}")


def csrf_from(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


class TestPortal(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        dport, pport = free_port(), free_port()
        cls.discord = ThreadingHTTPServer(("127.0.0.1", dport), FakeDiscord)
        threading.Thread(target=cls.discord.serve_forever, daemon=True).start()
        settings = Settings(
            discord_client_id="123",
            discord_client_secret="geheim",
            discord_redirect_uri=f"http://127.0.0.1:{pport}/auth/callback",
            discord_guild_id=GUILD,
            admin_discord_ids={MEMBER["id"]},
            community_name="Testgemeinschaft",
            data_dir=tmp / "data",
            session_secret="test-secret-" + "x" * 30,
            discord_api_base=f"http://127.0.0.1:{dport}",
            discord_authorize_url=f"http://127.0.0.1:{dport}/authorize",
            port=pport,
        )
        for d in (settings.data_dir, settings.uploads_dir, settings.reports_dir):
            d.mkdir(parents=True, exist_ok=True)
        cls.settings = settings
        cls.server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=pport, log_level="warning"))
        threading.Thread(target=cls.server.run, daemon=True).start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        cls.base = f"http://127.0.0.1:{pport}"
        # Testdateien
        cls.aba = make_file(tmp / "aba.ibt", SynthConfig(seed=7, laps=16, arb_schedule={6: 3, 11: 1})).read_bytes()
        cls.run_a = make_file(tmp / "a.ibt", SynthConfig(seed=10, laps=8)).read_bytes()
        cls.run_b = make_file(tmp / "b.ibt", SynthConfig(seed=11, laps=8, spring_front="200 N/mm")).read_bytes()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.discord.shutdown()
        time.sleep(0.3)
        cls.tmp.cleanup()

    def member(self, code: str = "member") -> tuple[Browser, str]:
        b = Browser(self.base)
        status, headers, _ = b.login(code)
        self.assertEqual(status, 303)
        if headers["location"].endswith("/einwilligung"):
            _, _, html = b.req("/einwilligung")
            status, headers, _ = b.form("/einwilligung", {"csrf": csrf_from(html), "zustimmung": "ja"})
            self.assertEqual(headers["location"], "/meine-daten")
        _, _, html = b.req("/meine-daten")
        csrf = csrf_from(html)
        if "Erst der Leitfaden" in html:
            status, headers, _ = b.form("/leitfaden/bestaetigen", {"csrf": csrf, "gelesen": "ja"})
            self.assertEqual(status, 303)
            _, _, html = b.req("/meine-daten")
            self.assertIn("Telemetrie hochladen", html)
        return b, csrf

    def wait_done(self, b: Browser, ids: list[str], timeout: float = 60) -> dict:
        t0 = time.time()
        while time.time() - t0 < timeout:
            _, _, text = b.req("/api/status")
            rows = {u["id"]: u for u in json.loads(text)["uploads"]}
            if all(rows.get(i, {}).get("status") in ("fertig", "fehler") for i in ids):
                return rows
            time.sleep(0.3)
        self.fail("Auswertung nicht rechtzeitig fertig")

    # ------------------------------------------------------------- Tests
    def test_01_landing_and_privacy(self) -> None:
        b = Browser(self.base)
        status, _, html = b.req("/")
        self.assertEqual(status, 200)
        self.assertIn("Mit Discord anmelden", html)
        self.assertIn("Testgemeinschaft", html)
        self.assertIn('class="trace-line"', html)
        self.assertEqual(b.req("/datenschutz")[0], 200)
        self.assertEqual(json.loads(b.req("/health")[2])["discord"], True)

    def test_02_outsider_blocked(self) -> None:
        b = Browser(self.base)
        status, _, html = b.login("outsider")
        self.assertEqual(status, 403)
        self.assertIn("Nur für Mitglieder", html)
        self.assertEqual(b.req("/meine-daten")[1].get("location"), "/")

    def test_03_bad_state_rejected(self) -> None:
        b = Browser(self.base)
        b.req("/login")
        status, _, html = b.req("/auth/callback?code=member&state=gefaelscht")
        self.assertEqual(status, 400)

    def test_04_consent_required(self) -> None:
        b = Browser(self.base)
        status, headers, _ = b.login("member")
        # Erstes Login -> Einwilligung (oder schon erteilt, wenn andere Tests vorher liefen)
        self.assertIn(headers["location"], ("/einwilligung", "/meine-daten"))
        if headers["location"] == "/einwilligung":
            _, _, html = b.req("/einwilligung")
            status, _, html2 = b.form("/einwilligung", {"csrf": csrf_from(html)})
            self.assertIn("Häkchen", html2)

    def test_045_guidelines_gate(self) -> None:
        # frisches Mitglied (eigene ID über eigenen Token geht hier nicht) -> Gate direkt prüfen
        b = Browser(self.base)
        b.login("member")
        _, _, html = b.req("/einwilligung")
        if 'name="zustimmung"' in html:
            b.form("/einwilligung", {"csrf": csrf_from(html), "zustimmung": "ja"})
        _, _, html = b.req("/meine-daten")
        if "Erst der Leitfaden" in html:
            csrf = csrf_from(html)
            self.assertIn("Das bitte auf keinen Fall", html)
            status, body = b.upload([("x.ibt", self.run_a)], {"test_type": "normal"}, csrf)
            self.assertEqual(status, 403)
            self.assertIn("Leitfaden", body["error"])
            status, headers, _ = b.form("/leitfaden/bestaetigen", {"csrf": csrf})  # ohne Häkchen
            self.assertIn("leitfaden=fehlt", headers["location"])
        self.assertEqual(Browser(self.base).req("/leitfaden")[0], 200)

    def test_05_upload_aba_and_reports(self) -> None:
        b, csrf = self.member()
        status, body = b.upload([("963_test.ibt", self.aba)], {"test_type": "aba", "description": "Stabi vorne 1 auf 3"}, csrf)
        self.assertEqual(status, 200, body)
        uid = body["items"][0]["id"]
        rows = self.wait_done(b, [uid])
        self.assertEqual(rows[uid]["status"], "fertig", rows[uid])
        self.assertTrue(rows[uid]["has_ab"])
        status, _, html = b.req(f"/bericht/{uid}")
        self.assertEqual(status, 200)
        self.assertIn("Empfohlene Änderungen", html)
        status, _, html = b.req(f"/bericht/{uid}/vergleich")
        self.assertIn("Stabilisator vorne", html)
        _, _, dash = b.req("/meine-daten")
        self.assertIn("Synth GT3", dash)
        self.assertIn("Dein nächster Test", dash)
        hist = json.loads(self.settings.history_path.read_text(encoding="utf-8"))
        self.assertTrue(any(r["within_session"] for r in hist))
        # Duplikat
        status, body = b.upload([("963_test.ibt", self.aba)], {"test_type": "aba"}, csrf)
        self.assertEqual(body["items"][0]["message"], "Schon hochgeladen.")

    def test_06_garage_pair(self) -> None:
        b, csrf = self.member()
        status, body = b.upload([("vorher.ibt", self.run_a), ("nachher.ibt", self.run_b)], {"test_type": "garage"}, csrf)
        self.assertEqual(status, 200, body)
        ids = [i["id"] for i in body["items"]]
        self.wait_done(b, ids)
        for _ in range(50):  # Vergleich läuft nach beiden Auswertungen
            _, _, text = b.req("/api/status")
            rows = {u["id"]: u for u in json.loads(text)["uploads"]}
            if all(rows[i]["has_ab"] for i in ids):
                break
            time.sleep(0.3)
        self.assertTrue(all(rows[i]["has_ab"] for i in ids))
        _, _, html = b.req(f"/bericht/{ids[0]}/vergleich")
        self.assertIn("SpringRate", html)
        # Garage-Test braucht genau zwei Dateien
        status, body = b.upload([("einzeln.ibt", self.run_a)], {"test_type": "garage"}, csrf)
        self.assertEqual(status, 400)

    def test_07_rejections(self) -> None:
        b, csrf = self.member()
        status, body = b.upload([("x.ibt", self.run_a)], {"test_type": "normal"}, None)
        self.assertEqual(status, 400)
        self.assertIn("Sitzung", body["error"])
        status, body = b.upload([("bild.png", b"\x89PNG....")], {"test_type": "normal"}, csrf)
        self.assertEqual(status, 400)
        self.assertFalse(body["items"][0]["ok"])
        status, body = b.upload([("kaputt.ibt", b"\x00" * 4000)], {"test_type": "normal"}, csrf)
        self.assertEqual(status, 400)
        self.assertIn("Keine lesbare", body["items"][0]["message"])
        anon = Browser(self.base)
        status, body = anon.upload([("x.ibt", self.run_a)], {}, "egal")
        self.assertEqual(status, 401)

    def test_08_admin_and_delete(self) -> None:
        b, csrf = self.member()
        status, _, html = b.req("/admin")
        self.assertEqual(status, 200)
        self.assertIn("Racer #1", html)
        self.assertIn("Datenlage je Auto", html)
        status, body = b.upload([("loeschmich.ibt", make_file(Path(self.tmp.name) / "d.ibt", SynthConfig(seed=21, laps=16, arb_schedule={6: 3, 11: 1})).read_bytes())], {"test_type": "aba"}, csrf)
        uid = body["items"][0]["id"]
        self.wait_done(b, [uid])
        before = len(json.loads(self.settings.history_path.read_text(encoding="utf-8")))
        status, headers, _ = b.form(f"/upload/{uid}/loeschen", {"csrf": csrf})
        self.assertEqual(status, 303)
        _, _, text = b.req("/api/status")
        self.assertNotIn(uid, text)
        after = len(json.loads(self.settings.history_path.read_text(encoding="utf-8")))
        self.assertEqual(after, before - 1)
        self.assertFalse((self.settings.uploads_dir / MEMBER["id"] / f"{uid}.ibt").exists())

    def test_10_public_pages_and_landing_when_logged_in(self) -> None:
        b, _ = self.member()
        status, _, html = b.req("/")
        self.assertEqual(status, 200)  # keine Umleitung mehr
        self.assertIn("Zum Upload", html)
        status, _, html = b.req("/projekt")
        self.assertEqual(status, 200)
        self.assertIn("Weniger raten", html)
        status, _, html = Browser(self.base).req("/fortschritt")
        self.assertEqual(status, 200)
        self.assertIn("Wo das Projekt steht", html)
        self.assertIn("Phasen", html)

    def test_11_moderation(self) -> None:
        admin, acsrf = self.member()
        two, csrf2 = self.member("second")
        self.assertEqual(two.req("/admin")[0], 403)
        data = make_file(Path(self.tmp.name) / "two.ibt", SynthConfig(seed=31, laps=16, arb_schedule={6: 3, 11: 1})).read_bytes()
        status, body = two.upload([("two_aba.ibt", data)], {"test_type": "aba"}, csrf2)
        self.assertEqual(status, 200, body)
        up = body["items"][0]["id"]
        self.wait_done(two, [up])

        def refs() -> list[str]:
            return [r["file_a"] for r in json.loads(self.settings.history_path.read_text(encoding="utf-8"))]

        def act(fields: dict) -> tuple:
            return admin.form("/admin/aktion", {"csrf": acsrf, **fields})

        self.assertTrue(any(SECOND["id"] in r for r in refs()))
        # Upload aussortieren -> raus aus dem Wissen, im Dashboard markiert
        self.assertEqual(act({"action": "aussortieren", "upload_id": up, "reason": "zwei Dinge geändert"})[0], 303)
        self.assertFalse(any(SECOND["id"] in r for r in refs()))
        self.assertIn("zwei Dinge geändert", two.req("/meine-daten")[2])
        # wieder werten -> neu ausgewertet, wieder im Wissen
        act({"action": "werten", "upload_id": up})
        for _ in range(100):
            if any(SECOND["id"] in r for r in refs()):
                break
            time.sleep(0.2)
        self.assertTrue(any(SECOND["id"] in r for r in refs()))
        # Pause: Teilnehmer abgelehnt, Admin nicht
        act({"action": "einstellungen", "paused": "1", "pause_message": "Wartung", "announcement": "Heute Abend Testabend!"})
        status, body = two.upload([("x.ibt", self.run_a)], {"test_type": "normal"}, csrf2)
        self.assertEqual(status, 503)
        self.assertIn("Wartung", body["error"])
        self.assertIn("Heute Abend Testabend!", Browser(self.base).req("/")[2])
        act({"action": "einstellungen", "announcement": ""})
        # Sperren mit Aussortieren
        status, _, _ = act({"action": "sperren", "user_id": SECOND["id"], "reason": "unsaubere Daten", "days": "7", "exclude": "1"})
        self.assertEqual(status, 303)
        status, _, html = two.req("/meine-daten")
        self.assertEqual(status, 403)
        self.assertIn("unsaubere Daten", html)
        self.assertEqual(two.upload([("x.ibt", self.run_a)], {"test_type": "normal"}, csrf2)[0], 403)
        self.assertFalse(any(SECOND["id"] in r for r in refs()))
        self.assertEqual(Browser(self.base).login("second")[0], 403)
        # sich selbst sperren geht nicht
        self.assertEqual(act({"action": "sperren", "user_id": MEMBER["id"]})[0], 400)
        # Entsperren, Admin geben und nehmen
        act({"action": "entsperren", "user_id": SECOND["id"]})
        self.assertEqual(two.req("/meine-daten")[0], 200)
        act({"action": "admin_geben", "user_id": SECOND["id"]})
        self.assertEqual(two.req("/admin/teilnehmer")[0], 200)
        act({"action": "admin_nehmen", "user_id": SECOND["id"]})
        self.assertEqual(two.req("/admin")[0], 403)
        # Seiten der Verwaltung
        for path in ("/admin", "/admin/teilnehmer", f"/admin/teilnehmer/{SECOND['id']}", "/admin/uploads?excluded=ja", "/admin/protokoll", "/admin/einstellungen"):
            self.assertEqual(admin.req(path)[0], 200, path)
        self.assertIn("Gesperrt", admin.req("/admin/protokoll")[2])
        # Rauswerfen: Konto und Dateien weg, Sitzung ungültig
        act({"action": "rauswerfen", "user_id": SECOND["id"], "reason": "Test"})
        self.assertFalse((self.settings.uploads_dir / SECOND["id"] / f"{up}.ibt").exists())
        self.assertEqual(two.req("/meine-daten")[1].get("location"), "/")
        self.assertEqual(admin.req(f"/admin/teilnehmer/{SECOND['id']}")[0], 404)
        # Leitfaden von allen neu bestätigen lassen
        act({"action": "leitfaden_alle", "reason": "neuer Abschnitt"})
        self.assertIn("Erst der Leitfaden", admin.req("/meine-daten")[2])
        admin.form("/leitfaden/bestaetigen", {"csrf": acsrf, "gelesen": "ja"})

    def test_12_archive(self) -> None:
        b, csrf = self.member()
        status, _, html = b.req("/archiv")
        self.assertEqual(status, 200)
        self.assertIn("Altdaten hochladen", html)
        status, headers, body = b.req("/download/telemetrie-pruefen")
        self.assertEqual(status, 200)
        self.assertIn("Read-Ibt", body)
        tmp = Path(self.tmp.name)
        a = make_file(tmp / "arch_a.ibt", SynthConfig(seed=51, laps=8)).read_bytes()
        bb = make_file(tmp / "arch_b.ibt", SynthConfig(seed=52, laps=8, spring_front="200 N/mm")).read_bytes()
        short = make_file(tmp / "arch_kurz.ibt", SynthConfig(seed=53, laps=3)).read_bytes()
        ids = []
        for name, data in (("alt_a.ibt", a), ("alt_b.ibt", bb), ("alt_kurz.ibt", short)):
            body = b.req("/api/upload?art=archiv", *self._multipart([(name, data)], {"test_type": "archiv"}, csrf))[2]
            ids.append(json.loads(body)["items"][0]["id"])
        self.wait_done(b, ids)
        for _ in range(60):
            hist = json.loads(self.settings.history_path.read_text(encoding="utf-8"))
            if any(r.get("source") == "archiv" and "alt_a.ibt" in r["file_a"] + r["file_b"] for r in hist):
                break
            time.sleep(0.3)
        self.assertTrue(any(r.get("source") == "archiv" for r in hist), "versteckter Garage-Test nicht gefunden")
        _, _, html = b.req("/archiv")
        self.assertIn("weniger als 5 saubere Runden", html)
        _, _, html = Browser(self.base).req("/fortschritt")
        self.assertIn("Archiv", html)

    def _multipart(self, files, fields, csrf):
        boundary = uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
        for name, content in files:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
                         f"Content-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        return body, {"Content-Type": f"multipart/form-data; boundary={boundary}", "X-CSRF-Token": csrf}

    def test_09_report_escaping(self) -> None:
        html = safe_report_html("| a | b |\n| --- | --- |\n| <script>alert(1)</script> | [x](javascript:alert(1)) |\n\n![i](http://x/y.png)")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<a ", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()

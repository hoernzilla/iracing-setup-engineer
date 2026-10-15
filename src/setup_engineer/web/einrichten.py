"""Einrichtungshelfer für portal.env – wird von Portal-Einrichten.bat aufgerufen.

    python -m setup_engineer.web.einrichten          portal.env anlegen/ergänzen, Adresse ausgeben
    python -m setup_engineer.web.einrichten --port   nur den eingestellten Port ausgeben (für die Firewall-Regel)

Das Portal wird direkt über die Server-IP und einen eigenen Port erreicht (kein Port 80/443).
Die öffentliche IP wird automatisch ermittelt und in DISCORD_REDIRECT_URI eingetragen,
solange dort noch der Platzhalter oder eine localhost-Adresse steht.
"""

from __future__ import annotations

import ipaddress
import sys
import urllib.request
from pathlib import Path

from .config import DEFAULT_PORT, PROJECT_ROOT

ENV_FILE = PROJECT_ROOT / "portal.env"
EXAMPLE_FILE = PROJECT_ROOT / "portal.env.example"
PLACEHOLDER = "SERVER-IP"


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _value(lines: list[str], key: str) -> str:
    for line in lines:
        k, sep, v = line.partition("=")
        if sep and k.strip() == key and not line.lstrip().startswith("#"):
            return v.strip().strip('"').strip("'")
    return ""


def _set(lines: list[str], key: str, value: str) -> list[str]:
    out, done = [], False
    for line in lines:
        k, sep, _ = line.partition("=")
        if sep and k.strip() == key and not line.lstrip().startswith("#"):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    return out


def public_ip() -> str:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                ip = r.read().decode().strip()
            ipaddress.ip_address(ip)
            return ip
        except Exception:  # noqa: BLE001 – nächsten Dienst versuchen
            continue
    return ""


def configured_port() -> int:
    if ENV_FILE.exists():
        raw = _value(_read(ENV_FILE), "PORTAL_PORT")
        if raw.isdigit():
            return int(raw)
    return DEFAULT_PORT


def main(argv: list[str]) -> int:
    if "--port" in argv:
        print(configured_port())
        return 0

    created = False
    if not ENV_FILE.exists():
        ENV_FILE.write_text(EXAMPLE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        created = True
    lines = _read(ENV_FILE)
    # Umstellung von der frueheren Vorlage (nur lokal hinter einem Proxy, Port 8420)
    if _value(lines, "PORTAL_PORT") in ("", "8420"):
        lines = _set(lines, "PORTAL_PORT", str(DEFAULT_PORT))
    if _value(lines, "PORTAL_HOST") in ("", "127.0.0.1"):
        lines = _set(lines, "PORTAL_HOST", "0.0.0.0")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    port = configured_port()
    redirect = _value(lines, "DISCORD_REDIRECT_URI")

    if not redirect or any(s in redirect for s in (PLACEHOLDER, "localhost", "127.0.0.1", ":8420/")):
        ip = public_ip()
        if not ip:
            print("   Die oeffentliche IP konnte nicht automatisch ermittelt werden.")
            try:
                ip = input("   Bitte die IP-Adresse des Servers eingeben: ").strip()
            except EOFError:
                ip = ""
        if ip:
            redirect = f"http://{ip}:{port}/auth/callback"
            lines = _set(lines, "DISCORD_REDIRECT_URI", redirect)

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    base = redirect.removesuffix("/auth/callback") if redirect else f"http://SERVER-IP:{port}"
    print("   portal.env wurde angelegt." if created else "   portal.env ist vorhanden und wurde geprueft.")
    print()
    print(f"   Adresse des Portals:        {base}")
    print(f"   Redirect fuer Discord:      {redirect or '(noch offen)'}")
    print("   Genau diese Redirect-Adresse in der Discord-Anwendung unter OAuth2 -> Redirects eintragen.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

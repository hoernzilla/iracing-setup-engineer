"""Portal starten:  python -m setup_engineer.web"""

import logging

import uvicorn

from .app import create_app
from .config import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = load_settings()
public = settings.discord_redirect_uri.removesuffix("/auth/callback")
print(f"Setup-Engineer-Portal startet auf Port {settings.port}.")
print(f"Adresse fuer die Community:  {public}")
print(f"Auf dem Server selbst:       http://localhost:{settings.port}")
if not settings.discord_configured:
    print("Hinweis: Discord ist noch nicht eingerichtet (portal.env) – Anmeldung nicht möglich.")
uvicorn.run(
    create_app(settings),
    host=settings.host,
    port=settings.port,
    proxy_headers=True,
    forwarded_allow_ips="127.0.0.1",
    log_level="info",
)

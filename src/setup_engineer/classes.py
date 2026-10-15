"""Fahrzeugklasse aus dem Autonamen (CarScreenName) bestimmen: GTP, GT3 oder keine.

Dieselben Regeln stecken im Browser-Vorabcheck (archive.js) und im Windows-Skript
(Telemetrie-Pruefen.bat) – bei Änderungen dort mitziehen.
"""

from __future__ import annotations

GTP_MARKERS = ("gtp", "arx-06", "m hybrid v8", "v-series.r", "963", "499p")
GT3_MARKER = "gt3"
GT3_EXCLUDE = ("cup",)  # Porsche 911 GT3 Cup ist ein Markenpokal, kein GT3


def car_class(name: str | None) -> str | None:
    n = (name or "").lower()
    if any(m in n for m in GTP_MARKERS):
        return "GTP"
    if GT3_MARKER in n and not any(x in n for x in GT3_EXCLUDE):
        return "GT3"
    return None

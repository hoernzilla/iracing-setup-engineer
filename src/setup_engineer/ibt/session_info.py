"""Session-Info (YAML) robust einlesen.

iRacing schreibt ISO-8859-1-kodiertes YAML. Fahrernamen, Teamnamen und
Sponsoren enthalten gelegentlich Zeichen, an denen ein strikter Parser
scheitert. Wir versuchen es daher in Stufen.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

try:  # C-Loader ist deutlich schneller, falls vorhanden
    _Loader = yaml.CSafeLoader  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover
    _Loader = yaml.SafeLoader

# Felder mit freiem Text, die das YAML erfahrungsgemäß brechen können
_FREE_TEXT_KEYS = (
    "UserName",
    "TeamName",
    "AbbrevName",
    "Initials",
    "CarDesignStr",
    "HelmetDesignStr",
    "SuitDesignStr",
    "CarNumberDesignStr",
    "CarSponsor_1",
    "CarSponsor_2",
    "ClubName",
    "DivisionName",
    "TrackDisplayName",
    "TrackDisplayShortName",
    "TrackConfigName",
    "SeriesName",
    "EventName",
)
_FREE_TEXT_RE = re.compile(r"^(\s*(?:" + "|".join(_FREE_TEXT_KEYS) + r"): )(.*)$", re.MULTILINE)


def _quote_free_text(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        value = m.group(2).strip()
        if value.startswith(("'", '"')) or value == "":
            return m.group(0)
        return f"{m.group(1)}'{value.replace(chr(39), chr(39) * 2)}'"

    return _FREE_TEXT_RE.sub(repl, text)


def decode_session_info(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("latin-1")


def parse_session_info(text: str) -> dict[str, Any]:
    """YAML parsen; bei Fehlern Freitextfelder quoten und erneut versuchen."""
    for candidate in (text, _quote_free_text(text)):
        try:
            data = yaml.load(candidate, Loader=_Loader)
            if isinstance(data, dict):
                return data
        except yaml.YAMLError:
            continue
    # Letzter Ausweg: nur die Blöcke laden, die wir wirklich brauchen
    result: dict[str, Any] = {}
    for block in ("WeekendInfo", "SessionInfo", "DriverInfo", "CarSetup", "SplitTimeInfo"):
        m = re.search(rf"^{block}:\n(?:(?:[ \t].*)?\n)*", text, re.MULTILINE)
        if not m:
            continue
        try:
            part = yaml.load(_quote_free_text(m.group(0)), Loader=_Loader)
            if isinstance(part, dict):
                result.update(part)
        except yaml.YAMLError:
            pass
    return result

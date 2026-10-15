"""Car-Setup aus der Session-Info (Block `CarSetup`) lesen und vergleichen.

iRacing liefert Setup-Werte als Text mit Einheit, z. B. "180 N/mm",
"-3.2 deg", "26.5 kPa", "5 clicks", "Soft". Die Struktur (Kategorien wie
TiresAero, Chassis, Dampers ...) unterscheidet sich je Auto; wir machen sie
deshalb flach: "Chassis.LeftFront.SpringRate" -> SetupValue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator

_NUM_RE = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*(.*?)\s*$")

# Schlüssel, die keine Einstellungen sind (Anzeige-/Rechenwerte von iRacing)
READ_ONLY_HINTS = (
    "CornerWeight",
    "RideHeight",  # bei vielen Autos berechnet, nicht direkt einstellbar
    "LastHotPressure",
    "LastTempsOMI",
    "LastTempsIMO",
    "TreadRemaining",
    "UpdateCount",
    "ShockDefl",
    "SpringDefl",
    "TorsionBarDefl",
)


@dataclass(frozen=True)
class SetupValue:
    path: str
    raw: str
    value: float | None
    unit: str

    @property
    def category(self) -> str:
        return self.path.split(".", 1)[0]

    @property
    def key(self) -> str:
        return self.path.rsplit(".", 1)[-1]

    @property
    def likely_read_only(self) -> bool:
        return any(h in self.key for h in READ_ONLY_HINTS)


def parse_value(path: str, raw: Any) -> SetupValue:
    text = str(raw).strip()
    m = _NUM_RE.match(text)
    if m:
        return SetupValue(path, text, float(m.group(1).replace(",", ".")), m.group(2))
    return SetupValue(path, text, None, "")


def _walk(node: Any, prefix: str) -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{prefix}[{i}]")
    else:
        yield prefix, node


@dataclass
class CarSetup:
    values: dict[str, SetupValue]
    update_count: int | None = None

    @classmethod
    def from_session_info(cls, session_info: dict[str, Any]) -> "CarSetup":
        block = session_info.get("CarSetup") or {}
        update = block.get("UpdateCount") if isinstance(block, dict) else None
        values = {
            p: parse_value(p, v)
            for p, v in _walk(block, "")
            if p != "UpdateCount" and v is not None
        }
        return cls(values=values, update_count=update)

    def __len__(self) -> int:
        return len(self.values)

    def __getitem__(self, path: str) -> SetupValue:
        return self.values[path]

    def find(self, *fragments: str) -> list[SetupValue]:
        """Alle Werte, deren Pfad alle Fragmente enthält (Groß/Klein egal)."""
        frags = [f.lower() for f in fragments]
        return [v for p, v in self.values.items() if all(f in p.lower() for f in frags)]

    def categories(self) -> list[str]:
        return sorted({v.category for v in self.values.values()})


@dataclass(frozen=True)
class SetupChange:
    path: str
    before: str | None
    after: str | None
    delta: float | None
    unit: str


def diff(a: CarSetup, b: CarSetup, *, include_read_only: bool = False) -> list[SetupChange]:
    """Unterschiede von Setup a nach Setup b."""
    out: list[SetupChange] = []
    for path in sorted(set(a.values) | set(b.values)):
        va, vb = a.values.get(path), b.values.get(path)
        if va and vb and va.raw == vb.raw:
            continue
        ref = vb or va
        assert ref is not None
        if ref.likely_read_only and not include_read_only:
            continue
        delta = None
        if va and vb and va.value is not None and vb.value is not None and va.unit == vb.unit:
            delta = round(vb.value - va.value, 6)
        out.append(SetupChange(path, va.raw if va else None, vb.raw if vb else None, delta, ref.unit))
    return out

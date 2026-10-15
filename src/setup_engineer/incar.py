"""Einstellungen, die während der Fahrt im Auto verstellt werden (dc*-Kanäle).

Erkenntnis aus echten Daten: Der CarSetup-Block in der IBT-Datei ist der Stand
aus der Garage. Wird z. B. der Front-Stabi im Auto von 1 auf 3 gestellt, steht
im Setup weiterhin 1 – nur der Kanal dcAntiRollFront zeigt den echten Wert.
Wir ermitteln deshalb das tatsächlich gefahrene Setup je Runde.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .ibt.reader import IbtFile
from .segment.laps import LapSet

# dc-Kanal -> (Klartext, Fragmente zum Finden des Garage-Werts im Setup)
LABELS: dict[str, tuple[str, tuple[str, ...]]] = {
    "dcAntiRollFront": ("Stabilisator vorne", ("Front", "Arb")),
    "dcAntiRollRear": ("Stabilisator hinten", ("Rear", "Arb")),
    "dcBrakeBias": ("Bremsbalance", ("BrakePressureBias",)),
    "dcBrakeBiasFine": ("Bremsbalance fein", ()),
    "dcPeakBrakeBias": ("Bremsbalance Spitze", ()),
    "dcBrakeMisc": ("Bremsmigration", ("BrakeBiasMigration",)),
    "dcABS": ("ABS", ("Abs",)),
    "dcTractionControl": ("Traktionskontrolle 1", ()),
    "dcTractionControl2": ("Traktionskontrolle 2", ()),
    "dcTractionControl3": ("Traktionskontrolle 3", ()),
    "dcEnginePower": ("Motorleistung", ()),
    "dcThrottleShape": ("Gaspedal-Kennlinie", ()),
    "dcFuelMixture": ("Gemisch", ()),
    "dcMGUKDeployMode": ("MGU-K Modus", ()),
    "dcMGUKRegenGain": ("MGU-K Rekuperation", ()),
    "dcDiffEntry": ("Differenzial Einlenken", ()),
    "dcDiffMiddle": ("Differenzial Mitte", ()),
    "dcDiffExit": ("Differenzial Ausgang", ()),
}


def _numeric_dc_channels(ibt: IbtFile) -> list[str]:
    return [
        n
        for n, vh in ibt.var_headers.items()
        if n.startswith("dc") and vh.type in (2, 4, 5) and vh.count == 1
    ]


def label(channel: str) -> str:
    return LABELS.get(channel, (channel[2:], ()))[0]


@dataclass
class InCarSetting:
    channel: str
    label: str
    per_lap: dict[int, float]  # Rundennummer -> Wert (Median) für gültige Runden
    session_values: list[float]  # alle vorkommenden Werte in der Session
    mixed_laps: set[int] = field(default_factory=set)  # Runden, in denen umgestellt wurde

    @property
    def constant_in_valid_laps(self) -> bool:
        return len(set(self.per_lap.values())) <= 1

    @property
    def effective(self) -> float | None:
        """Wert, der in den gewerteten Runden (überwiegend) gefahren wurde."""
        if not self.per_lap:
            return None
        vals, counts = np.unique(list(self.per_lap.values()), return_counts=True)
        return float(vals[np.argmax(counts)])

    @property
    def changed_in_session(self) -> bool:
        return len(self.session_values) > 1


def in_car_settings(laps: LapSet) -> list[InCarSetting]:
    ibt = laps.ibt
    out = []
    for ch in _numeric_dc_channels(ibt):
        x = ibt.get(ch)
        per_lap = {lap.number: round(float(np.nanmedian(x[lap.slice])), 3) for lap in laps.valid}
        mixed = {lap.number for lap in laps.valid if np.nanmax(x[lap.slice]) - np.nanmin(x[lap.slice]) > 1e-6}
        session_values = sorted({round(float(v), 3) for v in np.unique(x[np.isfinite(x)])})
        out.append(InCarSetting(ch, label(ch), per_lap, session_values, mixed))
    return out


def changed_settings(settings: list[InCarSetting]) -> list[InCarSetting]:
    """Nur Einstellungen, die in der Session verstellt wurden."""
    return [s for s in settings if s.changed_in_session]


def lap_groups(settings: list[InCarSetting]) -> dict[tuple[tuple[str, float], ...], list[int]]:
    """Gültige Runden nach Kombination der im Auto verstellten Werte gruppieren.

    Mehr als eine Gruppe = innerhalb der gewerteten Runden wurde verstellt
    -> Vergleich unter (nahezu) gleichen Bedingungen möglich.
    """
    varying = [s for s in settings if not s.constant_in_valid_laps or s.mixed_laps]
    if not varying:
        return {}
    mixed = set().union(*(s.mixed_laps for s in varying))
    groups: dict[tuple[tuple[str, float], ...], list[int]] = {}
    laps_numbers = sorted(varying[0].per_lap)
    for n in laps_numbers:
        if n in mixed:
            continue  # Umstell-Runde: zwei Einstellungen in einer Runde -> nicht werten
        key = tuple((s.label, s.per_lap[n]) for s in varying)
        groups.setdefault(key, []).append(n)
    return groups if len(groups) > 1 else {}

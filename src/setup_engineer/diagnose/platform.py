"""Plattform-Diagnose: Ride Height, Aufsetzer, Bump-Stop-Kontakt, Dämpfer.

Einheiten in iRacing: Ride Height und Federweg in Metern, Federweg-
Geschwindigkeit in m/s. Wir rechnen intern in mm bzw. mm/s.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from ..segment.corners import Corner
from ..segment.laps import LapSet
from ..setup import CarSetup
from .balance import phase_mask

WHEELS = ("LF", "RF", "LR", "RR")
WHEEL_SETUP_NAME = {"LF": "LeftFront", "RF": "RightFront", "LR": "LeftRear", "RR": "RightRear"}

BOTTOMING_MM = 3.0  # vorläufig; an echten Daten kalibrieren
LS_LIMIT_MMS = 50.0  # Grenze Low-/High-Speed-Dämpfung (Kolbengeschwindigkeit)
HIST_EDGES_MMS = np.arange(-300, 301, 25)


@dataclass
class RideHeightRow:
    zone: str  # Kurve/Phase oder "Geraden"
    front_mm: float
    rear_mm: float
    rake_mm: float
    min_mm: float
    bottoming_laps: int


@dataclass
class DamperStats:
    wheel: str
    source: str  # Kanalname
    bump_share: float  # Anteil Einfedern (Geschw. > 0)
    ls_share: float  # Anteil |v| < LS_LIMIT
    p95_bump_mms: float
    p95_rebound_mms: float
    histogram: list[int] = field(default_factory=list)

    @property
    def symmetry(self) -> float:
        """1.0 = Ein-/Ausfedern gleich verteilt."""
        b, r = self.bump_share, 1 - self.bump_share
        return min(b, r) / max(b, r) if max(b, r) > 0 else float("nan")


@dataclass
class BumpStopRow:
    wheel: str
    gap_mm: float
    max_defl_mm: float
    contact_share: float  # Anteil der Samples mit Kontakt
    note: str = "Annahme: Federweg und Gap im gleichen Bezug – an echten Daten prüfen"


@dataclass
class PlatformResult:
    ride_height: list[RideHeightRow]
    dampers: list[DamperStats]
    bump_stops: list[BumpStopRow]
    notes: list[str]


def _rh_channel(laps: LapSet, wheel: str) -> str | None:
    name = f"{wheel}rideHeight"
    return name if laps.ibt.has(name) else None


def analyze_ride_height(laps: LapSet, corners: list[Corner]) -> tuple[list[RideHeightRow], list[str]]:
    notes: list[str] = []
    chans = {w: _rh_channel(laps, w) for w in WHEELS}
    if not all(chans.values()):
        missing = [w for w, c in chans.items() if not c]
        notes.append(f"Ride-Height-Kanäle fehlen für {', '.join(missing)} – Plattformanalyse eingeschränkt")
        if not any(chans.values()):
            return [], notes

    stacks = {w: laps.stack(c) * 1000.0 for w, c in chans.items() if c}
    front = np.nanmean([stacks[w] for w in ("LF", "RF") if w in stacks], axis=0)
    rear = np.nanmean([stacks[w] for w in ("LR", "RR") if w in stacks], axis=0)
    lowest = np.nanmin(np.stack(list(stacks.values())), axis=0)

    zones: list[tuple[str, np.ndarray]] = []
    in_corner = np.zeros(laps.grid.size, dtype=bool)
    for c in corners:
        for phase, (a, b) in c.phase_bounds().items():
            m = phase_mask(laps.grid, a, b)
            in_corner |= m
            zones.append((f"{c.name} {phase}", m))
    zones.append(("Geraden", ~in_corner))

    rows = []
    for label, m in zones:
        if not m.any():
            continue
        f, r, lo = front[:, m], rear[:, m], lowest[:, m]
        rows.append(
            RideHeightRow(
                zone=label,
                front_mm=float(np.nanmedian(f)),
                rear_mm=float(np.nanmedian(r)),
                rake_mm=float(np.nanmedian(r - f)),
                min_mm=float(np.nanmin(lo)),
                bottoming_laps=int(np.sum(np.nanmin(lo, axis=1) < BOTTOMING_MM)),
            )
        )
    return rows, notes


def _valid_samples(laps: LapSet, name: str) -> tuple[np.ndarray, str]:
    """Rohdaten (volle Auflösung) aller gültigen Runden; bevorzugt 360-Hz-Kanal."""
    ibt = laps.ibt
    hi = f"{name}_ST"
    src = hi if ibt.has(hi) else name
    parts = []
    for lap in laps.valid:
        arr = ibt.channel(src)[lap.slice]
        parts.append(arr.reshape(-1))
    return (np.concatenate(parts) if parts else np.empty(0)), src


def analyze_dampers(laps: LapSet) -> list[DamperStats]:
    out = []
    for w in WHEELS:
        if not laps.ibt.has(f"{w}shockVel"):
            continue
        v, src = _valid_samples(laps, f"{w}shockVel")
        v = v[np.isfinite(v)] * 1000.0
        if v.size == 0:
            continue
        bump, reb = v[v > 0], -v[v < 0]
        hist, _ = np.histogram(np.clip(v, HIST_EDGES_MMS[0], HIST_EDGES_MMS[-1]), bins=HIST_EDGES_MMS)
        out.append(
            DamperStats(
                wheel=w,
                source=src,
                bump_share=float(bump.size / v.size),
                ls_share=float(np.mean(np.abs(v) < LS_LIMIT_MMS)),
                p95_bump_mms=float(np.percentile(bump, 95)) if bump.size else 0.0,
                p95_rebound_mms=float(np.percentile(reb, 95)) if reb.size else 0.0,
                histogram=hist.tolist(),
            )
        )
    return out


_GAP_RE = re.compile(r"(bump.?(rubber|stop)|packer).*gap|gap.*(bump|packer)", re.IGNORECASE)


def analyze_bump_stops(laps: LapSet, setup: CarSetup) -> tuple[list[BumpStopRow], list[str]]:
    rows, notes = [], []
    for w in WHEELS:
        corner_name = WHEEL_SETUP_NAME[w]
        gaps = [
            v
            for v in setup.values.values()
            if corner_name.lower() in v.path.lower() and _GAP_RE.search(v.key) and v.value is not None
        ]
        if not gaps or not laps.ibt.has(f"{w}shockDefl"):
            continue
        gap = gaps[0]
        gap_mm = gap.value * (25.4 if gap.unit.strip() == "in" else 1.0)
        d, _ = _valid_samples(laps, f"{w}shockDefl")
        d = d[np.isfinite(d)] * 1000.0
        if d.size == 0:
            continue
        rows.append(
            BumpStopRow(
                wheel=w,
                gap_mm=gap_mm,
                max_defl_mm=float(d.max()),
                contact_share=float(np.mean(d >= gap_mm)),
            )
        )
    if not rows:
        notes.append("Kein Bump-Stop-/Packer-Gap im Setup gefunden oder Federweg-Kanal fehlt")
    return rows, notes


def analyze_platform(laps: LapSet, corners: list[Corner], setup: CarSetup) -> PlatformResult:
    rh, n1 = analyze_ride_height(laps, corners)
    bs, n2 = analyze_bump_stops(laps, setup)
    return PlatformResult(ride_height=rh, dampers=analyze_dampers(laps), bump_stops=bs, notes=n1 + n2)

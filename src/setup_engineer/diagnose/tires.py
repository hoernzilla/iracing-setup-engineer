"""Reifen sowie Schlupf (Durchdrehen/Blockieren) aus den Radgeschwindigkeiten.

Erkenntnisse aus echten Daten (Porsche 963 GTP):
* Karkassentemperaturen (*tempCL/CM/CR) und Verschleiß (*wear*) werden nur in
  der Box aktualisiert – während der Fahrt konstant.
* Reifendruck (*pressure) und Oberflächentemperatur (*tempL) laufen live.
* Radgeschwindigkeiten (*speed) liegen vor -> Schlupf direkt messbar.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..segment.corners import Corner
from ..segment.laps import LapSet
from .balance import phase_mask

WHEELS = ("LF", "RF", "LR", "RR")
SPIN_SLIP = 0.05  # Antriebsrad > 5 % schneller als frei rollend
LOCK_SLIP = -0.10  # Rad > 10 % langsamer als frei rollend


@dataclass
class TireLap:
    lap: int
    pressure_kpa: dict[str, float]
    surface_c: dict[str, float]


@dataclass
class TireResult:
    cold_kpa: dict[str, float]
    laps: list[TireLap]
    stable_from_lap: int | None
    pit_only: list[str]

    @property
    def last(self) -> TireLap | None:
        return self.laps[-1] if self.laps else None


@dataclass
class SlipRow:
    corner: str
    spin_exit: float | None  # Anteil der Ausgangsphase mit Durchdrehen (Hinterachse)
    lock_brake: float | None  # Anteil der Bremsphase mit blockierendem Rad
    lock_wheels: str


def _constant_during_laps(laps: LapSet, name: str) -> bool:
    x = laps.ibt.get(name)
    vals = np.concatenate([x[lap.slice] for lap in laps.valid])
    return bool(np.nanstd(vals) < 1e-6)


def analyze_tires(laps: LapSet) -> TireResult | None:
    ibt = laps.ibt
    if not laps.valid or not any(ibt.has(f"{w}pressure") for w in WHEELS):
        return None
    pit_only = [
        n
        for n in ibt.channel_names()
        if any(n.startswith(w) for w in WHEELS) and ("temp" in n or "wear" in n) and _constant_during_laps(laps, n)
    ]
    cold = {w: float(np.nanmedian(ibt.get(f"{w}coldPressure"))) for w in WHEELS if ibt.has(f"{w}coldPressure")}
    rows = []
    tail = ibt.tick_rate * 2
    for lap in laps.valid:
        end = slice(max(lap.end - tail, lap.start), lap.end)
        p = {w: float(np.nanmedian(ibt.get(f"{w}pressure")[end])) for w in WHEELS if ibt.has(f"{w}pressure")}
        surf = {}
        for w in WHEELS:
            name = f"{w}tempL" if ibt.has(f"{w}tempL") else f"{w}tempM"
            if ibt.has(name) and name not in pit_only:
                surf[w] = float(np.nanmean(ibt.get(name)[lap.slice]))
        rows.append(TireLap(lap.number, p, surf))

    stable = None
    for i in range(len(rows) - 1):
        a, b = rows[i].pressure_kpa, rows[i + 1].pressure_kpa
        if a and all(abs(b[w] - a[w]) < 1.0 for w in a):
            stable = rows[i].lap
            break
    return TireResult(cold_kpa=cold, laps=rows, stable_from_lap=stable, pit_only=pit_only)


def _slip(laps: LapSet) -> dict[str, np.ndarray] | None:
    """Schlupf je Rad auf dem Distanzraster, auf frei rollend kalibriert."""
    ibt = laps.ibt
    if not all(ibt.has(f"{w}speed") for w in WHEELS):
        return None
    v = laps.stack("Speed")
    acc = np.abs(laps.stack("LongAccel")) if ibt.has("LongAccel") else np.zeros_like(v)
    brake = laps.stack("Brake") if ibt.has("Brake") else np.zeros_like(v)
    thr = laps.stack("Throttle") if ibt.has("Throttle") else np.zeros_like(v)
    free = (v > 20) & (acc < 1.5) & (brake < 0.02) & (thr < 0.6)
    out = {}
    for w in WHEELS:
        ratio = laps.stack(f"{w}speed") / np.maximum(v, 1.0)
        base = np.nanmedian(ratio[free]) if free.sum() > 50 else np.nanmedian(ratio[v > 20])
        out[w] = ratio / base - 1.0
    return out


def analyze_slip(laps: LapSet, corners: list[Corner]) -> list[SlipRow]:
    slip = _slip(laps)
    if slip is None or not corners:
        return []
    ibt = laps.ibt
    v = laps.stack("Speed")
    brake = laps.stack("Brake") if ibt.has("Brake") else np.zeros_like(v)
    thr = laps.stack("Throttle") if ibt.has("Throttle") else np.zeros_like(v)
    rear_spin = np.maximum(slip["LR"], slip["RR"])
    rows = []
    for c in corners:
        ph = c.phase_bounds()
        exit_m = phase_mask(laps.grid, *ph["Ausgang"]) if "Ausgang" in ph else None
        brake_m = phase_mask(laps.grid, c.brake_start, c.apex)
        spin = None
        if exit_m is not None and exit_m.any():
            on = (thr[:, exit_m] > 0.2) & (v[:, exit_m] > 10)
            spin = float(np.mean(rear_spin[:, exit_m][on] > SPIN_SLIP)) if on.any() else 0.0
        lock, who = None, ""
        if brake_m.any():
            on = (brake[:, brake_m] > 0.1) & (v[:, brake_m] > 10)
            if on.any():
                per = {w: float(np.mean(slip[w][:, brake_m][on] < LOCK_SLIP)) for w in WHEELS}
                lock = max(per.values())
                who = ", ".join(w for w, x in per.items() if x > 0.02)
        rows.append(SlipRow(c.name, spin, lock, who))
    return rows

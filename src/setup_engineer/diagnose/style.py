"""Fahrstil-Profil und Brems-Kennzahlen pro Kurve.

Das Profil ist die Grundlage dafür, ein Setup um den Fahrer herum zu bauen
(statt eines Durchschnitts-Setups für einen Esportler).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..segment.corners import Corner
from ..segment.laps import LapSet
from .balance import phase_mask


@dataclass
class CornerBraking:
    corner: str
    peak_brake: float  # 0..1
    trail_share: float  # Anteil der Einlenkphase mit Bremse > 5 %
    abs_share: float | None  # Anteil der Bremsphase mit ABS-Eingriff
    min_speed_kmh: float
    min_speed_spread_kmh: float  # Streuung über die Runden
    full_throttle_after_apex_pct: float | None  # Distanz (% der Kurve) bis Vollgas


@dataclass
class StyleProfile:
    trail_braking: float
    peak_brake: float
    abs_usage: float | None
    consistency_kmh: float  # mittlere Streuung der Scheitelgeschwindigkeit
    corners: list[CornerBraking]


def analyze_style(laps: LapSet, corners: list[Corner]) -> StyleProfile | None:
    if not laps.valid or not corners:
        return None
    ibt = laps.ibt
    brake = laps.stack("Brake") if ibt.has("Brake") else None
    throttle = laps.stack("Throttle") if ibt.has("Throttle") else None
    speed = laps.stack("Speed") * 3.6
    absact = laps.stack("BrakeABSactive") if ibt.has("BrakeABSactive") else None

    rows = []
    for c in corners:
        ph = c.phase_bounds()
        bm = phase_mask(laps.grid, *ph["Bremsen"]) if "Bremsen" in ph else None
        em = phase_mask(laps.grid, c.start, c.apex)
        cm = phase_mask(laps.grid, c.start, c.end)
        am = phase_mask(laps.grid, c.apex, c.end)

        peak = float(np.nanmedian(np.nanmax(brake[:, bm | em], axis=1))) if brake is not None and bm is not None else 0.0
        trail = float(np.nanmean(brake[:, em] > 0.05)) if brake is not None and em.any() else 0.0
        abs_share = None
        if absact is not None and bm is not None and bm.any():
            on = brake[:, bm] > 0.05 if brake is not None else np.ones_like(absact[:, bm], dtype=bool)
            abs_share = float(np.mean(absact[:, bm][on] > 0.5)) if on.any() else 0.0
        mins = np.nanmin(speed[:, cm], axis=1)
        ft = None
        if throttle is not None and am.any():
            idx = np.flatnonzero(am)
            first_full = []
            for row in throttle[:, idx]:
                hit = np.flatnonzero(row > 0.98)
                first_full.append(hit[0] / len(idx) * 100 if hit.size else 100.0)
            ft = float(np.median(first_full))
        rows.append(
            CornerBraking(
                corner=c.name,
                peak_brake=peak,
                trail_share=trail,
                abs_share=abs_share,
                min_speed_kmh=float(np.median(mins)),
                min_speed_spread_kmh=float(np.std(mins)),
                full_throttle_after_apex_pct=ft,
            )
        )
    braked = [r for r in rows if r.peak_brake > 0.2]
    abs_vals = [r.abs_share for r in braked if r.abs_share is not None]
    return StyleProfile(
        trail_braking=float(np.mean([r.trail_share for r in braked])) if braked else 0.0,
        peak_brake=float(np.mean([r.peak_brake for r in braked])) if braked else 0.0,
        abs_usage=float(np.mean(abs_vals)) if abs_vals else None,
        consistency_kmh=float(np.mean([r.min_speed_spread_kmh for r in rows])),
        corners=rows,
    )

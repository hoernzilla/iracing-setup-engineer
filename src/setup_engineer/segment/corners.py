"""Kurven und Kurvenphasen automatisch aus der Telemetrie erkennen.

Keine Streckendatenbank nötig: Die Krümmung der Fahrlinie (Gierrate / Tempo)
wird über alle gültigen Runden gemittelt. Zusammenhängende Bereiche mit
ausreichend Krümmung sind Kurven; der Punkt minimaler Geschwindigkeit ist
der Scheitel.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .laps import LapSet

PHASES = ("Bremsen", "Einlenken", "Scheitel", "Ausgang")


@dataclass(frozen=True)
class CornerConfig:
    enter_curvature: float = 1 / 400  # 1/m  (Radius < 400 m)
    peak_curvature: float = 1 / 250  # Kurve muss mind. einmal Radius < 250 m haben
    merge_gap_m: float = 30.0  # Lücken gleicher Richtung zusammenfassen
    min_length_m: float = 20.0
    smooth_m: float = 15.0
    brake_threshold: float = 0.05
    max_brake_lookback_m: float = 400.0
    apex_window_frac: float = 0.15  # Scheitelphase = ±15 % der Kurvenlänge um den Scheitel
    min_speed_ms: float = 10.0


@dataclass(frozen=True)
class Corner:
    index: int
    direction: str  # "links" / "rechts"
    brake_start: float  # LapDistPct, = start wenn nicht gebremst wird
    start: float
    apex: float
    end: float
    min_speed_kmh: float
    min_radius_m: float

    @property
    def name(self) -> str:
        return f"T{self.index}"

    def phase_bounds(self, apex_window_frac: float = 0.15) -> dict[str, tuple[float, float]]:
        w = max((self.end - self.start) * apex_window_frac, 1e-4)
        a0, a1 = max(self.start, self.apex - w), min(self.end, self.apex + w)
        bounds = {
            "Bremsen": (self.brake_start, self.start),
            "Einlenken": (self.start, a0),
            "Scheitel": (a0, a1),
            "Ausgang": (a1, self.end),
        }
        return {k: v for k, v in bounds.items() if v[1] > v[0]}


def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    if n <= 1:
        return x
    k = np.ones(n) / n
    # zirkulär glätten (Start/Ziel)
    padded = np.concatenate((x[-n:], x, x[:n]))
    return np.convolve(padded, k, mode="same")[n:-n]


def curvature_profile(laps: LapSet) -> np.ndarray:
    """Median-Krümmung (1/m, Vorzeichen = Richtung) auf dem Distanzraster."""
    ibt = laps.ibt
    speed = laps.stack("Speed")
    if ibt.has("YawRate"):
        kappa = laps.stack("YawRate") / np.maximum(speed, 1.0)
    elif ibt.has("LatAccel"):
        kappa = laps.stack("LatAccel") / np.maximum(speed, 1.0) ** 2
    else:
        raise ValueError("Weder YawRate noch LatAccel vorhanden – Kurvenerkennung unmöglich")
    kappa[speed < CornerConfig.min_speed_ms] = np.nan
    return np.nanmedian(kappa, axis=0)


def detect_corners(laps: LapSet, cfg: CornerConfig = CornerConfig()) -> list[Corner]:
    if not laps.valid:
        return []
    length = laps.ibt.track_length_m or 4000.0
    m_per_pt = length / laps.grid.size
    n_smooth = max(1, int(round(cfg.smooth_m / m_per_pt)))

    kappa = _smooth(np.nan_to_num(curvature_profile(laps)), n_smooth)
    speed = np.nanmedian(laps.stack("Speed"), axis=0)
    brake = np.nanmedian(laps.stack("Brake"), axis=0) if laps.ibt.has("Brake") else np.zeros_like(speed)

    sign = np.sign(kappa)
    active = np.abs(kappa) >= cfg.enter_curvature

    # Bereiche finden
    regions: list[list[int]] = []
    i, n = 0, active.size
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j] and sign[j] == sign[i]:
                j += 1
            regions.append([i, j, int(sign[i])])
            i = j
        else:
            i += 1

    # Kleine Lücken gleicher Richtung schließen
    gap_pts = int(cfg.merge_gap_m / m_per_pt)
    merged: list[list[int]] = []
    for r in regions:
        if merged and r[2] == merged[-1][2] and r[0] - merged[-1][1] <= gap_pts:
            merged[-1][1] = r[1]
        else:
            merged.append(r)

    corners: list[Corner] = []
    min_pts = int(cfg.min_length_m / m_per_pt)
    prev_end = 0
    for s, e, sgn in merged:
        if e - s < min_pts or np.abs(kappa[s:e]).max() < cfg.peak_curvature:
            continue
        apex = s + int(np.nanargmin(speed[s:e]))
        # Bremsbeginn: letzte Bremszone vor dem Scheitel, nicht weiter zurück als
        # bis zum Ende der vorigen Kurve bzw. max_brake_lookback_m
        limit = max(prev_end, s - int(cfg.max_brake_lookback_m / m_per_pt))
        braking = np.flatnonzero(brake[limit : apex + 1] > cfg.brake_threshold)
        b = s
        if braking.size:
            k = limit + int(braking[-1])
            while k > limit and brake[k - 1] > cfg.brake_threshold:
                k -= 1
            b = min(k, s)
        prev_end = e
        corners.append(
            Corner(
                index=len(corners) + 1,
                direction="links" if sgn > 0 else "rechts",
                brake_start=float(laps.grid[b]),
                start=float(laps.grid[s]),
                apex=float(laps.grid[apex]),
                end=float(laps.grid[min(e, laps.grid.size - 1)]),
                min_speed_kmh=float(speed[apex] * 3.6),
                min_radius_m=float(1.0 / max(np.abs(kappa[s:e]).max(), 1e-9)),
            )
        )
    return corners

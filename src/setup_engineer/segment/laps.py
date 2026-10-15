"""Runden aus einer IBT-Datei schneiden, bewerten und auf ein Distanzraster legen."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..ibt.format import TRK_OFF_TRACK
from ..ibt.reader import IbtFile

GRID_POINTS = 2000  # Auflösung des gemeinsamen Distanzrasters (0..1 LapDistPct)


@dataclass
class Lap:
    number: int
    start: int  # Index erster Datensatz (inklusive)
    end: int  # Index letzter Datensatz (exklusive)
    time_s: float
    valid: bool = True
    reasons: list[str] = field(default_factory=list)
    fuel_start_l: float | None = None
    track_temp_c: float | None = None
    air_temp_c: float | None = None

    def invalidate(self, reason: str) -> None:
        self.valid = False
        if reason not in self.reasons:
            self.reasons.append(reason)

    @property
    def slice(self) -> slice:
        return slice(self.start, self.end)


@dataclass
class LapSet:
    ibt: IbtFile
    laps: list[Lap]
    grid: np.ndarray  # LapDistPct-Raster

    _cache: dict[str, np.ndarray] = field(default_factory=dict, repr=False)

    def _cache_1d(self, name: str) -> np.ndarray:
        """Kanäle nur einmal aus der (großen) Datei lesen."""
        if name not in self._cache:
            self._cache[name] = self.ibt.get(name)
        return self._cache[name]

    @property
    def valid(self) -> list[Lap]:
        return [lap for lap in self.laps if lap.valid]

    @property
    def best(self) -> Lap | None:
        v = self.valid
        return min(v, key=lambda lap: lap.time_s) if v else None

    def resample(self, lap: Lap, name: str) -> np.ndarray:
        """Kanal einer Runde auf das Distanzraster interpolieren."""
        pct = _monotonic_pct(self._cache_1d("LapDistPct")[lap.slice])
        values = self._cache_1d(name)[lap.slice]
        ok = np.isfinite(values)
        if ok.sum() < 2:
            return np.full_like(self.grid, np.nan)
        return np.interp(self.grid, pct[ok], values[ok])

    def stack(self, name: str, laps: list[Lap] | None = None) -> np.ndarray:
        """Matrix (Runden × Raster) für einen Kanal."""
        laps = self.valid if laps is None else laps
        if not laps:
            return np.empty((0, self.grid.size))
        return np.vstack([self.resample(lap, name) for lap in laps])


def _monotonic_pct(pct: np.ndarray) -> np.ndarray:
    """LapDistPct kann am Start minimal negativ sein oder zurückspringen."""
    pct = np.clip(pct, 0.0, 1.0)
    return np.maximum.accumulate(pct)


def split_laps(ibt: IbtFile, *, slow_factor: float = 1.07) -> LapSet:
    if not ibt.has("Lap") or not ibt.has("LapDistPct"):
        raise ValueError("Kanäle Lap/LapDistPct fehlen – Runden nicht bestimmbar")

    lap_no = ibt.channel("Lap", dtype=np.int64)
    pct = ibt.channel("LapDistPct")
    t = ibt.get("SessionTime")
    if not np.isfinite(t).all():
        t = np.arange(ibt.record_count) / ibt.tick_rate

    boundaries = np.flatnonzero(np.diff(lap_no) != 0) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [ibt.record_count]))

    on_pit = ibt.get("OnPitRoad", 0.0)
    surface = ibt.get("PlayerTrackSurface", 3.0)
    fuel = ibt.get("FuelLevel")
    track_temp = ibt.get("TrackTempCrew") if ibt.has("TrackTempCrew") else ibt.get("TrackTemp")
    air_temp = ibt.get("AirTemp")
    last_lap_time = ibt.get("LapLastLapTime")

    laps: list[Lap] = []
    for s, e in zip(starts, ends):
        if e - s < ibt.tick_rate * 5:  # Fragmente < 5 s ignorieren
            continue
        seg_pct = pct[s:e]
        time_s = _crossing_time(t, pct, s, e)
        # LapLastLapTime wird kurz nach der Linie aktualisiert: bevorzugen, wenn plausibel
        probe = min(e + ibt.tick_rate * 2, ibt.record_count - 1)
        if e < ibt.record_count and np.isfinite(last_lap_time[probe]):
            official = float(last_lap_time[probe])
            if official > 0 and abs(official - time_s) < 0.25:
                time_s = official

        lap = Lap(
            number=int(lap_no[s]),
            start=int(s),
            end=int(e),
            time_s=float(time_s),
            fuel_start_l=_first_finite(fuel[s:e]),
            track_temp_c=_nanmean(track_temp[s:e]),
            air_temp_c=_nanmean(air_temp[s:e]),
        )
        if seg_pct.min() > 0.05 or seg_pct.max() < 0.95:
            lap.invalidate("unvollständig")
        if e == ibt.record_count:
            lap.invalidate("unvollständig")
        if np.nanmax(on_pit[s:e]) > 0:
            lap.invalidate("Boxengasse (Out-/Inlap)")
        off = np.sum(surface[s:e] == TRK_OFF_TRACK) / ibt.tick_rate
        if off > 0.2:
            lap.invalidate(f"neben der Strecke ({off:.1f} s)")
        laps.append(lap)

    # Langsame Ausreißer (Verkehr, Fehler) relativ zum Median
    times = [lap.time_s for lap in laps if lap.valid]
    if len(times) >= 3:
        median = float(np.median(times))
        for lap in laps:
            if lap.valid and lap.time_s > median * slow_factor:
                lap.invalidate(f"Ausreißer (> {round((slow_factor - 1) * 100)} % über Median)")

    grid = np.linspace(0.0, 1.0, GRID_POINTS, endpoint=False)
    return LapSet(ibt=ibt, laps=laps, grid=grid)


def _crossing_time(t: np.ndarray, pct: np.ndarray, s: int, e: int) -> float:
    """Rundenzeit mit Interpolation des Linienübertritts an beiden Enden."""

    def cross(i: int) -> float:
        # Übergang zwischen i-1 (pct ~1) und i (pct ~0)
        if i <= 0 or i >= len(t):
            return float(t[min(max(i, 0), len(t) - 1)])
        p0, p1 = pct[i - 1], pct[i]
        span = (1.0 - p0) + p1
        frac = (1.0 - p0) / span if span > 1e-9 else 0.0
        return float(t[i - 1] + frac * (t[i] - t[i - 1]))

    return cross(e) - cross(s)


def _first_finite(a: np.ndarray) -> float | None:
    idx = np.flatnonzero(np.isfinite(a))
    return float(a[idx[0]]) if idx.size else None


def _nanmean(a: np.ndarray) -> float | None:
    a = a[np.isfinite(a)]
    return float(a.mean()) if a.size else None

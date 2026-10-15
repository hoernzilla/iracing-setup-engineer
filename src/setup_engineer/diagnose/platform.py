"""Plattform-Diagnose: Ride Height, Bodenkontakt, Federweg, Aero-Plattform, Dämpfer.

Einheiten in iRacing: Ride Height und Federweg in Metern, Federweg-
Geschwindigkeit in m/s. Intern rechnen wir in mm bzw. mm/s.

Erkenntnisse aus echten Daten (Porsche 963 GTP):
* Federweg-Kanäle (*shockDefl) liegen 360 Hz als 6er-Arrays vor und stimmen
  im Stand exakt mit den Setup-Anzeigen "statisch / maximal" überein
  (z. B. LeftRear.ShockDefl "30.9 mm 100.0 mm" <-> LRshockDefl 30,8 mm).
  Damit lässt sich die Ausnutzung des Federwegs direkt messen.
* Negative Ride Height = kurzer Bodenkontakt (Kerbs, Kompressionen).
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

CONTACT_MM = 0.0  # Ride Height <= 0 -> Bodenkontakt
CONTACT_MIN_SAMPLES = 2  # mind. 2 Datensätze (33 ms) am Stück
TRAVEL_WARN = 0.95  # ab 95 % Federweg-Ausnutzung warnen
LS_LIMIT_MMS = 50.0  # Grenze Low-/High-Speed-Dämpfung (Kolbengeschwindigkeit)
HIST_EDGES_MMS = np.arange(-300, 301, 25)

_TWO_NUM = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*mm\s+([-+]?\d+(?:\.\d+)?)\s*mm\s*$")
_SHOCK_CH = re.compile(r"^(LF|RF|LR|RR|HF|HR|CF|CR|ROLLF|ROLLR)shockDefl$")


@dataclass
class RideHeightRow:
    zone: str
    front_mm: float
    rear_mm: float
    rake_mm: float
    low_mm: float  # 1-%-Perzentil (robuster als das Minimum)


KERB_MM = -8.0  # tiefer als das kann der Boden nicht "durch den Asphalt" -> Kerb unter dem Messpunkt


@dataclass
class ContactEvent:
    location: str
    pct: float
    wheels: list[str]
    laps: int
    of_laps: int
    speed_kmh: float
    lowest_mm: float

    @property
    def kind(self) -> str:
        """Heuristik, an echten Daten zu bestätigen:
        sehr negative Werte = Kerb hebt die Fahrbahn unter dem Messpunkt an;
        knapp unter 0 = Auto setzt auf (Plattform zu tief/zu weich)."""
        return "Kerb" if self.lowest_mm < KERB_MM else "Aufsetzen"


@dataclass
class TravelRow:
    setting: str  # Setup-Pfad
    channel: str
    static_mm: float
    max_mm: float
    used_mm: float  # 99,9-%-Perzentil im Fahrbetrieb (auf Setup-Bezug umgerechnet)
    usage: float
    matched_static: bool

    @property
    def margin_mm(self) -> float:
        return self.max_mm - self.used_mm


@dataclass
class AeroPlatform:
    front_calc_mm: float
    rear_calc_mm: float
    front_meas_mm: float
    rear_meas_mm: float
    speed_kmh: float
    finding: str | None


@dataclass
class DamperStats:
    wheel: str
    source: str
    bump_share: float
    ls_share: float
    p95_bump_mms: float
    p95_rebound_mms: float
    histogram: list[int] = field(default_factory=list)

    @property
    def symmetry(self) -> float:
        b, r = self.bump_share, 1 - self.bump_share
        return min(b, r) / max(b, r) if max(b, r) > 0 else float("nan")


@dataclass
class BumpStopRow:
    wheel: str
    gap_mm: float
    max_defl_mm: float
    contact_share: float
    note: str = "Annahme: Federweg und Gap im gleichen Bezug – an echten Daten prüfen"


@dataclass
class PlatformResult:
    ride_height: list[RideHeightRow]
    contacts: list[ContactEvent]
    travel: list[TravelRow]
    aero: AeroPlatform | None
    dampers: list[DamperStats]
    bump_stops: list[BumpStopRow]
    notes: list[str]


# --------------------------------------------------------------- Hilfsfunktionen
def zone_of(pct: float, corners: list[Corner]) -> str:
    for c in corners:
        for phase, (a, b) in c.phase_bounds().items():
            if a <= pct < b:
                return f"{c.name} {phase}"
    before = [c for c in corners if c.end <= pct]
    return f"Gerade nach {before[-1].name}" if before else "Start/Ziel-Gerade"


def _valid_samples(laps: LapSet, name: str) -> tuple[np.ndarray, str]:
    """Rohdaten aller gültigen Runden in voller Auflösung (360 Hz, falls vorhanden)."""
    ibt = laps.ibt
    src = f"{name}_ST" if ibt.has(f"{name}_ST") else name
    arr = ibt.channel(src)
    parts = [arr[lap.slice].reshape(-1) for lap in laps.valid]
    return (np.concatenate(parts) if parts else np.empty(0)), src


def _standstill(laps: LapSet, name: str) -> float | None:
    ibt = laps.ibt
    speed = ibt.get("Speed")
    idx = np.flatnonzero(speed < 0.3)
    if idx.size < 10:
        return None
    return float(np.nanmedian(ibt.get(name)[idx]))


# ------------------------------------------------------------------ Ride Height
def analyze_ride_height(laps: LapSet, corners: list[Corner]) -> tuple[list[RideHeightRow], list[str]]:
    notes: list[str] = []
    chans = {w: f"{w}rideHeight" for w in WHEELS if laps.ibt.has(f"{w}rideHeight")}
    if len(chans) < 4:
        missing = [w for w in WHEELS if w not in chans]
        notes.append(f"Ride-Height-Kanäle fehlen für {', '.join(missing)} – Plattformanalyse eingeschränkt")
        if not chans:
            return [], notes

    stacks = {w: laps.stack(c) * 1000.0 for w, c in chans.items()}
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
                low_mm=float(np.nanpercentile(lo, 1)),
            )
        )
    return rows, notes


def find_contacts(laps: LapSet, corners: list[Corner]) -> list[ContactEvent]:
    """Bodenkontakte (Ride Height <= 0) als Ereignisse mit Ort, über Runden zusammengefasst."""
    ibt = laps.ibt
    chans = [w for w in WHEELS if ibt.has(f"{w}rideHeight")]
    if not chans or not laps.valid:
        return []
    pct_all = ibt.get("LapDistPct")
    speed_all = ibt.get("Speed") * 3.6
    raw: list[tuple[float, str, int, float, float]] = []  # pct, Rad, Runde, Tempo, Tiefe
    for w in chans:
        rh = ibt.get(f"{w}rideHeight") * 1000.0
        for lap in laps.valid:
            seg = rh[lap.slice]
            hit = seg <= CONTACT_MM
            if not hit.any():
                continue
            edges = np.flatnonzero(np.diff(np.concatenate(([0], hit.astype(int), [0]))))
            for s, e in zip(edges[::2], edges[1::2]):
                if e - s < CONTACT_MIN_SAMPLES:
                    continue
                i = lap.start + s + int(np.argmin(seg[s:e]))
                raw.append((float(pct_all[i]), w, lap.number, float(speed_all[i]), float(rh[i])))
    if not raw:
        return []
    raw.sort()
    clusters: list[list[tuple[float, str, int, float, float]]] = []
    for ev in raw:
        if clusters and ev[0] - clusters[-1][-1][0] < 0.004:
            clusters[-1].append(ev)
        else:
            clusters.append([ev])
    out = []
    n_laps = len(laps.valid)
    for cl in clusters:
        pct = float(np.median([e[0] for e in cl]))
        out.append(
            ContactEvent(
                location=zone_of(pct, corners),
                pct=pct,
                wheels=sorted({e[1] for e in cl}, key=WHEELS.index),
                laps=len({e[2] for e in cl}),
                of_laps=n_laps,
                speed_kmh=float(np.median([e[3] for e in cl])),
                lowest_mm=float(min(e[4] for e in cl)),
            )
        )
    out.sort(key=lambda c: (-c.laps, c.pct))
    return out


# ------------------------------------------------------------------- Federweg
def _travel_candidates(path: str) -> list[str]:
    p = path.lower()
    for w, name in WHEEL_SETUP_NAME.items():
        if name.lower() in p:
            return [w]
    front = "front" in p
    if "heave" in p:
        return ["HF", "CF"] if front else ["HR", "CR"]
    if "third" in p:
        return ["HR", "CR"]
    if "roll" in p:
        return ["ROLLF"] if front else ["ROLLR"]
    return []


def analyze_travel(laps: LapSet, setup: CarSetup) -> list[TravelRow]:
    """Federweg-Ausnutzung aus Setup-Anzeigen 'statisch / maximal' und Telemetrie."""
    ibt = laps.ibt
    channels = [n for n in ibt.channel_names() if _SHOCK_CH.match(n)]
    if not channels or not laps.valid:
        return []
    stand = {ch: _standstill(laps, ch) for ch in channels}
    rows = []
    used_channels: set[str] = set()
    for path, v in setup.values.items():
        if not v.key.endswith("Defl") or "Spring" in v.key:
            continue  # Federwege der Feder selbst haben einen anderen Bezug
        m = _TWO_NUM.match(v.raw)
        if not m:
            continue
        static, max_mm = float(m.group(1)), float(m.group(2))
        cands = [f"{c}shockDefl" for c in _travel_candidates(path) if f"{c}shockDefl" in channels]
        if not cands:
            # Fallback: Kanal mit passendem Standwert
            cands = [ch for ch in channels if stand[ch] is not None and abs(stand[ch] * 1000 - static) < 1.5]
        cands = [c for c in cands if c not in used_channels]
        if not cands:
            continue
        ch = cands[0]
        st = stand[ch]
        matched = st is not None and abs(st * 1000 - static) < 1.5
        offset = static - st * 1000 if st is not None else 0.0
        x, _ = _valid_samples(laps, ch)
        x = x[np.isfinite(x)] * 1000.0
        if x.size == 0:
            continue
        used = float(np.percentile(x, 99.9)) + offset
        rows.append(TravelRow(path, ch, static, max_mm, used, used / max_mm if max_mm > 0 else float("nan"), matched))
        used_channels.add(ch)
    return rows


# --------------------------------------------------------------- Aero-Plattform
def analyze_aero_platform(laps: LapSet, setup: CarSetup) -> AeroPlatform | None:
    """Gemessene Ride Height bei Topspeed vs. Annahme im iRacing-Aero-Rechner (GTP)."""
    fc = setup.find("AeroCalculator", "FrontRh")
    rc = setup.find("AeroCalculator", "RearRh")
    ibt = laps.ibt
    if not fc or not rc or fc[0].value is None or rc[0].value is None or not laps.valid:
        return None
    if not all(ibt.has(f"{w}rideHeight") for w in WHEELS):
        return None
    sl = np.concatenate([np.arange(lap.start, lap.end) for lap in laps.valid])
    speed = ibt.get("Speed")[sl]
    ay = np.abs(ibt.get("LatAccel")[sl]) if ibt.has("LatAccel") else np.zeros_like(speed)
    brake = ibt.get("Brake")[sl] if ibt.has("Brake") else np.zeros_like(speed)
    fast = (speed > np.percentile(speed, 90)) & (ay < 3.0) & (brake < 0.05)
    if fast.sum() < 60:
        return None
    rh = {w: ibt.get(f"{w}rideHeight")[sl][fast] * 1000.0 for w in WHEELS}
    front = float(np.median((rh["LF"] + rh["RF"]) / 2))
    rear = float(np.median((rh["LR"] + rh["RR"]) / 2))
    f_calc, r_calc = float(fc[0].value), float(rc[0].value)
    df, dr = front - f_calc, rear - r_calc
    finding = None
    rake_meas, rake_calc = rear - front, r_calc - f_calc
    if abs(df) > 2 or abs(dr) > 2:
        direction = (
            "nach hinten (weniger Frontabtrieb → Highspeed-Untersteuern)"
            if rake_meas < rake_calc
            else "nach vorne (mehr Frontabtrieb → Highspeed-Übersteuern)"
        )
        finding = (
            f"Bei Topspeed fährt das Auto vorne {df:+.1f} mm und hinten {dr:+.1f} mm anders als im Aero-Rechner "
            f"angenommen (Rake {rake_meas:.1f} statt {rake_calc:.1f} mm). Die angezeigte Abtriebsbalance verschiebt "
            f"sich dadurch vermutlich {direction}. Bezugspunkt der Rechner-Werte noch an weiteren Daten bestätigen."
        )
    return AeroPlatform(f_calc, r_calc, front, rear, float(np.median(speed[fast]) * 3.6), finding)


# ---------------------------------------------------------------------- Dämpfer
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


def analyze_bump_stops(laps: LapSet, setup: CarSetup) -> list[BumpStopRow]:
    """Für Autos mit Bump-Rubber-/Packer-Gap im Setup (v. a. GT3, noch zu bestätigen)."""
    rows = []
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
        rows.append(BumpStopRow(w, gap_mm, float(d.max()), float(np.mean(d >= gap_mm))))
    return rows


def analyze_platform(laps: LapSet, corners: list[Corner], setup: CarSetup) -> PlatformResult:
    rh, notes = analyze_ride_height(laps, corners)
    travel = analyze_travel(laps, setup)
    bump = analyze_bump_stops(laps, setup)
    if not travel and not bump:
        notes.append("Federweg-Ausnutzung nicht bestimmbar (keine passenden Setup-Anzeigen oder Kanäle)")
    return PlatformResult(
        ride_height=rh,
        contacts=find_contacts(laps, corners),
        travel=travel,
        aero=analyze_aero_platform(laps, setup),
        dampers=analyze_dampers(laps),
        bump_stops=bump,
        notes=notes,
    )

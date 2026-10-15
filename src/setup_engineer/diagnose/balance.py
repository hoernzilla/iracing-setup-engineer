"""Balance-Index: Unter-/Übersteuern messen statt erfragen.

Idee: Im linearen Bereich (wenig Querbeschleunigung) ist der Lenkwinkel
proportional zur Bahnkrümmung κ = Gierrate / Tempo. Diesen Faktor k lernen
wir pro Auto und Session aus den Daten selbst – kein Radstand und keine
Lenkübersetzung nötig. Im Grenzbereich gilt dann:

    Lenküberschuss = Lenkwinkel / (k · κ) − 1

> 0  mehr Lenkung als ein neutrales Auto bräuchte  -> Untersteuern
< 0  weniger Lenkung bzw. Gegenlenken               -> Übersteuern

Fahrer oder Auto? Ein Setup-Problem tritt konstant über die Runden auf.
Hängt die Abweichung dagegen stark vom Tempo am Kurveneingang ab, ist sie
eher fahrerbedingt (zu schnell rein -> schiebt).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..segment.corners import Corner
from ..segment.laps import LapSet

# Vorläufige Schwellen – werden an echten GT3/GTP-Daten kalibriert
UNDERSTEER_FLAG = 0.10  # ±10 % Lenküberschuss gilt als auffällig
DRIVER_CORR = 0.6  # |r| ab hier: Abweichung folgt dem Eingangstempo -> Fahrer
MIN_LAPS = 4
OVERDRIVE_CORR = 0.3  # Eingangstempo ↔ Abschnittszeit: ab hier kostet mehr Tempo Zeit


@dataclass(frozen=True)
class SteerModel:
    gain: float  # rad Lenkrad pro (1/m) Krümmung
    samples: int


@dataclass(frozen=True)
class PhaseBalance:
    corner: str
    phase: str
    understeer: float  # Median Lenküberschuss (0.12 = 12 % zu viel Lenkung)
    lap_spread: float  # Standardabweichung über die Runden
    countersteer_share: float  # Anteil Gegenlenken
    entry_speed_corr: float | None
    laps: int
    verdict: str  # "Auto", "Fahrer", "unklar", "neutral"
    time_corr: float | None = None  # Eingangstempo ↔ Abschnittszeit

    @property
    def tendency(self) -> str:
        if self.countersteer_share > 0.05 or self.understeer < -UNDERSTEER_FLAG:
            return "Übersteuern"
        if self.understeer > UNDERSTEER_FLAG:
            return "Untersteuern"
        if self.verdict != "neutral":
            return "Untersteuern (einzelne Runden)" if self.understeer >= 0 else "Übersteuern (einzelne Runden)"
        return "neutral"


def fit_steer_model(laps: LapSet) -> SteerModel | None:
    ibt = laps.ibt
    if not (ibt.has("SteeringWheelAngle") and ibt.has("Speed")):
        return None
    steer = laps.stack("SteeringWheelAngle")
    speed = laps.stack("Speed")
    kappa = _kappa(laps, speed)
    ay = np.abs(laps.stack("LatAccel")) if ibt.has("LatAccel") else np.abs(kappa) * speed**2
    brake = laps.stack("Brake") if ibt.has("Brake") else np.zeros_like(speed)

    ay_lim = 0.4 * np.nanpercentile(ay, 95)
    m = (speed > 15) & (np.abs(kappa) > 1 / 800) & (ay < ay_lim) & (brake < 0.05)
    m &= np.isfinite(steer) & np.isfinite(kappa)
    if m.sum() < 50:
        return None
    k = float(np.sum(steer[m] * kappa[m]) / np.sum(kappa[m] ** 2))
    return SteerModel(gain=k, samples=int(m.sum()))


def _kappa(laps: LapSet, speed: np.ndarray) -> np.ndarray:
    if laps.ibt.has("YawRate"):
        return laps.stack("YawRate") / np.maximum(speed, 1.0)
    return laps.stack("LatAccel") / np.maximum(speed, 1.0) ** 2


def phase_mask(grid: np.ndarray, a: float, b: float) -> np.ndarray:
    return (grid >= a) & (grid < b)


def analyze_balance(
    laps: LapSet, corners: list[Corner], model: SteerModel, speed_balance: "SpeedBalance | None" = None
) -> list[PhaseBalance]:
    """Balance je Kurve/Phase.

    Fahrer oder Auto? Dass ein Auto mit mehr Eingangstempo mehr schiebt, ist am
    Limit normal (echte GTP-Daten: in schnellen Kurven fast immer so). Ein
    Fahrerfehler ist es erst, wenn das Mehr an Tempo die Kurve insgesamt
    LANGSAMER macht (Überfahren). Deshalb zwei Korrelationen über die Runden:
      r1 = Eingangstempo ↔ Lenküberschuss
      r2 = Eingangstempo ↔ Zeit für den Kurvenabschnitt
    Fahrer = r1 hoch UND r2 > 0 (schneller rein, langsamer raus).
    """
    valid = laps.valid
    if not valid:
        return []
    steer = laps.stack("SteeringWheelAngle")
    speed = laps.stack("Speed")
    kappa = _kappa(laps, speed)
    neutral = model.gain * kappa
    length = laps.ibt.track_length_m or 4000.0
    dt = (length / laps.grid.size) / np.maximum(speed, 1.0)  # Sekunden je Rasterpunkt

    with np.errstate(invalid="ignore", divide="ignore"):
        excess = np.where(
            (np.abs(kappa) >= 1 / 400) & (np.sign(steer) == np.sign(neutral)) & (speed > 10),
            steer / neutral - 1.0,
            np.nan,
        )
    counter = (np.sign(steer) != np.sign(kappa)) & (np.abs(kappa) >= 1 / 300) & (speed > 10)

    out: list[PhaseBalance] = []
    for i, c in enumerate(corners):
        bounds = c.phase_bounds()
        hi = bounds.get("Scheitel", (c.start, c.apex))[1]
        em = phase_mask(laps.grid, c.start, max(hi, c.start + 1e-4))
        entry_speed = np.nanmean(speed[:, em], axis=1) if em.any() else speed[:, 0]
        # Abschnittszeit: Bremspunkt bis Bremspunkt der nächsten Kurve (Ausgangstempo zählt mit)
        nxt = corners[i + 1].brake_start if i + 1 < len(corners) else 1.0
        sm = phase_mask(laps.grid, c.brake_start, max(nxt, c.end))
        section_time = dt[:, sm].sum(axis=1)
        for phase, (a, b) in bounds.items():
            if phase == "Bremsen":
                continue  # vor dem Einlenken ist Balance kaum messbar
            m = phase_mask(laps.grid, a, b)
            if not m.any():
                continue
            per_lap = np.array([_nanmedian(excess[j, m]) for j in range(len(valid))])
            ok = np.isfinite(per_lap)
            cs = float(np.mean(counter[:, m]))
            if ok.sum() == 0:
                continue
            med = float(np.median(per_lap[ok]))
            spread = float(np.std(per_lap[ok])) if ok.sum() > 1 else float("nan")
            corr = time_corr = None
            if ok.sum() >= MIN_LAPS and np.std(entry_speed[ok]) > 0.05:
                corr = float(np.corrcoef(entry_speed[ok], per_lap[ok])[0, 1])
                if np.std(section_time[ok]) > 1e-6:
                    time_corr = float(np.corrcoef(entry_speed[ok], section_time[ok])[0, 1])
            worst = float(np.max(np.abs(per_lap[ok])))
            out.append(
                PhaseBalance(
                    corner=c.name,
                    phase=phase,
                    understeer=med,
                    lap_spread=spread,
                    countersteer_share=cs,
                    entry_speed_corr=corr,
                    laps=int(ok.sum()),
                    verdict=_verdict(med, spread, worst, corr, int(ok.sum()), cs, time_corr),
                    time_corr=time_corr,
                )
            )
    return out


def _verdict(
    med: float, spread: float, worst: float, corr: float | None, n: int, cs: float, time_corr: float | None = None
) -> str:
    """Fahrer oder Auto?

    * auffällig = Median über der Schwelle ODER einzelne Runden deutlich darüber
    * folgt die Abweichung dem Eingangstempo -> Fahrer
    * konstant über die Runden -> Auto
    * sonst unklar (inkonsistent, aber kein Tempo-Zusammenhang erkennbar)
    """
    notable = abs(med) > UNDERSTEER_FLAG or worst > 1.5 * UNDERSTEER_FLAG or cs > 0.05
    if not notable:
        return "neutral"
    if n < MIN_LAPS:
        return "unklar"
    if corr is not None and abs(corr) >= DRIVER_CORR:
        # Nur Überfahren ist ein Fahrerthema: mehr Tempo rein kostet Zeit im Abschnitt.
        if time_corr is None or time_corr > OVERDRIVE_CORR:
            return "Fahrer"
        # Mehr Tempo bringt mehr Schieben, aber keine Zeit: Auto am Limit
        return "Auto" if abs(med) > UNDERSTEER_FLAG else "unklar"
    # konstant über die Runden (Streuung klein gegenüber der Abweichung)
    if abs(med) > UNDERSTEER_FLAG and np.isfinite(spread) and spread < max(abs(med), 0.05) * 0.75:
        return "Auto"
    return "unklar"


SPEED_BANDS_KMH = ((0, 150), (150, 200), (200, 250), (250, 500))
AERO_SPLIT_FLAG = 0.10  # 10 Prozentpunkte Unterschied langsam vs. schnell


@dataclass(frozen=True)
class SpeedBandBalance:
    band: str
    samples: int
    lat_g: float
    understeer: float
    speed_kmh: float = float("nan")  # Median-Tempo der Messpunkte im Band


@dataclass(frozen=True)
class SpeedBalance:
    bands: list[SpeedBandBalance]
    low: float | None  # Mittel der langsamen Bänder
    high: float | None  # Mittel der schnellen Bänder
    finding: str | None


def balance_by_speed(laps: LapSet, model: SteerModel) -> SpeedBalance | None:
    """Balance im Grenzbereich nach Tempo getrennt.

    Unterscheidet mechanische Balance (langsam) von Aero-Balance (schnell):
    Untersteuert das Auto nur schnell, liegt die Aero-Balance zu weit hinten
    (oder die Plattform verschiebt sie bei Tempo); übersteuert es schnell,
    entsprechend umgekehrt.
    """
    if not laps.valid:
        return None
    steer = laps.stack("SteeringWheelAngle")
    speed = laps.stack("Speed")
    kappa = _kappa(laps, speed)
    ay = laps.stack("LatAccel") if laps.ibt.has("LatAccel") else kappa * speed**2
    brake = laps.stack("Brake") if laps.ibt.has("Brake") else np.zeros_like(speed)
    neutral = model.gain * kappa
    grip = (np.abs(ay) > 0.6 * np.nanpercentile(np.abs(ay), 95)) & (brake < 0.05)
    grip &= np.sign(steer) == np.sign(neutral)
    kmh = speed * 3.6
    bands = []
    for lo, hi in SPEED_BANDS_KMH:
        m = grip & (kmh >= lo) & (kmh < hi)
        if m.sum() < 30:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            ex = steer[m] / neutral[m] - 1.0
        label = f"> {lo} km/h" if hi >= 500 else f"{lo}–{hi} km/h"
        bands.append(
            SpeedBandBalance(
                label,
                int(m.sum()),
                float(np.median(np.abs(ay[m]))) / 9.81,
                float(np.nanmedian(ex)),
                float(np.median(kmh[m])),
            )
        )
    if not bands:
        return None
    low = [b.understeer for b in bands if b.band.startswith(("0", "150"))]
    high = [b.understeer for b in bands if not b.band.startswith(("0", "150"))]
    lo_v = float(np.mean(low)) if low else None
    hi_v = float(np.mean(high)) if high else None
    finding = None
    if lo_v is not None and hi_v is not None:
        d = hi_v - lo_v
        if d > AERO_SPLIT_FLAG:
            finding = (
                f"Highspeed-Untersteuern: schnell {hi_v * 100:+.0f} % gegenüber langsam {lo_v * 100:+.0f} %. "
                "Die Aero-Balance liegt bei Tempo zu weit hinten (Frontflügel/Rake/Ride Height vorne prüfen)."
            )
        elif d < -AERO_SPLIT_FLAG:
            finding = (
                f"Highspeed-Übersteuern: schnell {hi_v * 100:+.0f} % gegenüber langsam {lo_v * 100:+.0f} %. "
                "Die Aero-Balance liegt bei Tempo zu weit vorne (Heckflügel/Rake prüfen)."
            )
    return SpeedBalance(bands=bands, low=lo_v, high=hi_v, finding=finding)


def _nanmedian(a: np.ndarray) -> float:
    a = a[np.isfinite(a)]
    return float(np.median(a)) if a.size else float("nan")

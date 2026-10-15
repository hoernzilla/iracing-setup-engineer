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


def analyze_balance(laps: LapSet, corners: list[Corner], model: SteerModel) -> list[PhaseBalance]:
    valid = laps.valid
    if not valid:
        return []
    steer = laps.stack("SteeringWheelAngle")
    speed = laps.stack("Speed")
    kappa = _kappa(laps, speed)
    neutral = model.gain * kappa

    with np.errstate(invalid="ignore", divide="ignore"):
        excess = np.where(
            (np.abs(kappa) >= 1 / 400) & (np.sign(steer) == np.sign(neutral)) & (speed > 10),
            steer / neutral - 1.0,
            np.nan,
        )
    counter = (np.sign(steer) != np.sign(kappa)) & (np.abs(kappa) >= 1 / 300) & (speed > 10)

    out: list[PhaseBalance] = []
    for c in corners:
        # Tempo, das der Fahrer in die Kurve trägt: Mittel über Einlenken bis Scheitel.
        # Robuster als ein Einzelwert am Einlenkpunkt.
        bounds = c.phase_bounds()
        hi = bounds.get("Scheitel", (c.start, c.apex))[1]
        em = phase_mask(laps.grid, c.start, max(hi, c.start + 1e-4))
        entry_speed = np.nanmean(speed[:, em], axis=1) if em.any() else speed[:, 0]
        for phase, (a, b) in bounds.items():
            if phase == "Bremsen":
                continue  # vor dem Einlenken ist Balance kaum messbar
            m = phase_mask(laps.grid, a, b)
            if not m.any():
                continue
            per_lap = np.array([_nanmedian(excess[i, m]) for i in range(len(valid))])
            ok = np.isfinite(per_lap)
            cs = float(np.mean(counter[:, m]))
            if ok.sum() == 0:
                continue
            med = float(np.median(per_lap[ok]))
            spread = float(np.std(per_lap[ok])) if ok.sum() > 1 else float("nan")
            corr = None
            if ok.sum() >= MIN_LAPS and np.std(entry_speed[ok]) > 0.05:
                corr = float(np.corrcoef(entry_speed[ok], per_lap[ok])[0, 1])
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
                    verdict=_verdict(med, spread, worst, corr, int(ok.sum()), cs),
                )
            )
    return out


def _verdict(med: float, spread: float, worst: float, corr: float | None, n: int, cs: float) -> str:
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
        return "Fahrer"
    # konstant über die Runden (Streuung klein gegenüber der Abweichung)
    if abs(med) > UNDERSTEER_FLAG and np.isfinite(spread) and spread < max(abs(med), 0.05) * 0.75:
        return "Auto"
    return "unklar"


def _nanmedian(a: np.ndarray) -> float:
    a = a[np.isfinite(a)]
    return float(np.median(a)) if a.size else float("nan")

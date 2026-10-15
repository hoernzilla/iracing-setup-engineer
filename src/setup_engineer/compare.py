"""A/B-Vergleich zweier Runs: Hat die Setup-Änderung wirklich etwas gebracht?

Rundenzeit = Basis + Setup-Effekt + Sprit-Effekt + Temperatur-Effekt + Rauschen.
Sprit und Streckentemperatur gehen nur als Störgrößen ins Modell, wenn sie
in den Daten ausreichend variieren. Der Setup-Effekt wird per OLS geschätzt
und mit einem t-Test geprüft.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from .analysis import SessionAnalysis
from .setup import SetupChange, diff

ALPHA = 0.05


@dataclass
class ABResult:
    laps_a: int
    laps_b: int
    mean_a: float
    mean_b: float
    effect_s: float  # B − A, bereinigt; negativ = B schneller
    ci95_s: tuple[float, float]
    p_value: float
    covariates: list[str]
    verdict: str
    laps_needed: int | None  # geschätzte Runden je Variante für ein klares Ergebnis
    setup_changes: list[SetupChange]


def ab_compare(a: SessionAnalysis, b: SessionAnalysis) -> ABResult:
    la, lb = a.laps.valid, b.laps.valid
    changes = diff(a.setup, b.setup)
    if len(la) < 2 or len(lb) < 2:
        return ABResult(
            len(la), len(lb), float("nan"), float("nan"), float("nan"), (float("nan"),) * 2,
            float("nan"), [], "zu wenig gültige Runden", None, changes,
        )

    y = np.array([lap.time_s for lap in la + lb])
    group = np.array([0] * len(la) + [1] * len(lb), dtype=float)
    cols = [np.ones_like(y), group]
    names = []
    fuel = np.array([lap.fuel_start_l if lap.fuel_start_l is not None else np.nan for lap in la + lb])
    if np.isfinite(fuel).all() and np.ptp(fuel) > 2.0:
        cols.append(fuel - fuel.mean())
        names.append("Sprit")
    temp = np.array([lap.track_temp_c if lap.track_temp_c is not None else np.nan for lap in la + lb])
    if np.isfinite(temp).all() and np.ptp(temp) > 1.0:
        cols.append(temp - temp.mean())
        names.append("Streckentemperatur")

    X = np.column_stack(cols)
    dof = len(y) - X.shape[1]
    if dof < 2:  # zu wenig Runden für Kovariaten -> nur Gruppenvergleich
        X, names, dof = X[:, :2], [], len(y) - 2
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    sigma2 = float(resid @ resid / dof)
    cov = sigma2 * np.linalg.pinv(X.T @ X)
    se = float(np.sqrt(cov[1, 1]))
    effect = float(beta[1])
    t = effect / se if se > 0 else 0.0
    p = float(2 * stats.t.sf(abs(t), dof)) if se > 0 else 1.0
    q = float(stats.t.ppf(0.975, dof))
    ci = (effect - q * se, effect + q * se)

    if p < ALPHA:
        verdict = "B ist schneller" if effect < 0 else "B ist langsamer"
    else:
        verdict = "nicht entscheidbar"

    # Runden je Variante, um |effect| bei 80 % Power zu erkennen
    sd = float(np.sqrt(sigma2))
    needed = None
    if abs(effect) > 1e-3 and sd > 0:
        needed = int(np.ceil(2 * ((1.96 + 0.84) * sd / abs(effect)) ** 2))

    return ABResult(
        laps_a=len(la),
        laps_b=len(lb),
        mean_a=float(np.mean([lap.time_s for lap in la])),
        mean_b=float(np.mean([lap.time_s for lap in lb])),
        effect_s=effect,
        ci95_s=ci,
        p_value=p,
        covariates=names,
        verdict=verdict,
        laps_needed=needed,
        setup_changes=changes,
    )

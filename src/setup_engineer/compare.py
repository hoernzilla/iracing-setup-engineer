"""A/B-Vergleich zweier Runs: Hat die Setup-Änderung wirklich etwas gebracht?

Rundenzeit = Basis + Setup-Effekt + Sprit-Effekt + Temperatur-Effekt + Rauschen.
Sprit und Streckentemperatur gehen nur als Störgrößen ins Modell, wenn sie
in den Daten ausreichend variieren. Der Setup-Effekt wird per OLS geschätzt
und mit einem t-Test geprüft.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    notes: list[str] = field(default_factory=list)
    lap_sd_s: float | None = None  # Rundenstreuung nach Bereinigung (Fahrer-Konstanz)
    sections: list["SectionDelta"] = field(default_factory=list)
    conditions: list["Condition"] = field(default_factory=list)
    balance: list["BalanceDelta"] = field(default_factory=list)


@dataclass
class SectionDelta:
    section: str  # z. B. "T1 → T2" (vom Bremspunkt T1 bis zum Bremspunkt T2)
    time_a: float
    time_b: float

    @property
    def delta(self) -> float:
        return self.time_b - self.time_a


def section_deltas(a: SessionAnalysis, b: SessionAnalysis) -> list[SectionDelta]:
    """Median-Zeit je Abschnitt (Bremspunkt Kurve n bis Bremspunkt Kurve n+1) in A und B."""
    corners = a.corners
    length = a.ibt.track_length_m
    if not corners or not length or not a.laps.valid or not b.laps.valid:
        return []
    grid = a.laps.grid
    ds = length / grid.size

    def seg_times(s: SessionAnalysis) -> np.ndarray:
        v = np.maximum(s.laps.stack("Speed"), 1.0)
        return ds / v  # Sekunden je Rasterpunkt, Runden × Raster

    ta, tb = seg_times(a), seg_times(b)
    starts = [c.brake_start for c in corners]
    out = []
    for i, c in enumerate(corners):
        lo, hi = starts[i], starts[i + 1] if i + 1 < len(starts) else 1.0
        m = (grid >= lo) & (grid < hi)
        nxt = corners[i + 1].name if i + 1 < len(corners) else "Ziel"
        out.append(
            SectionDelta(f"{c.name} → {nxt}", float(np.median(ta[:, m].sum(axis=1))), float(np.median(tb[:, m].sum(axis=1))))
        )
    m0 = grid < starts[0]
    out.insert(0, SectionDelta(f"Start → {corners[0].name}", float(np.median(ta[:, m0].sum(axis=1))), float(np.median(tb[:, m0].sum(axis=1)))))
    return out


CONDITIONS = (
    # Kanal, Bezeichnung, Einheit, Schwelle für Warnung (absolut), relativ?
    ("AirDensity", "Luftdichte", "kg/m³", 0.01, True),
    ("TrackTempCrew", "Streckentemperatur", "°C", 1.0, False),
    ("AirTemp", "Lufttemperatur", "°C", 2.0, False),
    ("WindVel", "Wind", "m/s", 2.0, False),
)


@dataclass
class Condition:
    name: str
    unit: str
    a: float
    b: float
    warn: bool


def compare_conditions(a: SessionAnalysis, b: SessionAnalysis) -> list[Condition]:
    """Umgebungsbedingungen beider Runs. Erkenntnis aus echten Daten: 4,6 % weniger
    Luftdichte kosteten den 963 bei identischem Setup rund 0,8 s (weniger Abtrieb
    und Leistung) – solche Unterschiede überdecken kleine Setup-Effekte."""
    out = []
    for ch, label, unit, thr, rel in CONDITIONS:
        if not (a.ibt.has(ch) and b.ibt.has(ch)):
            continue
        va = float(np.nanmean(np.concatenate([a.ibt.get(ch)[l.slice] for l in a.laps.valid])))
        vb = float(np.nanmean(np.concatenate([b.ibt.get(ch)[l.slice] for l in b.laps.valid])))
        diff_ = abs(vb - va) / abs(va) if rel and va else abs(vb - va)
        out.append(Condition(label, unit, va, vb, diff_ > thr))
    return out


def incar_changes(a: SessionAnalysis, b: SessionAnalysis) -> list[SetupChange]:
    """Unterschiede der im Auto gefahrenen Werte (dc*-Kanäle), die im Setup-Block fehlen."""
    eb = {s.channel: s for s in b.incar}
    out = []
    for sa in a.incar:
        sb = eb.get(sa.channel)
        if sb is None or sa.effective is None or sb.effective is None or sa.effective == sb.effective:
            continue
        out.append(
            SetupChange(f"Im Auto: {sa.label}", f"{sa.effective:g}", f"{sb.effective:g}", round(sb.effective - sa.effective, 4), "")
        )
    return out


@dataclass
class BalanceDelta:
    zone: str
    a: float
    b: float


def balance_deltas(a: SessionAnalysis, b: SessionAnalysis) -> list[BalanceDelta]:
    """Lenküberschuss A vs. B – nach Tempo und je Kurve (Scheitel), um die Wirkung
    einer Änderung auf die Balance zu sehen."""
    out = []
    if a.speed_balance and b.speed_balance:
        bb = {x.band: x for x in b.speed_balance.bands}
        for x in a.speed_balance.bands:
            if x.band in bb:
                out.append(BalanceDelta(f"Tempo {x.band}", x.understeer, bb[x.band].understeer))
    pb = {(x.corner, x.phase): x for x in b.balance}
    for x in a.balance:
        if x.phase == "Scheitel" and (x.corner, x.phase) in pb:
            out.append(BalanceDelta(f"{x.corner} Scheitel", x.understeer, pb[(x.corner, x.phase)].understeer))
    return out


def _racing_laps(s: SessionAnalysis, notes: list[str], label: str) -> list:
    """Gültige Runden ohne Aufwärmrunde (erste fliegende Runde nach der Boxengasse).

    Echte Daten zeigen: Die erste Runde nach dem Out-Lap ist wegen kalter Reifen
    ~1,5–2,5 s langsamer und würde den Vergleich verzerren.
    """
    by_no = {lap.number: lap for lap in s.laps.laps}
    out, skipped = [], 0
    for lap in s.laps.valid:
        prev = by_no.get(lap.number - 1)
        if prev is not None and any("Boxengasse" in r for r in prev.reasons):
            skipped += 1
            continue
        out.append(lap)
    if skipped:
        notes.append(f"{label}: {skipped} Aufwärmrunde(n) nach der Boxengasse nicht gewertet.")
    return out


def _usable_covariate(x: np.ndarray, group: np.ndarray, min_sd: float) -> tuple[bool, str | None]:
    """Eine Störgröße darf nur ins Modell, wenn sie INNERHALB der Runs variiert.

    Ist sie pro Run (fast) konstant, ist sie vom Setup-Effekt nicht zu trennen
    (Beispiel echte Daten: Strecke 23,9 °C in A, 25,0 °C in B -> Modell kippt).
    """
    if not np.isfinite(x).all():
        return False, None
    sd_in = [float(np.std(x[group == g])) for g in (0, 1)]
    if max(sd_in) < min_sd:
        if abs(x[group == 0].mean() - x[group == 1].mean()) >= min_sd:
            return False, "innerhalb der Runs konstant, nur zwischen den Runs verschieden – nicht vom Setup trennbar"
        return False, None
    if min(sd_in) < min_sd / 2:
        return False, "variiert nur in einem der beiden Runs"
    r = float(np.corrcoef(x, group)[0, 1])
    if abs(r) > 0.7:
        return False, f"zu stark mit dem Run verknüpft (r = {r:.2f})"
    return True, None


def ab_compare(a: SessionAnalysis, b: SessionAnalysis) -> ABResult:
    notes: list[str] = []
    la, lb = _racing_laps(a, notes, "A"), _racing_laps(b, notes, "B")
    changes = diff(a.setup, b.setup) + incar_changes(a, b)
    if not changes:
        notes.append(
            "Keine Setup-Änderung zwischen A und B – der Unterschied stammt aus Fahrer und Bedingungen "
            "(Wiederholbarkeitstest)."
        )
    if len(la) < 2 or len(lb) < 2:
        return ABResult(
            len(la), len(lb), float("nan"), float("nan"), float("nan"), (float("nan"),) * 2,
            float("nan"), [], "zu wenig gültige Runden", None, changes, notes,
        )

    y = np.array([lap.time_s for lap in la + lb])
    group = np.array([0] * len(la) + [1] * len(lb), dtype=float)
    cols = [np.ones_like(y), group]
    names = []
    for label, values, min_sd in (
        ("Sprit", [lap.fuel_start_l for lap in la + lb], 1.0),
        ("Streckentemperatur", [lap.track_temp_c for lap in la + lb], 0.3),
    ):
        x = np.array([np.nan if v is None else v for v in values], dtype=float)
        ok, why = _usable_covariate(x, group, min_sd)
        if ok:
            cols.append(x - x.mean())
            names.append(label)
        elif why:
            notes.append(f"{label} nicht herausgerechnet: {why}")

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

    conds = compare_conditions(a, b)
    changed = [c for c in conds if c.warn]
    if changed:
        notes.append(
            "Bedingungen unterschiedlich ("
            + ", ".join(f"{c.name} {c.a:.3g} → {c.b:.3g} {c.unit}" for c in changed)
            + ") – der Effekt kann ganz oder teilweise daher kommen. Für saubere Tests A und B direkt "
            "hintereinander in derselben Session fahren, idealerweise A-B-A."
        )
        if p < ALPHA and changes:
            verdict += " (Bedingungen verschieden – mit Vorsicht)"

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
        notes=notes,
        lap_sd_s=sd,
        sections=section_deltas(a, b),
        conditions=conds,
        balance=balance_deltas(a, b),
    )

"""A/B-Vergleich zweier Runs: Hat die Setup-Änderung wirklich etwas gebracht?

Rundenzeit = Basis + Setup-Effekt + Sprit-Effekt + Temperatur-Effekt + Rauschen.
Sprit und Streckentemperatur gehen nur als Störgrößen ins Modell, wenn sie
in den Daten ausreichend variieren. Der Setup-Effekt wird per OLS geschätzt
und mit einem t-Test geprüft.
"""

from __future__ import annotations

import re
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
    detail: object | None = None  # compare_detail.ABDetail


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


MIN_BLOCK_LAPS = 4  # gewertete Runden je Block (A, B, zweites A) – darunter ist der Test nicht komplett


def _lap_clock_min(s: SessionAnalysis, laps: list) -> np.ndarray:
    """Session-Uhr (Minuten) zu Beginn jeder Runde – für den Verlauf innerhalb einer Session."""
    t = s.ibt.get("SessionTime")
    return np.array([float(t[lap.start]) / 60 for lap in laps], dtype=float)


def ab_compare(a: SessionAnalysis, b: SessionAnalysis, a2: SessionAnalysis | None = None) -> ABResult:
    """B gegen A. Mit ``a2`` (Garagen-Test A-B-A): B gegen beide A-Runs, Verlauf über die drei Runs
    herausgerechnet (Strecke, Reifen, Fahrer werden mit der Zeit meist schneller)."""
    notes: list[str] = []
    la, lb = list(a.laps.valid), list(b.laps.valid)
    la2 = list(a2.laps.valid) if a2 is not None else []
    changes = diff(a.setup, b.setup) + incar_changes(a, b)
    if not changes:
        notes.append(
            "Keine Setup-Änderung zwischen A und B – der Unterschied stammt aus Fahrer und Bedingungen "
            "(Wiederholbarkeitstest)."
        )
    if len(la) + len(la2) < 2 or len(lb) < 2:
        return ABResult(
            len(la) + len(la2), len(lb), float("nan"), float("nan"), float("nan"), (float("nan"),) * 2,
            float("nan"), [], "zu wenig gültige Runden", None, changes, notes,
        )

    a_laps = la + la2
    y = np.array([lap.time_s for lap in la + lb + la2])
    group = np.array([0] * len(la) + [1] * len(lb) + [0] * len(la2), dtype=float)
    cols = [np.ones_like(y), group]
    names = []
    if a2 is not None:
        # A-B-A über drei Runs: B liegt zeitlich in der Mitte -> ein linearer Verlauf ist schätzbar
        run = np.array([0] * len(la) + [1] * len(lb) + [2] * len(la2), dtype=float)
        cols.append(run - run.mean())
        names.append("Verlauf über die drei Runs")
    elif a.ibt is b.ibt:
        # A-B-A im Auto (eine Datei): Session-Uhr als Verlauf, wenn B zwischen den A-Blöcken liegt
        clock = np.concatenate([_lap_clock_min(a, la), _lap_clock_min(b, lb)])
        ok, why = _usable_covariate(clock, group, 1.0)
        if ok:
            cols.append(clock - clock.mean())
            names.append("Verlauf in der Session")
        elif why:
            notes.append(f"Verlauf nicht herausgerechnet: {why}")
    for label, values, min_sd in (
        ("Sprit", [lap.fuel_start_l for lap in la + lb + la2], 1.0),
        ("Streckentemperatur", [lap.track_temp_c for lap in la + lb + la2], 0.3),
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
    if changed and a2 is None:
        notes.append(
            "Bedingungen unterschiedlich ("
            + ", ".join(f"{c.name} {c.a:.3g} → {c.b:.3g} {c.unit}" for c in changed)
            + ") – der Effekt kann ganz oder teilweise daher kommen. Für saubere Tests A und B direkt "
            "hintereinander in derselben Session fahren, idealerweise A-B-A."
        )
        if p < ALPHA and changes:
            verdict += " (Bedingungen verschieden – mit Vorsicht)"

    sections = section_deltas(a, b)
    balance = balance_deltas(a, b)
    if a2 is not None:
        # Kontrolle: Was hat sich ohne Setup-Änderung zwischen erstem und zweitem A verändert?
        drift = float(np.mean([lap.time_s for lap in la2]) - np.mean([lap.time_s for lap in la]))
        notes.append(
            f"Kontrolle zweites A: {drift:+.3f} s pro Runde gegenüber dem ersten A bei identischem Setup – "
            "so viel haben Strecke, Reifen und Fahrer zwischen den Runs verändert. Dieser Verlauf ist herausgerechnet."
        )
        if abs(drift) > 2 * max(abs(effect), 0.05):
            notes.append("Der Verlauf ist größer als die Wirkung der Änderung – Ergebnis mit Vorsicht lesen.")
        sec2 = {x.section: x for x in section_deltas(a2, b)}
        sections = [SectionDelta(x.section, (x.time_a + sec2[x.section].time_a) / 2, x.time_b)
                    for x in sections if x.section in sec2]
        bal2 = {x.zone: x for x in balance_deltas(a2, b)}
        balance = [BalanceDelta(x.zone, (x.a + bal2[x.zone].a) / 2, x.b) for x in balance if x.zone in bal2]
        conds = [Condition(c.name, c.unit, c.a, c.b, False) for c in conds]

    # Runden je Variante, um |effect| bei 80 % Power zu erkennen
    sd = float(np.sqrt(sigma2))
    needed = None
    if abs(effect) > 1e-3 and sd > 0:
        needed = int(np.ceil(2 * ((1.96 + 0.84) * sd / abs(effect)) ** 2))

    result = ABResult(
        laps_a=len(a_laps),
        laps_b=len(lb),
        mean_a=float(np.mean([lap.time_s for lap in a_laps])),
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
        sections=sections,
        conditions=conds,
        balance=balance,
    )
    from .compare_detail import build_detail

    result.detail = build_detail(result, a, b)
    return result


def distinct_changes(changes: list[SetupChange]) -> int:
    """Zahl der Änderungen; links/rechts gleich verstellt (z. B. beide Vorderfedern) zählt als eine."""
    keys = {(re.sub(r"(Left|Right)(Front|Rear)", r"\2", c.path), c.before, c.after) for c in changes}
    return len(keys)


def _list_changes(changes: list[SetupChange], limit: int = 4) -> str:
    txt = ", ".join(f"{c.path.split('.')[-1] if not c.path.startswith('Im Auto') else c.path[9:]} "
                    f"{c.before} → {c.after}" for c in changes[:limit])
    return txt + (" …" if len(changes) > limit else "")


def garage_problem(a1: SessionAnalysis, b: SessionAnalysis, a2: SessionAnalysis) -> str | None:
    """Ist der Garagen-Test A-B-A komplett? None = ja, sonst der Grund in Klartext für den Fahrer."""
    back = diff(a1.setup, a2.setup) + incar_changes(a1, a2)
    if back:
        return ("Das zweite A ist nicht exakt das Setup vom ersten A (" + _list_changes(back) + "). "
                "Nach Run B das gespeicherte Setup A wieder laden und den letzten Run noch einmal fahren.")
    changes = diff(a1.setup, b.setup) + incar_changes(a1, b)
    n = distinct_changes(changes)
    if n == 0:
        return "Zwischen A und B wurde nichts verstellt. Für Run B genau eine Einstellung ändern."
    if n > 1:
        return ("Zwischen A und B wurde mehr als eine Einstellung geändert (" + _list_changes(changes) + "). "
                "Für einen Test genau eine Einstellung ändern.")
    short = [(name, len(s.laps.valid)) for name, s in (("A", a1), ("B", b), ("zweites A", a2))
             if len(s.laps.valid) < MIN_BLOCK_LAPS]
    if short:
        return ("Zu wenig gewertete Runden in " + ", ".join(f"{n} ({k})" for n, k in short)
                + f" – je Run mindestens {MIN_BLOCK_LAPS}. Pro Run eine Aufwärmrunde und 5 saubere Runden fahren.")
    return None


def ab_within(a: SessionAnalysis) -> tuple["ABResult | None", str, str, str | None] | None:
    """A-B-A innerhalb EINER Session (im Auto umgestellt).

    None = in der Session wurde nichts verstellt. Sonst (Ergebnis, Name A, Name B, Problem):
    Problem ist None, wenn der Test komplett ist – A, dann B, dann wieder exakt A, jeder Block mit
    mindestens MIN_BLOCK_LAPS gewerteten Runden. Ist der Test unvollständig, gibt es kein Ergebnis.
    """
    from .analysis import analyze_subset
    from .incar import lap_groups

    groups = lap_groups(a.incar)
    if len(groups) < 2:
        return None
    items = list(groups.items())
    base_key, base_laps = min(items, key=lambda kv: min(kv[1]))
    others = [kv for kv in items if kv[0] != base_key]
    other_key, other_laps = max(others, key=lambda kv: len(kv[1]))

    def name(key) -> str:
        return ", ".join(f"{lbl} {v:g}" for lbl, v in key)

    def laps_txt(ns) -> str:
        return ", ".join(map(str, ns))

    name_a = f"{name(base_key)} (Runden {laps_txt(base_laps)})"
    name_b = f"{name(other_key)} (Runden {laps_txt(other_laps)})"
    first_b, last_b = min(other_laps), max(other_laps)
    a1 = [n for n in base_laps if n < first_b]
    a2 = [n for n in base_laps if n > last_b]
    problem = None
    if len(others) > 1:
        extra = [name(k) for k, _ in others if k != other_key]
        problem = ("Es wurde mehr als einmal umgestellt (zusätzlich " + "; ".join(extra) + "). "
                   "Ein Test ist A, B und zurück auf exakt A – sonst nichts verstellen.")
    elif any(first_b < n < last_b for n in base_laps):
        problem = "Block B ist unterbrochen. B bitte am Stück fahren: A, B, A."
    elif not a2:
        problem = (f"Der zweite A-Block fehlt: Nach B ({name(other_key)}) wurde nicht wieder auf exakt "
                   f"{name(base_key)} zurückgestellt. Ohne das zweite A lässt sich nicht trennen, was die Änderung "
                   "und was Strecke, Reifen und Fahrer bewirkt haben.")
    elif min(len(a1), len(other_laps), len(a2)) < MIN_BLOCK_LAPS:
        problem = (f"Zu wenig gewertete Runden (A {len(a1)}, B {len(other_laps)}, zweites A {len(a2)}) – je Block "
                   f"mindestens {MIN_BLOCK_LAPS}. Erster Block: Aufwärmrunde plus 5 Runden, danach je 5 Runden.")
    if problem:
        return None, name_a, name_b, problem

    sa = analyze_subset(a, base_laps)
    sb = analyze_subset(a, other_laps)
    r = ab_compare(sa, sb)
    mixed = sorted(set().union(*(s.mixed_laps for s in a.incar)))
    if mixed:
        r.notes.append(f"Umstell-Runde(n) {laps_txt(mixed)} nicht gewertet (zwei Einstellungen in einer Runde).")
    lap_time = {lap.number: lap.time_s for lap in a.laps.laps}
    drift = float(np.mean([lap_time[n] for n in a2]) - np.mean([lap_time[n] for n in a1]))
    r.notes.append(f"Kontrolle zweites A: {drift:+.3f} s pro Runde gegenüber dem ersten A bei identischer Einstellung.")
    r.notes.append("Vergleich innerhalb einer Session – Bedingungen nahezu gleich, Ergebnis besonders belastbar.")
    return r, name_a, name_b, None

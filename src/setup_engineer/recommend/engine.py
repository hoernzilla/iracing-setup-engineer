"""Empfehlungs-Engine: aus Symptomen konkrete, getestete Setup-Änderungen ableiten.

Ablauf
1. Symptome mit Schweregrad aus der Analyse (symptoms.py)
2. Jede Änderung der Wissensbasis bewerten: Nutzen für aktive Symptome minus
   Schaden für andere aktive Symptome
3. Belege aus der Test-Historie einrechnen (bestätigt -> höhere Konfidenz und
   Effektgröße; widerlegt -> abwerten)
4. Konkreten Zielwert bestimmen (Schrittweite aus echten Verstellungen im Auto,
   sonst aus dem Werteformat)
5. Testplan: im Auto verstellbar -> A-B-A in einer Session, sonst zwei Runs
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ..analysis import SessionAnalysis
from ..incar import label as incar_label
from . import symptoms as S
from .history import History, TestRecord
from .knowledge import CANDIDATES, Candidate, find_parameter

HARM_WEIGHT = 0.8
MIN_BENEFIT = 0.15
INCAR_BONUS = 0.05  # bei gleicher Wirkung: im Auto verstellbar ist schneller und sauberer zu testen

# Balance-Bereiche der Historie, die zu einem Symptom gehören
SYMPTOM_ZONES = {
    S.MID_UNDERSTEER: ("Tempo 0–150 km/h", "Tempo 150–200 km/h"),
    S.HS_UNDERSTEER: ("Tempo 200–250 km/h", "Tempo > 250 km/h"),
    S.HS_OVERSTEER: ("Tempo 200–250 km/h", "Tempo > 250 km/h"),
}


@dataclass
class Evidence:
    record: TestRecord
    change: dict
    zone_label: str
    measured_shift: float  # gemessene Veränderung des Lenküberschusses (B − A)
    shift_per_step: float  # daraus: Veränderung für EINE Stufe in Empfehlungsrichtung
    confirms: bool
    helpful: bool = True  # betrifft die Wirkung ein Symptom, das die Empfehlung verbessern soll?

    def text(self) -> str:
        c = self.change
        verb = "bestätigt" if self.confirms else "widerspricht"
        return (
            f"Gemessen ({self.record.quality}): {c['path'].replace('Im Auto: ', '')} {c['before']} → {c['after']} "
            f"veränderte den Lenküberschuss bei {self.zone_label} um {self.measured_shift * 100:+.0f} Pkt. "
            f"→ für diese Empfehlung ca. {self.shift_per_step * 100:+.1f} Pkt. je Stufe ({verb} die erwartete Richtung)."
        )


@dataclass
class Recommendation:
    candidate: Candidate
    parameter: str  # Setup-Pfad oder Klartext
    current: str
    proposed: str
    step_known: bool
    score: float
    benefit: float
    harm: float
    helps: list[tuple[str, float]]  # (Symptom-Titel, Stärke × Schweregrad)
    hurts: list[tuple[str, float]]
    evidence: list[Evidence] = field(default_factory=list)
    incar: bool = False
    tested: TestRecord | None = None  # genau diese Richtung schon getestet
    revert_of: TestRecord | None = None  # Rücknahme einer getesteten, langsameren Änderung

    @property
    def confidence(self) -> str:
        if self.revert_of is not None:
            level = "hoch" if self.revert_of.within_session or not self.revert_of.conditions_differ else "mittel"
            return f"{level} – eigener Test war mit dem aktuellen Wert langsamer (Messung: {self.revert_of.quality})"
        if self.tested is not None and self.tested.lap_delta_s is not None and self.tested.lap_delta_s > 0:
            return "niedrig (bereits getestet: war langsamer)"
        if any(not e.confirms for e in self.evidence):
            return "niedrig (Messung widerspricht)"
        if any(e.confirms and e.helpful for e in self.evidence):
            return "hoch (durch Messung bestätigt)"
        if self.harm > 0.5 * self.benefit:
            return "niedrig (deutliche Nebenwirkungen)"
        return "mittel (Fahrdynamik-Grundlage, noch nicht gemessen)"

    def test_plan(self) -> str:
        if self.incar:
            return (
                f"Im Auto verstellbar → A-B-A in **einer** Session: 5 gewertete Runden mit {self.current}, "
                f"dann im Auto auf {self.proposed}, 5 Runden, zurück auf {self.current}, 5 Runden. "
                "Die Analyse erkennt die Wechsel und vergleicht die Rundengruppen unter gleichen Bedingungen."
            )
        return (
            f"Garage-Änderung → zwei Runs direkt hintereinander in derselben Session (gleiche Tageszeit/Wetter), "
            f"je mindestens 6 gewertete Runden: erst {self.current}, dann {self.proposed}. Danach `compare A.ibt B.ibt --save`."
        )


@dataclass
class RecommendationSet:
    symptoms: list[S.Symptom]
    driver_hints: list[S.DriverHint]
    recommendations: list[Recommendation]
    avoid: list[Recommendation]


# ------------------------------------------------------------------ Hilfen
_NUM = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*(.*)$")


def _decimals(raw: str) -> int:
    m = re.match(r"^\s*[-+]?\d+(?:\.(\d+))?", raw)
    return len(m.group(1)) if m and m.group(1) else 0


def _current_and_step(a: SessionAnalysis, cand: Candidate):
    """(Anzeige-Parameter, aktueller Wert als Zahl oder None, Rohtext, Einheit, Schritt, Schritt bekannt?, im Auto?)"""
    incar = next((s for s in a.incar if cand.incar_channel and s.channel == cand.incar_channel), None)
    setup_v = find_parameter(a.setup, cand)
    if incar is not None and incar.effective is not None:
        vals = sorted(set(incar.session_values))
        diffs = [round(b - a_, 4) for a_, b in zip(vals, vals[1:]) if b - a_ > 1e-6]
        step = min(diffs) if diffs else None
        known = step is not None
        unit = ""
        if cand.incar_channel == "dcBrakeBias":
            unit = "%"
            step, known = (step or 0.25) * 2, True  # 0,5 % als spürbarer, aber kleiner Schritt
        elif step is None and float(incar.effective).is_integer():
            step, known = 1.0, True  # Schalter im Auto mit ganzen Stufen
        param = incar_label(cand.incar_channel) + " (im Auto)"
        return param, incar.effective, f"{incar.effective:g}", unit, step or 1.0, known, True
    if setup_v is None:
        return None
    unit = setup_v.unit
    if setup_v.value is None:
        return setup_v.path, None, setup_v.raw, unit, None, False, False
    if "click" in unit.lower() or (unit == "" and float(setup_v.value).is_integer()):
        step, known = 1.0, True
    elif unit.strip() == "%":
        step, known = 0.5, False
    elif _decimals(setup_v.raw) >= 1:
        step, known = 10 ** -_decimals(setup_v.raw) * 5, False
    else:
        step, known = 1.0, False
    return setup_v.path, setup_v.value, setup_v.raw, unit, step, known, cand.incar_channel is not None


def _fmt_value(v: float, unit: str) -> str:
    u = unit.strip()
    if u in ("%",):
        return f"{v:g} %"
    return f"{v:g} {u}".strip()


def _change_matches(change_path: str, cand: Candidate) -> bool:
    p = change_path.lower()
    if p.startswith("im auto: ") and cand.incar_channel:
        return p[len("im auto: ") :] == incar_label(cand.incar_channel).lower()
    return all(f in p for f in cand.setup_fragments)


def _evidence(cand: Candidate, history: History | None, car: str) -> list[Evidence]:
    if history is None:
        return []
    out = []
    for rec in history.for_car(car):
        for ch in rec.changes:
            if not _change_matches(ch["path"], cand) or not ch.get("delta"):
                continue
            for sym, eff in cand.effects.items():
                zones = SYMPTOM_ZONES.get(sym)
                if not zones or eff == 0:
                    continue
                shifts = [rec.balance[z] for z in zones if z in rec.balance]
                if not shifts:
                    continue
                shift = sum(shifts) / len(shifts)
                if abs(shift) < 0.02:
                    continue
                per_step = shift / ch["delta"] * cand.direction  # eine Stufe in Empfehlungsrichtung
                # eff > 0 bei *_UNTERSTEUERN heißt: Untersteuern soll sinken -> per_step < 0 erwartet
                wants_less_understeer = (eff > 0) == ("untersteuern" in sym)
                confirms = (per_step < 0) == wants_less_understeer
                zone_label = " und ".join(z.replace("Tempo ", "") for z in zones)
                out.append(Evidence(rec, ch, zone_label, shift, per_step, confirms, helpful=eff > 0))
                break
    return out


def _already_tested(cand: Candidate, history: History | None, car: str) -> TestRecord | None:
    """Wurde genau diese Änderungsrichtung schon gefahren?"""
    if history is None:
        return None
    for rec in history.for_car(car):
        for ch in rec.changes:
            d = ch.get("delta")
            if d and _change_matches(ch["path"], cand) and (d > 0) == (cand.direction > 0):
                return rec
    return None


# ----------------------------------------------------------------- Engine
def recommend(a: SessionAnalysis, history: History | None = None, top: int = 4) -> RecommendationSet:
    symptoms, hints = S.detect_symptoms(a)
    sev = {s.key: s.severity for s in symptoms}
    titles = {s.key: s.title for s in symptoms}

    recs: list[Recommendation] = []
    for cand in CANDIDATES:
        info = _current_and_step(a, cand)
        if info is None:
            continue
        param, cur, raw, unit, step, known, incar = info
        helps = [(titles[k], e * sev[k]) for k, e in cand.effects.items() if e > 0 and k in sev]
        hurts = [(titles[k], -e * sev[k]) for k, e in cand.effects.items() if e < 0 and k in sev]
        benefit = sum(x for _, x in helps)
        harm = sum(x for _, x in hurts)
        if benefit < MIN_BENEFIT:
            continue
        ev = _evidence(cand, history, a.ibt.car_name)
        score = benefit - HARM_WEIGHT * harm + (INCAR_BONUS if incar else 0.0)
        # Belege: bestätigte NÜTZLICHE Wirkung wertet auf, bestätigte schädliche ab
        for e in ev:
            if not e.confirms:
                score -= 0.5
            elif e.helpful:
                score += 0.15
            else:
                score -= 0.3
        tested = _already_tested(cand, history, a.ibt.car_name)
        if tested is not None and tested.lap_delta_s is not None and tested.lap_delta_s > 0:
            score -= 0.3
        if cur is not None and step:
            target = round(cur + cand.direction * step, 4)
            proposed = _fmt_value(target, unit)
            current = _fmt_value(cur, unit)
            if not known:
                # Schrittweite unbekannt -> keine Scheingenauigkeit
                proposed = f"nächste Stufe {'über' if cand.direction > 0 else 'unter'} {current} (Garage)"
        else:
            current = raw
            proposed = "eine Stufe " + ("höher" if cand.direction > 0 else "niedriger")
        recs.append(
            Recommendation(
                candidate=cand,
                parameter=param,
                current=current,
                proposed=proposed,
                step_known=known,
                score=score,
                benefit=benefit,
                harm=harm,
                helps=sorted(helps, key=lambda x: -x[1]),
                hurts=sorted(hurts, key=lambda x: -x[1]),
                evidence=ev,
                incar=incar,
                tested=tested,
            )
        )

    # Pro Parameter nur die bessere Richtung behalten
    best: dict[str, Recommendation] = {}
    for r in sorted(recs, key=lambda r: -r.score):
        key = r.candidate.setup_fragments
        best.setdefault(str(key), r)
    ranked = sorted(best.values(), key=lambda r: -r.score)
    good = [r for r in ranked if r.score > 0.1]
    avoid = [r for r in recs if any(not e.confirms for e in r.evidence)]
    reverts = _reverts(a, history, sev, titles)
    taken = {r.candidate.setup_fragments for r in reverts}
    rest = [r for r in good if r.candidate.setup_fragments not in taken]
    return RecommendationSet(symptoms, hints, reverts + _diversify(rest, max(top - len(reverts), 1)), avoid)


def _reverts(a: SessionAnalysis, history: History | None, sev: dict, titles: dict) -> list[Recommendation]:
    """Fährst du gerade mit einem Wert, der im eigenen Test langsamer war? Dann zuerst zurück."""
    if history is None:
        return []
    out: list[Recommendation] = []
    for rec in history.for_car(a.ibt.car_name):
        if rec.lap_delta_s is None or rec.lap_delta_s <= 0:
            continue
        for ch in rec.changes:
            d = ch.get("delta")
            if not d:
                continue
            for cand in CANDIDATES:
                if not _change_matches(ch["path"], cand) or (cand.direction > 0) == (d > 0):
                    continue  # nur die Gegenrichtung = Rücknahme
                info = _current_and_step(a, cand)
                if info is None:
                    continue
                param, cur, raw, unit, step, known, incar = info
                try:
                    after, before = float(ch["after"]), float(ch["before"])
                except (TypeError, ValueError):
                    continue
                if cur is None or abs(cur - after) > 1e-6:
                    continue
                helps = [(titles[k], e * sev[k]) for k, e in cand.effects.items() if e > 0 and k in sev]
                hurts = [(titles[k], -e * sev[k]) for k, e in cand.effects.items() if e < 0 and k in sev]
                out.append(
                    Recommendation(
                        candidate=cand,
                        parameter=param,
                        current=_fmt_value(cur, unit),
                        proposed=_fmt_value(before, unit),
                        step_known=True,
                        score=10.0,
                        benefit=sum(x for _, x in helps),
                        harm=sum(x for _, x in hurts),
                        helps=sorted(helps, key=lambda x: -x[1]) or [("Rücknahme einer langsameren Änderung", 1.0)],
                        hurts=sorted(hurts, key=lambda x: -x[1]),
                        evidence=_evidence(cand, history, a.ibt.car_name),
                        incar=incar,
                        revert_of=rec,
                    )
                )
    return out


def _diversify(ranked: list[Recommendation], top: int) -> list[Recommendation]:
    """Je Problembereich die beste Änderung statt der N stärksten zum selben Thema.

    Erkenntnis aus echten GTP-Daten: Ohne Streuung landeten alle Vorschläge beim
    Heck/Ausgang, das Highspeed-Untersteuern (Aero) fiel ganz heraus.
    """
    picked: list[Recommendation] = []
    covered: set[str] = set()
    for r in ranked:
        if not r.helps:
            continue
        primary = r.helps[0][0]
        if primary in covered:
            continue
        picked.append(r)
        covered.add(primary)
        if len(picked) >= top:
            break
    return picked


def expected_text(r: Recommendation) -> str:
    parts = []
    for e in r.evidence:
        if e.confirms:
            parts.append(f"{e.zone_label}: ca. {e.shift_per_step * 100:+.1f} Pkt. Lenküberschuss je Stufe (gemessen)")
    return "; ".join(parts)


def is_finite(x: float | None) -> bool:
    return x is not None and math.isfinite(x)

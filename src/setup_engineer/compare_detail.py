"""Ausführlicher A/B-Bericht: Runden, Kurventempos, Plattform, Reifen, Traktion – und ein Fazit.

Das Fazit wird aus den Messwerten formuliert, damit der Bericht ohne
zusätzliche Erklärung verständlich ist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from .analysis import SessionAnalysis

if TYPE_CHECKING:  # pragma: no cover
    from .compare import ABResult

BAND_FLAG = 0.05  # 5 Prozentpunkte Balanceänderung im Tempoband gilt als deutlich
CORNER_FLAG = 0.08  # 8 Prozentpunkte in einer Kurve
VMAX_FLAG = 1.5  # km/h

# Erwartete Wirkung auf das Untersteuern bei Erhöhung des Werts (+1 = mehr Untersteuern).
# Bewusst klein und konservativ; wird mit der Empfehlungs-Engine ausgebaut.
EXPECTED_UNDERSTEER = (
    (("stabilisator vorne",), +1),
    (("front", "arb"), +1),
    (("stabilisator hinten",), -1),
    (("rear", "arb"), -1),
    (("front", "spring"), +1),
    (("front", "heave"), +1),
    (("rear", "spring"), -1),
    (("rear", "third"), -1),
    (("rearwing",), +1),
)
# Änderungen, die die Endgeschwindigkeit beeinflussen können
VMAX_RELEVANT = ("wing", "aero", "gear", "ridehe", "rake", "pushrod", "enginepower", "motorleistung")


@dataclass
class LapRow:
    number: int
    time_s: float
    status: str


@dataclass
class Pair:
    label: str
    a: float | None
    b: float | None
    unit: str = ""
    digits: int = 1

    @property
    def delta(self) -> float | None:
        return None if self.a is None or self.b is None else self.b - self.a


@dataclass
class ABDetail:
    laps_a: list[LapRow]
    laps_b: list[LapRow]
    overview: list[Pair]
    corner_speeds: list[Pair]
    platform: list[Pair]
    tires: list[Pair]
    traction: list[Pair]
    style: list[Pair]
    conclusions: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ Bausteine
def _lap_rows(s: SessionAnalysis) -> list[LapRow]:
    by_no = {lap.number: lap for lap in s.laps.laps}
    rows = []
    for lap in s.laps.laps:
        prev = by_no.get(lap.number - 1)
        if not lap.valid:
            status = ", ".join(lap.reasons)
        elif prev is not None and any("Boxengasse" in r for r in prev.reasons):
            status = "Aufwärmrunde (nicht gewertet)"
        else:
            status = "gewertet"
        rows.append(LapRow(lap.number, lap.time_s, status))
    return rows


def _racing(s: SessionAnalysis) -> list:
    rows = {r.number: r for r in _lap_rows(s)}
    return [lap for lap in s.laps.valid if rows[lap.number].status == "gewertet"]


def _vmax(s: SessionAnalysis) -> float | None:
    laps = _racing(s)
    if not laps:
        return None
    v = s.ibt.get("Speed") * 3.6
    return float(np.median([np.nanmax(v[lap.slice]) for lap in laps]))


def _corner_pairs(a: SessionAnalysis, b: SessionAnalysis) -> list[Pair]:
    """Kurven über die Scheitelposition zuordnen (Erkennung kann leicht abweichen)."""
    if not a.style or not b.style:
        return []
    sa = {c.corner: c for c in a.style.corners}
    sb = {c.corner: c for c in b.style.corners}
    out = []
    for ca in a.corners:
        cb = min(b.corners, key=lambda c: abs(c.apex - ca.apex), default=None)
        if cb is None or abs(cb.apex - ca.apex) > 0.01 or ca.name not in sa or cb.name not in sb:
            continue
        out.append(Pair(f"{ca.name} ({ca.direction})", sa[ca.name].min_speed_kmh, sb[cb.name].min_speed_kmh, "km/h"))
    return out


def _platform_pairs(a: SessionAnalysis, b: SessionAnalysis) -> list[Pair]:
    out: list[Pair] = []
    pa, pb = a.platform, b.platform
    if not pa or not pb:
        return out
    if pa.aero and pb.aero:
        out += [
            Pair("Ride Height vorne bei Topspeed", pa.aero.front_meas_mm, pb.aero.front_meas_mm, "mm"),
            Pair("Ride Height hinten bei Topspeed", pa.aero.rear_meas_mm, pb.aero.rear_meas_mm, "mm"),
            Pair(
                "Rake bei Topspeed",
                pa.aero.rear_meas_mm - pa.aero.front_meas_mm,
                pb.aero.rear_meas_mm - pb.aero.front_meas_mm,
                "mm",
            ),
        ]
    tb = {t.channel: t for t in pb.travel}
    for t in pa.travel:
        if t.channel in tb:
            out.append(Pair(f"Federweg-Ausnutzung {t.channel}", t.usage * 100, tb[t.channel].usage * 100, "%", 0))

    def touch(p) -> int:
        return sum(c.laps for c in p.contacts if c.kind == "Aufsetzen")

    out.append(Pair("Aufsetzer (Ereignisse × Runden)", touch(pa), touch(pb), "", 0))
    return out


def _tire_pairs(a: SessionAnalysis, b: SessionAnalysis) -> list[Pair]:
    ta, tb = a.tires, b.tires
    if not ta or not tb or not ta.last or not tb.last:
        return []
    out = []
    for w in ("LF", "RF", "LR", "RR"):
        if w in ta.last.pressure_kpa and w in tb.last.pressure_kpa:
            out.append(Pair(f"Druck {w} (letzte Runde)", ta.last.pressure_kpa[w], tb.last.pressure_kpa[w], "kPa"))
    for w in ("LF", "RF", "LR", "RR"):
        if w in ta.last.surface_c and w in tb.last.surface_c:
            out.append(Pair(f"Oberfläche {w} (letzte Runde)", ta.last.surface_c[w], tb.last.surface_c[w], "°C", 0))
    return out


def _traction_pairs(a: SessionAnalysis, b: SessionAnalysis) -> list[Pair]:
    sb = {s.corner: s for s in b.slip}
    out = []
    for s in a.slip:
        o = sb.get(s.corner)
        if o is None:
            continue
        if s.spin_exit is not None and o.spin_exit is not None and max(s.spin_exit, o.spin_exit) >= 0.03:
            out.append(Pair(f"{s.corner} Durchdrehen im Ausgang", s.spin_exit * 100, o.spin_exit * 100, "%", 0))
        if s.lock_brake is not None and o.lock_brake is not None and max(s.lock_brake, o.lock_brake) >= 0.02:
            out.append(Pair(f"{s.corner} Blockieren beim Bremsen", s.lock_brake * 100, o.lock_brake * 100, "%", 0))
    return out


def _style_pairs(a: SessionAnalysis, b: SessionAnalysis) -> list[Pair]:
    if not a.style or not b.style:
        return []
    return [
        Pair("Trail Braking", a.style.trail_braking * 100, b.style.trail_braking * 100, "%", 0),
        Pair("Spitzen-Bremsdruck", a.style.peak_brake * 100, b.style.peak_brake * 100, "%", 0),
        Pair("Streuung Scheiteltempo", a.style.consistency_kmh, b.style.consistency_kmh, "km/h"),
    ]


# ---------------------------------------------------------------------- Fazit
def _expected_sign(path: str) -> int | None:
    p = path.lower().replace(" ", "")
    for frags, sign in EXPECTED_UNDERSTEER:
        if all(f.replace(" ", "") in p for f in frags):
            return sign
    return None


def _fmt_pts(x: float) -> str:
    return f"{x * 100:+.0f} Pkt."


def _conclusions(r: "ABResult", d: ABDetail, a: SessionAnalysis, b: SessionAnalysis) -> list[str]:
    out: list[str] = []
    diff_s = r.mean_b - r.mean_a

    # 1. Ergebnis
    if np.isfinite(r.p_value):
        faster = "schneller" if r.effect_s < 0 else "langsamer"
        clear = "statistisch eindeutig" if r.p_value < 0.05 else "statistisch nicht eindeutig"
        ptxt = "p < 0,001" if r.p_value < 0.001 else f"p = {r.p_value:.3f}"
        out.append(
            f"**Rundenzeit:** B ist im Schnitt {abs(r.effect_s):.3f} s pro Runde {faster} ({clear}, {ptxt}). "
            f"Rohdifferenz der Mittelwerte: {diff_s:+.3f} s."
        )

    # 2. Was wurde geändert
    if r.setup_changes:
        ch = "; ".join(f"{c.path.replace('Im Auto: ', '')} {c.before} → {c.after}" for c in r.setup_changes)
        out.append(f"**Geändert:** {ch}.")
    else:
        out.append("**Geändert:** nichts – der Unterschied stammt aus Fahrer und Bedingungen.")

    # 3. Bedingungen
    warn = [c for c in r.conditions if c.warn]
    if warn:
        txt = ", ".join(
            f"{c.name} {(c.b - c.a) / c.a * 100:+.1f} %" if c.name == "Luftdichte" else f"{c.name} {c.b - c.a:+.1f} {c.unit}"
            for c in warn
        )
        out.append(
            f"**Bedingungen nicht gleich** ({txt}). Die Zeitdifferenz lässt sich deshalb nicht allein der Änderung "
            "zuschreiben."
        )

    # 4. Endgeschwindigkeit
    vm = next((p for p in d.overview if p.label.startswith("Endgeschwindigkeit")), None)
    if vm and vm.delta is not None and abs(vm.delta) >= VMAX_FLAG:
        vmax_changes = [c for c in r.setup_changes if any(k in c.path.lower().replace(" ", "") for k in VMAX_RELEVANT)]
        if not vmax_changes:
            reason = (
                "Die Änderungen wirken kaum auf die Endgeschwindigkeit – das passt zu den Bedingungen"
                + (" (Luftdichte)." if any(c.name == "Luftdichte" for c in warn) else ".")
            )
        else:
            reason = "Kann von der Änderung an Aero/Übersetzung/Ride Height kommen."
        out.append(f"**Endgeschwindigkeit** {vm.delta:+.1f} km/h. {reason}")

    # 5. Balance
    bands = [x for x in r.balance if x.zone.startswith("Tempo")]
    corners = [x for x in r.balance if not x.zone.startswith("Tempo")]
    strong_bands = [x for x in bands if abs(x.b - x.a) >= BAND_FLAG]
    strong_corners = sorted([x for x in corners if abs(x.b - x.a) >= CORNER_FLAG], key=lambda x: -abs(x.b - x.a))
    if strong_bands or strong_corners:
        parts = [f"{x.zone.replace('Tempo ', '')} {_fmt_pts(x.b - x.a)}" for x in strong_bands]
        parts += [f"{x.zone.replace(' Scheitel', '')} {_fmt_pts(x.b - x.a)}" for x in strong_corners[:5]]
        calm = [x for x in bands if abs(x.b - x.a) < 0.03]
        tail = f"; kaum Änderung bei {', '.join(x.zone.replace('Tempo ', '') for x in calm)}" if calm else ""
        out.append(f"**Balance** (+ = mehr Untersteuern): {', '.join(parts)}{tail}.")
        # Erwartete Wirkung prüfen (mittlere Bänder sind am wenigsten aero-dominiert)
        mid = [x for x in bands if not x.zone.endswith(("250 km/h", "500 km/h")) and "> 250" not in x.zone]
        mid_shift = float(np.mean([x.b - x.a for x in mid])) if mid else 0.0
        for c in r.setup_changes:
            sign = _expected_sign(c.path)
            if sign is None or c.delta is None or c.delta == 0 or abs(mid_shift) < 0.02:
                continue
            expected = sign * np.sign(c.delta)
            if np.sign(mid_shift) == expected:
                verb = "mehr" if expected > 0 else "weniger"
                out.append(
                    f"Das entspricht der erwarteten Wirkung von „{c.path.replace('Im Auto: ', '')} {c.before} → {c.after}“ "
                    f"({verb} Untersteuern)."
                )
                base = a.speed_balance.low if a.speed_balance and a.speed_balance.low is not None else None
                high = a.speed_balance.high if a.speed_balance and a.speed_balance.high is not None else None
                if expected > 0 and ((base or 0) > 0.0 or (high or 0) > 0.10):
                    out.append(
                        "Da das Auto vorher schon untersteuerte, geht diese Änderung für die Balance in die falsche Richtung."
                    )
            else:
                out.append(
                    f"Die Balance hat sich entgegen der erwarteten Wirkung von „{c.path.replace('Im Auto: ', '')}“ verschoben – "
                    "andere Einflüsse (Bedingungen, Fahrweise) überwiegen oder die Wirkung ist hier anders."
                )

    # 6. Wo liegt die Zeit
    if r.sections:
        total = sum(s.delta for s in r.sections)
        same_sign = all(np.sign(s.delta) == np.sign(total) or abs(s.delta) < 0.01 for s in r.sections)
        top = sorted(r.sections, key=lambda s: -abs(s.delta))[:3]
        share = sum(abs(s.delta) for s in top) / max(sum(abs(s.delta) for s in r.sections), 1e-9)
        if same_sign and share < 0.5:
            out.append(
                f"**Zeitverteilung:** gleichmäßig über die Runde ({total:+.3f} s, kein Abschnitt dominiert) – "
                "typisch für Bedingungen oder Leistung, nicht für einzelne Kurven."
            )
        else:
            out.append(
                "**Zeitverteilung:** konzentriert auf "
                + ", ".join(f"{s.section} ({s.delta:+.3f} s)" for s in top)
                + "."
            )

    # 7. Kurventempo
    if d.corner_speeds:
        worst = sorted([p for p in d.corner_speeds if p.delta is not None], key=lambda p: p.delta)[:3]
        if worst and worst[0].delta < -1.0:
            out.append(
                "**Größte Tempoverluste im Scheitel:** "
                + ", ".join(f"{p.label.split(' ')[0]} {p.delta:+.1f} km/h" for p in worst if p.delta < -1.0)
                + "."
            )

    # 8. Plattform / Traktion
    notable = [p for p in d.platform if p.delta is not None and p.unit == "mm" and abs(p.delta) >= 1.0]
    notable += [p for p in d.platform if p.delta is not None and p.unit == "%" and abs(p.delta) >= 5]
    if notable:
        txt = "**Plattform:** " + ", ".join(
            f"{p.label} {p.delta:+.1f} {'Pkt.' if p.unit == '%' else p.unit}" for p in notable
        )
        rh = [p for p in notable if p.label.startswith("Ride Height") and p.delta is not None]
        thinner = any(c.name == "Luftdichte" and c.b < c.a for c in warn)
        if rh and all(p.delta > 0 for p in rh) and thinner:
            txt += " – das Auto fährt bei Topspeed höher; passt zu weniger Abtrieb durch die geringere Luftdichte"
        out.append(txt + ".")
    spin = [p for p in d.traction if p.delta is not None and abs(p.delta) >= 5]
    if spin:
        out.append("**Traktion/Bremse:** " + ", ".join(f"{p.label} {p.delta:+.0f} Pkt" for p in spin) + ".")

    # 9. Nächster Schritt
    if warn:
        out.append(
            "**Nächster Schritt:** In einer Session A-B-A fahren (je 5 Runden), die Einstellung im Auto umstellen – "
            "die Analyse erkennt die Wechsel und vergleicht unter gleichen Bedingungen."
        )
    return out


def build_detail(r: "ABResult", a: SessionAnalysis, b: SessionAnalysis) -> ABDetail:
    best_a = min((lap.time_s for lap in _racing(a)), default=None)
    best_b = min((lap.time_s for lap in _racing(b)), default=None)
    overview = [
        Pair("Bestzeit (gewertet)", best_a, best_b, "s", 3),
        Pair("Durchschnitt (gewertet)", r.mean_a, r.mean_b, "s", 3),
        Pair("Endgeschwindigkeit (Median)", _vmax(a), _vmax(b), "km/h"),
    ]
    if a.speed_balance and b.speed_balance:
        overview.append(
            Pair(
                "Untersteuern schnell minus langsam",
                (a.speed_balance.high - a.speed_balance.low) * 100 if a.speed_balance.high is not None else None,
                (b.speed_balance.high - b.speed_balance.low) * 100 if b.speed_balance.high is not None else None,
                "Pkt.",
                0,
            )
        )
    d = ABDetail(
        laps_a=_lap_rows(a),
        laps_b=_lap_rows(b),
        overview=overview,
        corner_speeds=_corner_pairs(a, b),
        platform=_platform_pairs(a, b),
        tires=_tire_pairs(a, b),
        traction=_traction_pairs(a, b),
        style=_style_pairs(a, b),
    )
    d.conclusions = _conclusions(r, d, a, b)
    return d

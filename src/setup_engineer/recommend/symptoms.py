"""Symptome: was am Auto nicht stimmt, mit Schweregrad (0..1) und Belegen.

Nur Befunde, die als Setup-Thema eingestuft sind ("Auto"), gehen ein.
Fahrerbedingte Auffälligkeiten werden separat als Fahrhinweise ausgegeben.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..analysis import SessionAnalysis

# Schlüssel der Symptome (werden in der Wissensbasis referenziert)
HS_UNDERSTEER = "hs_untersteuern"
HS_OVERSTEER = "hs_uebersteuern"
MID_UNDERSTEER = "mid_untersteuern"
ENTRY_OVERSTEER = "eingang_uebersteuern"
ENTRY_UNDERSTEER = "eingang_untersteuern"
EXIT_OVERSTEER = "ausgang_uebersteuern"
TRACTION = "traktion"
BOTTOMING = "aufsetzen"
RAKE_DEFICIT = "rake_zu_klein"
RAKE_EXCESS = "rake_zu_gross"
LOCKUP = "blockieren"
TRAVEL_LIMIT = "federweg_am_anschlag"

TITLES = {
    HS_UNDERSTEER: "Untersteuern im schnellen Bereich (Aero-Balance hinten)",
    HS_OVERSTEER: "Übersteuern im schnellen Bereich (Aero-Balance vorne)",
    MID_UNDERSTEER: "Untersteuern in langsamen/mittleren Kurven (mechanische Balance)",
    ENTRY_OVERSTEER: "Übersteuern beim Einlenken",
    ENTRY_UNDERSTEER: "Untersteuern beim Einlenken",
    EXIT_OVERSTEER: "Übersteuern am Kurvenausgang",
    TRACTION: "Durchdrehende Hinterräder am Ausgang",
    BOTTOMING: "Auto setzt auf",
    RAKE_DEFICIT: "Rake bei Topspeed kleiner als im Aero-Rechner",
    RAKE_EXCESS: "Rake bei Topspeed größer als im Aero-Rechner",
    LOCKUP: "Blockierende Räder beim Bremsen",
    TRAVEL_LIMIT: "Federweg nahe am Anschlag",
}


@dataclass
class Symptom:
    key: str
    severity: float  # 0..1
    evidence: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return TITLES.get(self.key, self.key)


@dataclass
class DriverHint:
    corner: str
    text: str


def _clip(x: float) -> float:
    return float(min(max(x, 0.0), 1.0))


def detect_symptoms(a: SessionAnalysis) -> tuple[list[Symptom], list[DriverHint]]:
    out: dict[str, Symptom] = {}

    def add(key: str, sev: float, ev: str) -> None:
        if sev <= 0:
            return
        s = out.setdefault(key, Symptom(key, 0.0))
        s.severity = max(s.severity, _clip(sev))
        s.evidence.append(ev)

    # --- Balance nach Tempo
    sb = a.speed_balance
    if sb and sb.low is not None and sb.high is not None:
        d = sb.high - sb.low
        if d > 0.08:
            add(HS_UNDERSTEER, (d - 0.05) / 0.20, f"schnell {sb.high * 100:+.0f} % vs. langsam {sb.low * 100:+.0f} % Lenküberschuss")
        elif d < -0.08:
            add(HS_OVERSTEER, (-d - 0.05) / 0.20, f"schnell {sb.high * 100:+.0f} % vs. langsam {sb.low * 100:+.0f} % Lenküberschuss")
        mid = [b for b in sb.bands if b.band.startswith(("0", "150"))]
        if mid:
            m = float(np.mean([b.understeer for b in mid]))
            if m > 0.06:
                add(MID_UNDERSTEER, (m - 0.03) / 0.15, f"langsam/mittel {m * 100:+.0f} % Lenküberschuss im Grenzbereich")

    # --- Kurvenphasen (nur Setup-Themen)
    hints: list[DriverHint] = []
    for b in a.balance:
        if b.verdict == "Fahrer":
            r = b.entry_speed_corr or 0.0
            if b.understeer >= 0:
                text = (
                    "schiebt umso mehr, je schneller du einfährst" if r > 0 else "schiebt umso mehr, je langsamer du einfährst"
                )
                tip = "Eingangstempo konstanter wählen und das Auto zuerst rotieren lassen, dann Lenkung aufbauen."
            else:
                text = (
                    "dreht umso mehr, je schneller du einfährst" if r > 0 else "dreht umso mehr, je langsamer du einfährst"
                )
                tip = "Bremse gleichmäßiger lösen; das Heck wird vor allem durch die Art des Einfahrens unruhig."
            hints.append(
                DriverHint(b.corner, f"{b.phase}: {text} (r = {r:+.2f}, Tempoeinfluss des Autos bereits herausgerechnet). {tip}")
            )
            continue
        if b.verdict != "Auto":
            continue
        sev = (abs(b.understeer) - 0.08) / 0.25
        txt = f"{b.corner} {b.phase} {b.understeer * 100:+.0f} %"
        if b.phase == "Einlenken":
            add(ENTRY_OVERSTEER if b.understeer < 0 else ENTRY_UNDERSTEER, sev, txt)
        elif b.phase == "Ausgang" and b.understeer < 0:
            add(EXIT_OVERSTEER, sev, txt)

    # Mehrere betroffene Kurven verstärken das Symptom
    for key in (ENTRY_OVERSTEER, ENTRY_UNDERSTEER, EXIT_OVERSTEER):
        if key in out:
            out[key].severity = _clip(out[key].severity + 0.1 * (len(out[key].evidence) - 1))

    # --- Traktion / Blockieren
    for s in a.slip:
        if s.spin_exit is not None and s.spin_exit > 0.08:
            add(TRACTION, (s.spin_exit - 0.05) / 0.25, f"{s.corner} Ausgang {s.spin_exit * 100:.0f} % Durchdrehen")
        if s.lock_brake is not None and s.lock_brake > 0.04:
            add(LOCKUP, (s.lock_brake - 0.02) / 0.10, f"{s.corner} {s.lock_brake * 100:.0f} % Blockieren ({s.lock_wheels})")
    if TRACTION in out:
        out[TRACTION].severity = _clip(out[TRACTION].severity + 0.1 * (len(out[TRACTION].evidence) - 1))

    # --- Plattform
    p = a.platform
    if p:
        for c in p.contacts:
            if c.kind == "Aufsetzen" and c.laps >= max(2, c.of_laps // 2):
                add(BOTTOMING, c.laps / c.of_laps * 0.7, f"{c.location} ({', '.join(c.wheels)}, {c.speed_kmh:.0f} km/h) in {c.laps}/{c.of_laps} Runden")
        for t in p.travel:
            if t.usage >= 0.92:
                add(TRAVEL_LIMIT, (t.usage - 0.88) / 0.10, f"{t.setting} {t.usage * 100:.0f} % genutzt")
        if p.aero:
            rk_m = p.aero.rear_meas_mm - p.aero.front_meas_mm
            rk_c = p.aero.rear_calc_mm - p.aero.front_calc_mm
            if rk_m < rk_c - 2:
                add(RAKE_DEFICIT, (rk_c - rk_m) / 8, f"Rake {rk_m:.1f} mm statt {rk_c:.1f} mm bei {p.aero.speed_kmh:.0f} km/h")
            elif rk_m > rk_c + 2:
                add(RAKE_EXCESS, (rk_m - rk_c) / 8, f"Rake {rk_m:.1f} mm statt {rk_c:.1f} mm bei {p.aero.speed_kmh:.0f} km/h")

    symptoms = sorted(out.values(), key=lambda s: -s.severity)
    return symptoms, hints

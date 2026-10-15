"""Gesamtablauf für eine IBT-Datei: lesen -> segmentieren -> diagnostizieren."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .channels import Inventory, build_inventory
from .diagnose import (
    PhaseBalance,
    PlatformResult,
    SlipRow,
    SpeedBalance,
    SteerModel,
    StyleProfile,
    TireResult,
    analyze_balance,
    analyze_platform,
    analyze_slip,
    analyze_style,
    analyze_tires,
    balance_by_speed,
    fit_steer_model,
)
from .ibt import IbtFile
from .incar import LABELS, InCarSetting, changed_settings, in_car_settings


def _num(raw: str) -> float | None:
    import re

    m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)", raw)
    return float(m.group(1)) if m else None
from .segment import Corner, LapSet, detect_corners, split_laps
from .setup import CarSetup


@dataclass
class SessionAnalysis:
    ibt: IbtFile
    inventory: Inventory
    setup: CarSetup
    laps: LapSet
    corners: list[Corner]
    steer_model: SteerModel | None
    balance: list[PhaseBalance]
    speed_balance: SpeedBalance | None
    platform: PlatformResult | None
    tires: TireResult | None
    slip: list[SlipRow]
    style: StyleProfile | None
    incar: list[InCarSetting] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def garage_value(self, s: InCarSetting) -> str | None:
        """Garage-Wert aus dem Setup, der zu einer Verstellung im Auto passt."""
        frags = LABELS.get(s.channel, ("", ()))[1]
        if not frags:
            return None
        hits = [v for v in self.setup.find(*frags) if not v.likely_read_only]
        numeric = [v for v in hits if v.value is not None]  # "ArbAdj 1" statt "ArbSetting Connected"
        hits = numeric or hits
        return hits[0].raw if hits else None

    @property
    def path(self) -> Path:
        return self.ibt.path

    def findings(self) -> list[str]:
        """Die wichtigsten Auffälligkeiten in Klartext, nach Bedeutung sortiert."""
        out: list[str] = []
        for s in changed_settings(self.incar):
            garage = self.garage_value(s)
            if s.constant_in_valid_laps and s.effective is not None:
                if garage is not None and _num(garage) != s.effective:
                    out.append(
                        f"Im Auto verstellt: {s.label} gefahren mit {s.effective:g} (Garage-Setup: {garage}) – "
                        "das Setup in der Datei zeigt nur den Garage-Stand."
                    )
            elif not s.constant_in_valid_laps:
                out.append(
                    f"{s.label} wurde während der gewerteten Runden verstellt "
                    f"({', '.join(f'{v:g}' for v in sorted(set(s.per_lap.values())))}) – siehe Rundengruppen."
                )
        if self.speed_balance and self.speed_balance.finding:
            out.append(self.speed_balance.finding)
        p = self.platform
        if p and p.aero and p.aero.finding:
            out.append(p.aero.finding)
        if p:
            for t in p.travel:
                if t.usage >= 0.95:
                    out.append(
                        f"Federweg {t.setting} zu {t.usage * 100:.0f} % ausgenutzt "
                        f"(nur {t.margin_mm:.1f} mm Reserve) – läuft nahe am Anschlag."
                    )
            frequent = [c for c in p.contacts if c.kind == "Aufsetzen" and c.laps >= max(2, c.of_laps // 2)]
            for c in frequent[:3]:
                out.append(
                    f"Auto setzt auf: {c.location} ({', '.join(c.wheels)}, {c.speed_kmh:.0f} km/h) "
                    f"in {c.laps} von {c.of_laps} Runden."
                )
        car = [b for b in self.balance if b.verdict == "Auto"]
        for b in sorted(car, key=lambda b: -abs(b.understeer))[:4]:
            out.append(f"{b.corner} {b.phase}: konstant {b.tendency} ({b.understeer * 100:+.0f} % Lenkung) → Setup-Thema.")
        for s in self.slip:
            if s.spin_exit is not None and s.spin_exit > 0.10:
                out.append(f"{s.corner} Ausgang: Hinterräder drehen in {s.spin_exit * 100:.0f} % der Zeit durch.")
            if s.lock_brake is not None and s.lock_brake > 0.05:
                out.append(f"{s.corner} Bremsen: Rad blockiert ({s.lock_wheels}) in {s.lock_brake * 100:.0f} % der Zeit.")
        return out


def analyze_file(path: str | Path) -> SessionAnalysis:
    ibt = IbtFile.open(path)
    notes = list(ibt.warnings)
    inventory = build_inventory(ibt)
    setup = CarSetup.from_session_info(ibt.session_info)
    if not len(setup):
        notes.append("Kein CarSetup-Block in der Session-Info gefunden")

    laps = split_laps(ibt)
    if len(laps.valid) < 3:
        notes.append(
            f"Nur {len(laps.valid)} gültige Runde(n) – für belastbare Aussagen mindestens 5–10 saubere Runden fahren"
        )

    corners: list[Corner] = []
    try:
        corners = detect_corners(laps)
    except ValueError as exc:
        notes.append(str(exc))

    model = fit_steer_model(laps) if laps.valid else None
    return _diagnose(ibt, inventory, setup, laps, corners, model, notes)


def _diagnose(ibt, inventory, setup, laps, corners, model, notes) -> SessionAnalysis:
    balance: list[PhaseBalance] = []
    speed_balance = None
    if model is None:
        notes.append("Lenkmodell nicht bestimmbar (zu wenig Daten im linearen Bereich) – kein Balance-Index")
    elif laps.valid:
        speed_balance = balance_by_speed(laps, model)
        if corners:
            balance = analyze_balance(laps, corners, model, speed_balance)

    platform = analyze_platform(laps, corners, setup) if laps.valid else None
    tires = analyze_tires(laps)
    if tires and tires.pit_only:
        notes.append(
            "Nur in der Box aktualisiert (während der Fahrt konstant): " + ", ".join(sorted(tires.pit_only)[:6])
            + (" …" if len(tires.pit_only) > 6 else "")
        )

    return SessionAnalysis(
        ibt=ibt,
        inventory=inventory,
        setup=setup,
        laps=laps,
        corners=corners,
        steer_model=model,
        balance=balance,
        speed_balance=speed_balance,
        platform=platform,
        tires=tires,
        slip=analyze_slip(laps, corners),
        style=analyze_style(laps, corners),
        incar=in_car_settings(laps) if laps.valid else [],
        notes=notes,
    )


def analyze_subset(a: SessionAnalysis, lap_numbers: list[int], reason: str = "andere Einstellung") -> SessionAnalysis:
    """Dieselbe Session, aber nur mit ausgewählten Runden (z. B. eine Einstellungsgruppe eines A-B-A-Tests).

    Kurven und Lenkmodell kommen aus der ganzen Session (mehr Daten, gleiche Strecke und gleiches Auto).
    """
    import copy

    keep = set(lap_numbers)
    laps_copy = []
    for lap in a.laps.laps:
        lc = copy.copy(lap)
        lc.reasons = list(lap.reasons)
        if lc.valid and lc.number not in keep:
            lc.invalidate(reason)
        laps_copy.append(lc)
    laps = LapSet(ibt=a.ibt, laps=laps_copy, grid=a.laps.grid)
    return _diagnose(a.ibt, a.inventory, a.setup, laps, a.corners, a.steer_model, [])

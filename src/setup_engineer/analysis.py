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
    notes: list[str] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return self.ibt.path

    def findings(self) -> list[str]:
        """Die wichtigsten Auffälligkeiten in Klartext, nach Bedeutung sortiert."""
        out: list[str] = []
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
    balance: list[PhaseBalance] = []
    speed_balance = None
    if model is None:
        notes.append("Lenkmodell nicht bestimmbar (zu wenig Daten im linearen Bereich) – kein Balance-Index")
    else:
        speed_balance = balance_by_speed(laps, model)
        if corners:
            balance = analyze_balance(laps, corners, model)

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
        notes=notes,
    )

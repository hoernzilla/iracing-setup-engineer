"""Gesamtablauf für eine IBT-Datei: lesen -> segmentieren -> diagnostizieren."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .channels import Inventory, build_inventory
from .diagnose import (
    PhaseBalance,
    PlatformResult,
    SteerModel,
    StyleProfile,
    analyze_balance,
    analyze_platform,
    analyze_style,
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
    platform: PlatformResult | None
    style: StyleProfile | None
    notes: list[str] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return self.ibt.path


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
    if model is None:
        notes.append("Lenkmodell nicht bestimmbar (zu wenig Daten im linearen Bereich) – kein Balance-Index")
    elif corners:
        balance = analyze_balance(laps, corners, model)

    platform = analyze_platform(laps, corners, setup) if laps.valid else None
    style = analyze_style(laps, corners)

    return SessionAnalysis(
        ibt=ibt,
        inventory=inventory,
        setup=setup,
        laps=laps,
        corners=corners,
        steer_model=model,
        balance=balance,
        platform=platform,
        style=style,
        notes=notes,
    )

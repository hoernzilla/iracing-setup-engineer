"""Kanal-Inventar: Welche Daten liefert dieses Auto überhaupt?

Die verfügbaren Telemetriekanäle hängen vom Fahrzeug ab (GTP hat z. B.
Heave-/Hybrid-Kanäle, GT3 nicht). Die Diagnose fragt dieses Inventar ab,
statt Kanäle stillschweigend vorauszusetzen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .ibt.reader import IbtFile

CORNERS = ("LF", "RF", "LR", "RR")

# Gruppe -> Liste von Regex-Mustern
GROUPS: dict[str, list[str]] = {
    "Basis": [
        r"Speed",
        r"Throttle",
        r"Brake",
        r"Clutch",
        r"SteeringWheelAngle",
        r"Gear",
        r"RPM",
        r"Lap",
        r"LapDist",
        r"LapDistPct",
        r"LapCurrentLapTime",
        r"LapLastLapTime",
        r"SessionTime",
        r"OnPitRoad",
        r"PlayerTrackSurface",
    ],
    "Fahrdynamik": [
        r"YawRate",
        r"Yaw",
        r"Roll",
        r"Pitch",
        r"LatAccel",
        r"LongAccel",
        r"VertAccel",
        r"VelocityX",
        r"VelocityY",
        r"VelocityZ",
        r"Lat",
        r"Lon",
    ],
    "Ride Height": [r"(LF|RF|LR|RR)rideHeight", r"CF(SR)?rideHeight", r"CR(SR)?rideHeight", r"CFSRrideHeight"],
    "Federung": [r"(LF|RF|LR|RR)shockDefl", r"(LF|RF|LR|RR)shockVel"],
    "Federung 360 Hz": [r"(LF|RF|LR|RR)shockDefl_ST", r"(LF|RF|LR|RR)shockVel_ST"],
    "Heave/Third (GTP)": [r"(HF|HR|CF|CR)shock(Defl|Vel)(_ST)?", r"ROLL(F|R)shock(Defl|Vel)(_ST)?"],
    "Reifen": [
        r"(LF|RF|LR|RR)temp[CL][LMR]?",
        r"(LF|RF|LR|RR)wear[LMR]",
        r"(LF|RF|LR|RR)(cold|hot)?[Pp]ress(ure)?",
        r"(LF|RF|LR|RR)speed",
        r"(LF|RF|LR|RR)tireRPS",
    ],
    "Bremse/Elektronik": [
        r"BrakeABSactive",
        r"BrakeRaw",
        r"dcBrakeBias",
        r"dcABS",
        r"dcTractionControl\d?",
        r"dcAntiRollFront",
        r"dcAntiRollRear",
        r"dcBrakeBiasFine",
        r"dcPeakBrakeBias",
        r"dcBrakeMisc",
        r"dc\w+",
    ],
    "Hybrid (GTP)": [r"Energy\w+", r"PowerMGU_\w+", r"TorqueMGU_\w+", r"dcMGU\w*", r"MGU\w+"],
    "Umgebung": [r"TrackTemp\w*", r"AirTemp", r"AirDensity", r"AirPressure", r"WindVel", r"WindDir", r"RelativeHumidity", r"TrackWetness"],
    "Sprit": [r"FuelLevel", r"FuelLevelPct", r"FuelUsePerHour"],
}


@dataclass
class Inventory:
    groups: dict[str, list[str]]
    hi_res: list[str]
    other: list[str]
    total: int

    def has_any(self, group: str) -> bool:
        return bool(self.groups.get(group))


def build_inventory(ibt: IbtFile) -> Inventory:
    names = ibt.channel_names()
    compiled = {g: [re.compile(rf"^{p}$") for p in pats] for g, pats in GROUPS.items()}
    assigned: set[str] = set()
    groups: dict[str, list[str]] = {g: [] for g in GROUPS}
    # Spezifische Gruppen zuerst, damit dc\w+ nicht alles schluckt
    for g, pats in compiled.items():
        for n in names:
            if n in assigned:
                continue
            if any(p.match(n) for p in pats):
                groups[g].append(n)
                assigned.add(n)
    hi_res = [n for n in names if ibt.var_headers[n].count > 1]
    other = [n for n in names if n not in assigned]
    return Inventory(groups=groups, hi_res=hi_res, other=other, total=len(names))

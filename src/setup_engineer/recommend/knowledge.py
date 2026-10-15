"""Wissensbasis: welche Setup-Änderung wirkt wie auf welche Symptome.

Jeder Kandidat beschreibt EINE Änderung in EINE Richtung, ihre Wirkung auf die
Symptome (+ = verbessert, − = verschlechtert, Betrag 0..1 = Stärke) und wie der
Parameter im Setup bzw. im Auto gefunden wird.

Die Wirkungen sind Fahrdynamik-Grundlagen (Lehrbuchrichtung), keine
fahrzeugspezifischen Messwerte. Die gemessene Wirkung kommt aus der
Test-Historie (history.py) und hat Vorrang.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import symptoms as S


@dataclass(frozen=True)
class Candidate:
    key: str
    title: str
    setup_fragments: tuple[str, ...]  # alle müssen im Setup-Pfad vorkommen (Groß/Klein egal)
    direction: int  # +1 = Wert erhöhen, −1 = Wert senken
    effects: dict[str, float]
    why: str
    risks: str
    incar_channel: str | None = None  # im Auto verstellbar -> A-B-A in einer Session möglich
    exclude_fragments: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = field(default_factory=tuple)  # leer = alle Autos; sonst Teile des CarPath
    # Ersatzmuster, falls ein Auto (z. B. GT3) die Einstellung anders benennt; erst setup_fragments, dann diese
    alt_fragments: tuple[tuple[str, ...], ...] = ()


CANDIDATES: list[Candidate] = [
    # ---------------------------------------------------------- Stabilisatoren
    Candidate(
        "arb_front_soft",
        "Stabilisator vorne weicher",
        ("front", "arbadj"),
        -1,
        {S.MID_UNDERSTEER: 0.8, S.ENTRY_UNDERSTEER: 0.6, S.HS_UNDERSTEER: 0.2, S.ENTRY_OVERSTEER: -0.4, S.EXIT_OVERSTEER: -0.3},
        "Weniger Wanksteifigkeit vorne gibt der Vorderachse mehr mechanischen Grip – das Auto lenkt in langsamen und mittleren Kurven besser ein.",
        "Heck wird beim Einlenken und am Ausgang etwas lebendiger.",
        incar_channel="dcAntiRollFront",
    ),
    Candidate(
        "arb_front_stiff",
        "Stabilisator vorne härter",
        ("front", "arbadj"),
        +1,
        {S.ENTRY_OVERSTEER: 0.5, S.EXIT_OVERSTEER: 0.4, S.TRACTION: 0.2, S.MID_UNDERSTEER: -0.8, S.ENTRY_UNDERSTEER: -0.6, S.HS_UNDERSTEER: -0.2},
        "Mehr Wanksteifigkeit vorne beruhigt das Heck beim Einlenken und am Ausgang.",
        "Mehr Untersteuern in langsamen und mittleren Kurven.",
        incar_channel="dcAntiRollFront",
    ),
    Candidate(
        "arb_rear_soft",
        "Stabilisator hinten weicher",
        ("rear", "arbadj"),
        -1,
        {S.EXIT_OVERSTEER: 0.7, S.TRACTION: 0.6, S.ENTRY_OVERSTEER: 0.4, S.MID_UNDERSTEER: -0.6, S.ENTRY_UNDERSTEER: -0.3},
        "Weniger Wanksteifigkeit hinten verteilt die Last auf beide Hinterräder gleichmäßiger – mehr Traktion und ein ruhigeres Heck.",
        "Etwas mehr Untersteuern in langsamen und mittleren Kurven.",
        incar_channel="dcAntiRollRear",
    ),
    Candidate(
        "arb_rear_stiff",
        "Stabilisator hinten härter",
        ("rear", "arbadj"),
        +1,
        {S.MID_UNDERSTEER: 0.7, S.ENTRY_UNDERSTEER: 0.4, S.HS_UNDERSTEER: 0.2, S.EXIT_OVERSTEER: -0.7, S.TRACTION: -0.6, S.ENTRY_OVERSTEER: -0.4},
        "Mehr Wanksteifigkeit hinten nimmt Untersteuern aus langsamen und mittleren Kurven.",
        "Weniger Traktion, Heck am Ausgang unruhiger.",
        incar_channel="dcAntiRollRear",
    ),
    # ---------------------------------------------------------------- Aero
    Candidate(
        "wing_down",
        "Heckflügel flacher",
        ("rearwingangle",),
        -1,
        {S.HS_UNDERSTEER: 0.8, S.HS_OVERSTEER: -0.8},
        "Weniger Heckabtrieb verschiebt die Aero-Balance nach vorne – hilft gegen Untersteuern im schnellen Bereich und bringt Endgeschwindigkeit.",
        "Weniger Gesamtabtrieb; Heck in schnellen Kurven und beim Bremsen aus hohem Tempo unruhiger.",
    ),
    Candidate(
        "wing_up",
        "Heckflügel steiler",
        ("rearwingangle",),
        +1,
        {S.HS_OVERSTEER: 0.8, S.HS_UNDERSTEER: -0.8},
        "Mehr Heckabtrieb stabilisiert das Heck im schnellen Bereich.",
        "Mehr Untersteuern bei Tempo, weniger Endgeschwindigkeit.",
    ),
    Candidate(
        "rear_rh_up",
        "Ride Height hinten höher (mehr Rake)",
        ("rear", "pushrodlength"),
        +1,
        {S.HS_UNDERSTEER: 0.6, S.RAKE_DEFICIT: 0.8, S.RAKE_EXCESS: -0.8, S.HS_OVERSTEER: -0.6},
        "Mehr Rake bei Tempo verschiebt die Aero-Balance nach vorne (mehr Frontabtrieb).",
        "Heck bei Tempo leichter; zu viel Rake kann den Unterboden abreißen lassen.",
    ),
    Candidate(
        "rear_rh_down",
        "Ride Height hinten tiefer (weniger Rake)",
        ("rear", "pushrodlength"),
        -1,
        {S.HS_OVERSTEER: 0.6, S.RAKE_EXCESS: 0.8, S.RAKE_DEFICIT: -0.8, S.HS_UNDERSTEER: -0.6},
        "Weniger Rake verschiebt die Aero-Balance nach hinten und stabilisiert das Heck bei Tempo.",
        "Mehr Untersteuern bei Tempo.",
    ),
    Candidate(
        "rear_third_stiff",
        "Third Spring hinten härter",
        ("rear", "thirdspring"),
        +1,
        {S.RAKE_DEFICIT: 0.6, S.HS_UNDERSTEER: 0.4, S.TRAVEL_LIMIT: 0.3, S.TRACTION: -0.2},
        "Das Heck sackt bei Tempo weniger ein – der Rake bleibt näher am geplanten Wert, die Aero-Balance wandert weniger nach hinten.",
        "Heck über Bodenwellen und Kerbs härter, etwas weniger mechanischer Grip hinten.",
        exclude_fragments=("perch", "defl"),
    ),
    Candidate(
        "front_heave_stiff",
        "Heave Spring vorne härter",
        ("front", "heavespring"),
        +1,
        {S.BOTTOMING: 0.8, S.TRAVEL_LIMIT: 0.4, S.HS_UNDERSTEER: -0.2},
        "Die Front wird bei Tempo weniger tief gedrückt – weniger Aufsetzen.",
        "Front steht bei Tempo etwas höher (weniger Frontabtrieb), über Kerbs härter.",
        exclude_fragments=("perch", "defl"),
    ),
    # --------------------------------------------------------------- Bremse
    Candidate(
        "brake_bias_fwd",
        "Bremsbalance weiter nach vorne",
        ("brakepressurebias",),
        +1,
        {S.ENTRY_OVERSTEER: 0.6, S.LOCKUP: -0.3, S.ENTRY_UNDERSTEER: -0.3},
        "Mehr Bremskraft vorne entlastet die Hinterachse beim Anbremsen – das Heck bleibt beim Einlenken ruhiger.",
        "Vorderräder neigen eher zum Blockieren, Einlenken unter Bremse etwas träger.",
        incar_channel="dcBrakeBias",
    ),
    Candidate(
        "brake_bias_rear",
        "Bremsbalance weiter nach hinten",
        ("brakepressurebias",),
        -1,
        {S.ENTRY_UNDERSTEER: 0.6, S.ENTRY_OVERSTEER: -0.6},
        "Mehr Bremskraft hinten hilft dem Auto, unter Bremse einzudrehen.",
        "Heck beim Anbremsen unruhiger.",
        incar_channel="dcBrakeBias",
    ),
    # ----------------------------------------------------------- Differenzial
    Candidate(
        "diff_preload_up",
        "Differenzial-Vorspannung höher",
        ("diff", "preload"),
        +1,
        {S.ENTRY_OVERSTEER: 0.4, S.EXIT_OVERSTEER: 0.3, S.TRACTION: 0.3, S.MID_UNDERSTEER: -0.4, S.ENTRY_UNDERSTEER: -0.3},
        "Mehr Sperrwirkung stabilisiert das Heck beim Lastwechsel und verteilt das Antriebsmoment gleichmäßiger.",
        "Mehr Untersteuern in der Kurvenmitte.",
    ),
    Candidate(
        "diff_preload_down",
        "Differenzial-Vorspannung niedriger",
        ("diff", "preload"),
        -1,
        {S.MID_UNDERSTEER: 0.4, S.ENTRY_UNDERSTEER: 0.3, S.ENTRY_OVERSTEER: -0.4, S.EXIT_OVERSTEER: -0.3, S.TRACTION: -0.3},
        "Weniger Sperrwirkung lässt das Auto in der Kurvenmitte leichter drehen.",
        "Heck beim Lastwechsel und am Ausgang unruhiger.",
    ),
    # ------------------------------------------------------- Traktionskontrolle
    Candidate(
        "tc_up",
        "Traktionskontrolle eine Stufe stärker",
        ("tractioncontrolslip",),
        +1,
        {S.TRACTION: 0.8, S.EXIT_OVERSTEER: 0.4},
        "Die TC greift früher ein – weniger Durchdrehen am Kurvenausgang.",
        "Kann Vortrieb kosten, wenn sie zu früh regelt. Ob eine höhere Zahl mehr Eingriff bedeutet, "
        "ist je Auto verschieden – am Display/in der Garage-Beschreibung prüfen.",
        incar_channel="dcTractionControl",
    ),
]


# Ersatzmuster je Einstellung – GT3-Setups benennen manches anders als der GTP
_ALT = {
    ("front", "arbadj"): (("front", "arbblade"), ("front", "arbsetting"), ("front", "arb")),
    ("rear", "arbadj"): (("rear", "arbblade"), ("rear", "arbsetting"), ("rear", "arb")),
    ("rearwingangle",): (("wingangle",), ("wingsetting",), ("wing",)),
    ("tractioncontrolslip",): (("tractioncontrol",),),
}


def find_parameter(setup, cand: Candidate):
    """Den Setup-Wert zu einem Kandidaten finden (oder None)."""
    excl = [f.lower() for f in cand.exclude_fragments]
    patterns = (cand.setup_fragments, *cand.alt_fragments, *_ALT.get(cand.setup_fragments, ()))
    for pattern in patterns:
        frags = [f.lower() for f in pattern]
        for path, v in setup.values.items():
            p = path.lower()
            if all(f in p for f in frags) and not any(f in p for f in excl) and not v.likely_read_only:
                return v
    return None

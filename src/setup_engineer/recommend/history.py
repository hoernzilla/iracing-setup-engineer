"""Test-Historie: gemessene Wirkung von Setup-Änderungen speichern und wiederverwenden.

Jeder A/B-Vergleich kann gespeichert werden. Die Empfehlungs-Engine nutzt diese
Messungen als Beleg: Bestätigt eine Messung die erwartete Wirkung, steigt die
Konfidenz, und die Größe des Effekts wird aus der Messung abgeschätzt.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class TestRecord:
    created: str
    car: str
    track: str
    file_a: str
    file_b: str
    changes: list[dict]  # {path, before, after, delta}
    balance: dict[str, float]  # Bereich -> Veränderung Lenküberschuss (B − A), z. B. "Tempo 150–200 km/h": 0.07
    lap_delta_s: float | None
    p_value: float | None
    conditions_differ: bool
    within_session: bool = False
    notes: list[str] = field(default_factory=list)
    source: str = "test"  # "test" = nach Leitfaden gefahren, "archiv" = aus alten Dateien gefunden

    @property
    def weight(self) -> float:
        """Gewicht als Beleg: Funde aus Altdaten zählen halb."""
        return 0.5 if self.source == "archiv" else 1.0

    @property
    def quality(self) -> str:
        """Wie belastbar ist die Messung?"""
        if self.source == "archiv":
            return "Archiv, nicht geplant – halbes Gewicht"
        if self.within_session:
            return "hoch, gleiche Session"
        return "eingeschränkt, Bedingungen verschieden" if self.conditions_differ else "mittel, getrennte Runs"


class History:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.records: list[TestRecord] = []
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.records = [TestRecord(**r) for r in raw]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([asdict(r) for r in self.records], ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add(self, rec: TestRecord) -> bool:
        """Hinzufügen; gleiche Dateipaare werden ersetzt statt doppelt gespeichert."""
        self.records = [r for r in self.records if not (r.file_a == rec.file_a and r.file_b == rec.file_b)]
        self.records.append(rec)
        return True

    def for_car(self, car: str) -> list[TestRecord]:
        return [r for r in self.records if r.car == car]


def record_from_ab(r, a, b, within_session: bool = False) -> TestRecord:
    """Aus einem ABResult (compare.ab_compare) einen Historien-Eintrag machen."""
    return TestRecord(
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        car=a.ibt.car_name,
        track=a.ibt.track_name,
        file_a=a.ibt.path.name,
        file_b=b.ibt.path.name if b is not None else a.ibt.path.name,
        changes=[{"path": c.path, "before": c.before, "after": c.after, "delta": c.delta} for c in r.setup_changes],
        balance={x.zone: round(x.b - x.a, 4) for x in r.balance},
        lap_delta_s=None if r.effect_s != r.effect_s else round(r.effect_s, 4),
        p_value=None if r.p_value != r.p_value else round(r.p_value, 4),
        conditions_differ=any(c.warn for c in r.conditions),
        within_session=within_session,
        notes=list(r.notes),
    )

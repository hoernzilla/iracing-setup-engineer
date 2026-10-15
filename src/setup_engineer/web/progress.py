"""Fortschritt des Gesamtprojekts: Phase, Tests je Auto, getestete Einstellungen, Aktivität.

Alles aus der Datenbank (gewertete, nicht aussortierte Uploads) und dem gemeinsamen
Test-Wissen (community-history.json). Keine personenbezogenen Daten.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..recommend.history import History

# Themen, die die Empfehlungen kennen. Ein Test zählt für ein Thema, wenn der Name der
# geänderten Einstellung alle Teile eines Musters enthält (Setup-Pfad oder „Im Auto: …“).
TOPICS: list[tuple[str, list[tuple[str, ...]]]] = [
    ("Stabilisator vorne", [("front", "arb"), ("stabilisator vorne",)]),
    ("Stabilisator hinten", [("rear", "arb"), ("stabilisator hinten",)]),
    ("Heckflügel", [("wing",)]),
    ("Ride Height hinten", [("rear", "pushrod"), ("rear", "rideheight")]),
    ("Third Spring hinten", [("rear", "third")]),
    ("Heave Spring vorne", [("front", "heave")]),
    ("Bremsbalance", [("brakepressurebias",), ("bremsbalance",)]),
    ("Differenzial", [("diff",)]),
    ("Traktionskontrolle", [("tractioncontrol",), ("traktionskontrolle",)]),
]


def topic_of(path: str) -> str:
    p = path.lower()
    for name, patterns in TOPICS:
        if any(all(part in p for part in pat) for pat in patterns):
            return name
    return "Sonstiges"


def _stage(tests: int, goal1: int, goal2: int) -> dict:
    if tests >= goal2:
        return {"n": 3, "label": "Stufe 2 erreicht", "next": None, "missing": 0}
    if tests >= goal1:
        return {"n": 2, "label": "Stufe 1 erreicht", "next": goal2, "missing": goal2 - tests}
    return {"n": 1, "label": "auf dem Weg zu Stufe 1", "next": goal1, "missing": goal1 - tests}


def build(db, history_path: Path, goal1: int, goal2: int) -> dict:
    rows = db.all_uploads(status="fertig", excluded="nein", limit=1_000_000)
    rows = [r for r in rows if not r.get("banned_at")]
    hist = History(history_path)

    # ---------------------------------------------------------------- je Auto
    cars: dict[str, dict] = {}
    for r in rows:
        if not r["car"]:
            continue
        c = cars.setdefault(
            r["car"],
            {"car": r["car"], "drivers": set(), "tracks": set(), "sessions": 0, "laps": 0, "tests": set(),
             "aba": set(), "garage": set(), "topics": {}},
        )
        c["drivers"].add(r["user_id"])
        if r["track"]:
            c["tracks"].add(r["track"])
        c["sessions"] += 1
        c["laps"] += r["laps_valid"] or 0
        if r["ab_summary"]:
            key = r["pair_id"] or r["id"]
            c["tests"].add(key)
            (c["garage"] if r["pair_id"] else c["aba"]).add(key)

    for rec in hist.records:
        c = cars.get(rec.car)
        if c is None:
            continue
        for ch in rec.changes or [{"path": "keine Änderung erkannt"}]:
            t = topic_of(ch["path"])
            c["topics"][t] = c["topics"].get(t, 0) + 1

    car_list = []
    for c in cars.values():
        n = len(c["tests"])
        car_list.append(
            {
                "car": c["car"],
                "drivers": len(c["drivers"]),
                "tracks": sorted(c["tracks"]),
                "sessions": c["sessions"],
                "laps": c["laps"],
                "tests": n,
                "aba": len(c["aba"]),
                "garage": len(c["garage"]),
                "stage": _stage(n, goal1, goal2),
                "pct1": min(n / goal1 * 100, 100),
                "pct2": min(n / goal2 * 100, 100),
                "topics": [(name, c["topics"].get(name, 0)) for name, _ in TOPICS]
                + ([("Sonstiges", c["topics"]["Sonstiges"])] if c["topics"].get("Sonstiges") else []),
                "open_topics": [name for name, _ in TOPICS if not c["topics"].get(name)],
            }
        )
    car_list.sort(key=lambda x: (-x["tests"], -x["laps"]))

    # ------------------------------------------------------------ Gesamtphase
    best = max((c["tests"] for c in car_list), default=0)
    phases = [
        ("Werkzeug", "Auswertung, A/B-Vergleich und Empfehlungen laufen – getestet mit dem Porsche 963.", True),
        ("Stufe 1: Richtungen", f"{goal1} Tests je Auto. Dann ist abgesichert, in welche Richtung eine Änderung bei diesem Auto wirkt.", best >= goal1),
        ("Stufe 2: Stärke", f"{goal2} Tests je Auto. Dann wissen wir auch, wie viel eine Änderung bringt.", best >= goal2),
        ("Lernende Auswertung", "Die Empfehlungen rechnen pro Auto mit den gemessenen Wirkungen statt mit Lehrbuchwerten.", False),
        ("GT3", "Bewusst zurückgestellt – kommt dazu, wenn der GTP steht.", False),
    ]
    current = next((i for i, p in enumerate(phases) if not p[2]), len(phases) - 1)
    phase_list = [
        {"n": i + 1, "name": name, "text": text, "state": "fertig" if done else ("aktiv" if i == current else "später")}
        for i, (name, text, done) in enumerate(phases)
    ]

    # ------------------------------------------------------------- Aktivität
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    weeks = [{"start": monday - timedelta(weeks=w), "uploads": 0, "tests": set()} for w in range(7, -1, -1)]
    for r in rows:
        try:
            d = datetime.fromisoformat(r["uploaded_at"]).date()
        except (TypeError, ValueError):
            continue
        for w in reversed(weeks):
            if d >= w["start"]:
                w["uploads"] += 1
                if r["ab_summary"]:
                    w["tests"].add(r["pair_id"] or r["id"])
                break
    peak = max((w["uploads"] for w in weeks), default=0) or 1
    week_list = [
        {"label": w["start"].strftime("%d.%m."), "uploads": w["uploads"], "tests": len(w["tests"]), "pct": w["uploads"] / peak * 100}
        for w in weeks
    ]

    hours = sum((r["laps_total"] or 0) * (r["best_lap_s"] or 0) for r in rows) / 3600
    totals = {
        "drivers": len({r["user_id"] for r in rows}),
        "sessions": len(rows),
        "laps": sum(r["laps_valid"] or 0 for r in rows),
        "tests": sum(c["tests"] for c in car_list),
        "hours": hours,
        "cars": len(car_list),
        "tracks": len({r["track"] for r in rows if r["track"]}),
    }
    return {"cars": car_list, "phases": phase_list, "weeks": week_list, "totals": totals, "goal1": goal1, "goal2": goal2}

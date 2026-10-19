"""Trophäen, Punkte und Bestenliste.

Alles wird aus dem Datenbestand berechnet (gewertete, nicht aussortierte Uploads gesperrter
Teilnehmer ausgenommen) und dauerhaft gespeichert: Einmal verdient bleibt verdient – nur ein
Admin kann eine Trophäe aberkennen. Sichtbar ist eine Trophäe nur, wenn jemand sie besitzt;
den vollständigen Katalog zeigt das Portal nirgends.

Punkte: 10 je komplettem Test, 5 je Test aus Altdaten, dazu die Punkte der Trophäen
(bei Stufen zählen alle erreichten Stufen).
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..classes import car_class
from .progress import TOPICS, topic_of

log = logging.getLogger("portal.trophies")

TIER_KEYS = ["bronze", "silber", "gold", "lila"]
TIER_NAMES = ["Bronze", "Silber", "Gold", "Amethyst"]
TIER_PTS = [10, 25, 50, 100]
TEST_PTS, ARCHIVE_TEST_PTS = 10, 5
CLASS_SIZE = {"GTP": 5, "GT3": 11}  # so viele Autos hat die Klasse – erst dann gibt es Krone und Gürtel
STAGE1, STAGE2 = 30, 70
SINGULAR = {"Tests": "Test", "Garagen-Tests": "Garagen-Test", "Runden": "Runde", "Wochen": "Woche", "Autos": "Auto",
            "Strecken": "Strecke", "Setup-Bereiche": "Setup-Bereich", "Altdateien": "Altdatei", "Dateien": "Datei"}
LICENSES = [(0, "R"), (100, "D"), (250, "C"), (500, "B"), (900, "A"), (1400, "Pro")]

# ------------------------------------------------------------------ Katalog
# kind: stufe (Stufen), team, einmalig, auto, geheim, panne
CATALOG: dict[str, dict] = {
    # Team
    "schale": dict(kind="team", name="Meisterschale", draw="meisterschale", tiered=True, steps=[250, 500, 1000, 2000],
                   unit="Dateien", pts=[20, 40, 60, 100], desc="Dateien der ganzen Community."),
    "runden": dict(kind="team", name="Rundenmaschine", draw="kolben", tiered=True, steps=[1000, 2500, 5000, 10000],
                   unit="Runden", pts=[20, 40, 60, 100], desc="Gewertete Runden der ganzen Community."),
    # Stufen
    "test": dict(kind="stufe", name="Testfahrer", draw="testfahrer", tiered=True, steps=[1, 10, 25, 50], unit="Tests",
                 desc="Komplette A-B-A-Tests."),
    "box": dict(kind="stufe", name="Boxencrew", draw="boxencrew", tiered=True, steps=[1, 5, 15, 30], unit="Garagen-Tests",
                desc="Komplette Garagen-Tests mit drei Runs."),
    "km": dict(kind="stufe", name="Kilometerfresser", draw="kilometer", tiered=True, steps=[50, 150, 400, 1000], unit="Runden",
               desc="Gewertete Runden."),
    "dauer": dict(kind="stufe", name="Dauerbrenner", draw="dauerbrenner", tiered=True, steps=[2, 4, 8, 12], unit="Wochen",
                  desc="Aktive Wochen am Stück."),
    "garage": dict(kind="stufe", name="Garagenvielfalt", draw="garage", tiered=True, steps=[2, 4, 8, 16], unit="Autos",
                   desc="Autos mit einem kompletten Test."),
    "strecke": dict(kind="stufe", name="Streckenkenner", draw="strecke", tiered=True, steps=[3, 6, 10, 15], unit="Strecken",
                    desc="Verschiedene Strecken."),
    "ing": dict(kind="stufe", name="Ingenieur", draw="ingenieur", tiered=True, steps=[2, 4, 6, len(TOPICS)], unit="Setup-Bereiche",
                desc="Getestete Setup-Bereiche."),
    "archiv": dict(kind="stufe", name="Archivar", draw="archivar", tiered=True, steps=[10, 25, 75, 150], unit="Altdateien",
                   desc="Verwertbare Altdateien."),
    "uhr": dict(kind="stufe", name="Uhrwerk", draw="uhrwerk", tiered=True, steps=[1, 5, 10, 20], unit="Tests",
                desc="Tests mit sehr gleichmäßigen Rundenzeiten."),
    # Einmalig
    "gtp": dict(kind="einmalig", name="GTP-Komplett", draw="gtp", mat="kristall", pts=150, desc="In allen fünf GTP ein kompletter Test."),
    "gt3": dict(kind="einmalig", name="GT3-Komplett", draw="gt3", mat="gold", pts=250, desc="In allen elf GT3 ein kompletter Garagen-Test."),
    "allround": dict(kind="einmalig", name="Allrounder", draw="allrounder", mat="gold", pts=40, desc="Ein In-Car- und ein Garagen-Test."),
    "pionier": dict(kind="einmalig", name="Pionier", draw="pionier", mat="gold", pts=75, desc="Der allererste komplette Test in einem Auto."),
    "stein": dict(kind="einmalig", name="Grundsteinleger", draw="grundstein", mat="bronze", pts=30, desc="Einer der ersten fünf kompletten Tests in einem Auto."),
    "karte": dict(kind="einmalig", name="Kartograf", draw="kartograf", mat="gold", pts=60, desc="Der Test, mit dem ein Auto Stufe 2 erreicht hat."),
    # Geheim
    "haut": dict(kind="geheim", name="Ehrliche Haut", draw="waage", mat="lila", pts=60, desc="Ein sauberer Test, der zeigt: Diese Änderung bringt nichts."),
    "nacht": dict(kind="geheim", name="Nachtschicht", draw="nachtschicht", mat="nacht", pts=50, desc="Ein kompletter Test zwischen 0 und 5 Uhr."),
    "frueh": dict(kind="geheim", name="Frühaufsteher", draw="fruehaufsteher", mat="gold", pts=50, desc="Ein kompletter Test zwischen 5 und 7 Uhr."),
    "come": dict(kind="geheim", name="Comeback", draw="comeback", mat="lila", pts=40, desc="Nach über 60 Tagen Pause wieder ein Test."),
    "doppel": dict(kind="geheim", name="Doppelschicht", draw="lenkrad", mat="chrom", pts=75, desc="Zwei komplette Tests an einem Tag in zwei Autos."),
    "wochenende": dict(kind="geheim", name="Wochenendkrieger", draw="wochenende", mat="chrom", pts=50, desc="Komplette Tests am Samstag und am Sonntag desselben Wochenendes."),
    "metronom": dict(kind="geheim", name="Metronom", draw="metronom", mat="chrom", pts=120, desc="Ein Test, in dem die Rundenzeiten um weniger als sechs Hundertstel streuen."),
    "spiegel": dict(kind="geheim", name="Bauchgefühl", draw="spiegel", mat="chrom", pts=60, desc="Gefühl und Messung sagen das Gegenteil – und die Messung hat recht."),
    "treffer": dict(kind="geheim", name="Volltreffer", draw="volltreffer", mat="gold", pts=80, desc="Ein Test mit glasklarem Ergebnis, statistisch eindeutig."),
    "hoelle": dict(kind="geheim", name="Grüne Hölle", draw="gruenehoelle", mat="smaragd", pts=200, desc="Ein kompletter A-B-A-Test auf der Nordschleife. Respekt."),
    "zeit": dict(kind="geheim", name="Zeitreisender", draw="zeitreisender", mat="gold", pts=40, desc="Eine verwertbare Altdatei, die älter als zwei Jahre ist."),
    "klee": dict(kind="geheim", name="Glückszahl", draw="kleeblatt", mat="smaragd", pts=100, desc="Die 1.000. Datei der Community kam von dir."),
    "sync": dict(kind="geheim", name="Synchron", draw="synchron", mat="chrom", pts=50, desc="Zwei Fahrer testen am selben Tag dieselbe Änderung am selben Auto."),
    "kanister": dict(kind="geheim", name="Langstrecke", draw="kanister", mat="rot", pts=60, desc="50 gewertete Runden in einer einzigen Session."),
    # Pannen
    "dejavu": dict(kind="panne", name="Déjà-vu", draw="dejavu", mat="blech", pts=5, desc="Dieselbe Datei zweimal hochgeladen. Gezählt haben wir sie trotzdem nur einmal."),
    "kaffee": dict(kind="panne", name="Ungeduld", draw="kaffee", mat="blech", pts=5, desc="Zehnmal neu geladen, während die Auswertung lief. Sie dauert Sekunden – versprochen."),
    "finger": dict(kind="panne", name="Nur ganz kurz", draw="fingerabdruck", mat="chrom", pts=10, desc="Test ungültig, weil zwischendurch noch etwas anderes verstellt wurde."),
    "verfall": dict(kind="panne", name="Abgelaufen", draw="verfall", mat="blech", pts=5, desc="Zweimal ist ein Test verfallen, weil das zweite A nie kam."),
    "kies": dict(kind="panne", name="Kiesbett-Abo", draw="pylone", mat="blech", pts=5, desc="Fünf Runden neben der Strecke in einer einzigen Session."),
}


def _plate(car: str) -> str:
    return car.upper()[:18]


def info(tid: str) -> dict | None:
    """Katalogeintrag, auch für die Trophäen je Auto (s1:/s2:/champ:<Auto>) und je Klasse (krone:/guertel:<Klasse>)."""
    if tid in CATALOG:
        return {**CATALOG[tid], "id": tid}
    kind, _, arg = tid.partition(":")
    if kind == "s1":
        return dict(id=tid, kind="team", name=f"Stufe 1: {arg}", draw="stufe1", mat="kristall", pts=50, plate=_plate(arg),
                    desc=f"{STAGE1} komplette Tests im {arg} – die Richtung jeder Wirkung ist abgesichert.")
    if kind == "s2":
        return dict(id=tid, kind="team", name=f"Stufe 2: {arg}", draw="stufe2", mat="kristall", pts=100, plate=_plate(arg),
                    desc=f"{STAGE2} komplette Tests im {arg} – jetzt wissen wir auch, wie stark.")
    if kind == "champ":
        accents = ["#ef5d55", "#5b8cff", "#e9edf1", "#ff8a3d", "#3dbb84", "#b18cf6", "#f3c33b", "#8fd3ff"]
        return dict(id=tid, kind="auto", name=f"Champion {arg}", draw="champion", mat="gold", pts=150, plate=_plate(arg),
                    cls=car_class(arg) or "GT3", accent=accents[sum(map(ord, arg)) % len(accents)],
                    desc=f"Die meisten kompletten Tests im {arg}, als das Auto Stufe 2 erreicht hat.")
    if kind == "krone":
        return dict(id=tid, kind="team", name="Prototypen-Krone" if arg == "GTP" else "GT3-Krone", draw="krone", mat="gold",
                    pts=150, cls=arg, desc=f"Alle {CLASS_SIZE.get(arg, '?')} {arg} haben Stufe 1 erreicht.")
    if kind == "guertel":
        return dict(id=tid, kind="auto", name=f"{arg}-Champion", draw="guertel", mat="gold", pts=300, cls=arg,
                    desc=f"Die meisten kompletten Tests in allen {arg}, als jedes {arg}-Auto Stufe 2 erreicht hatte.")
    return None


def points(tid: str, tier: int | None) -> int:
    """Punkte einer Trophäe; bei Stufen alle erreichten Stufen zusammen."""
    i = info(tid)
    if not i:
        return 0
    if i.get("tiered"):
        pts = i.get("pts") or TIER_PTS
        return sum(pts[: (tier or 0) + 1])
    return int(i["pts"])


def tier_points(tid: str, tier: int | None) -> int:
    """Punkte genau dieser Stufe (für das Pop-up)."""
    i = info(tid)
    if not i:
        return 0
    if i.get("tiered"):
        return (i.get("pts") or TIER_PTS)[tier or 0]
    return int(i["pts"])


def license_of(total: int) -> str:
    return [name for minimum, name in LICENSES if total >= minimum][-1]


def display(tid: str, tier: int | None) -> dict:
    """Alles, was die Zeichnung im Browser braucht."""
    i = info(tid) or {"name": tid, "draw": "testfahrer", "mat": "bronze", "kind": "stufe", "desc": ""}
    tiered = bool(i.get("tiered"))
    t = tier or 0
    desc = i.get("desc", "")
    if tiered:
        step = i["steps"][t]
        unit = SINGULAR.get(i["unit"], i["unit"]) if step == 1 else i["unit"]
        desc = f"{desc} {TIER_NAMES[t]}: {step:,} {unit}.".replace(",", ".")
    return {
        "id": tid, "name": i["name"], "draw": i["draw"], "mat": TIER_KEYS[t] if tiered else i.get("mat", "gold"),
        "tiered": tiered, "tier": TIER_NAMES[t] if tiered else None, "kind": i["kind"], "desc": desc,
        "pts": tier_points(tid, tier), "plate": i.get("plate"), "cls": i.get("cls"), "accent": i.get("accent"),
    }


# ------------------------------------------------------------------ Berechnung
_lock = threading.Lock()


def _zone(name: str) -> tzinfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _tier(value: float, steps: list) -> int | None:
    reached = [i for i, s in enumerate(steps) if value >= s]
    return reached[-1] if reached else None


def _summary(row: dict) -> dict:
    try:
        return json.loads(row.get("ab_summary") or "{}")
    except ValueError:
        return {}


def compute(db, tz_name: str = "Europe/Berlin") -> dict:
    """Wer müsste welche Trophäe haben? Liefert {"awards": {uid: {tid: (tier, when)}}, "metrics": {uid: {...}}}."""
    tz = _zone(tz_name)
    local = lambda d: d.astimezone(tz)  # noqa: E731
    rows_all = db.all_uploads(limit=10_000_000)
    users = {u["discord_id"]: u for u in db.users_with_stats()}
    ok = lambda r: not r.get("excluded_at") and not (users.get(r["user_id"]) or {}).get("banned_at")  # noqa: E731
    done = [r for r in rows_all if r["status"] == "fertig" and ok(r)]

    awards: dict[str, dict[str, tuple[int | None, str]]] = defaultdict(dict)
    metrics: dict[str, dict] = defaultdict(lambda: defaultdict(float))

    def give(uid: str, tid: str, tier: int | None = None, when: str | None = None) -> None:
        cur = awards[uid].get(tid)
        if cur is None or (tier or 0) > (cur[0] or 0):
            awards[uid][tid] = (tier, when or "")

    # ---- Tests bündeln (Garage: drei Dateien = ein Test)
    tests: dict[str, dict] = {}
    for r in done:
        if not r.get("ab_summary"):
            continue
        key = r.get("pair_id") or r["id"]
        t = tests.setdefault(key, dict(key=key, user=r["user_id"], rows=[], car=r.get("car"), track=r.get("track"),
                                       kind="archiv" if r["test_type"] == "archiv" else ("garage" if r.get("pair_id") else "incar")))
        t["rows"].append(r)
    for t in tests.values():
        starts = [d for d in (_dt(r.get("session_start")) for r in t["rows"]) if d]
        ends = [d for d in (_dt(r.get("done_at") or r["uploaded_at"]) for r in t["rows"]) if d]
        t["start"] = min(starts) if starts else None
        t["done"] = max(ends) if ends else datetime.now(timezone.utc)
        t["sum"] = _summary(t["rows"][0])
        t["feeling"] = " ".join((r.get("feeling") or "") for r in t["rows"]).lower()
    ordered = sorted(tests.values(), key=lambda t: t["done"])
    planned = [t for t in ordered if t["kind"] != "archiv"]

    # ---- Kennzahlen je Fahrer
    weeks: dict[str, set] = defaultdict(set)
    tracks: dict[str, set] = defaultdict(set)
    for r in done:
        m = metrics[r["user_id"]]
        m["laps"] += r.get("laps_valid") or 0
        if r.get("track"):
            tracks[r["user_id"]].add(r["track"])
        d = _dt(r.get("session_start")) or _dt(r["uploaded_at"])
        if d:
            y, w, _ = local(d).isocalendar()
            weeks[r["user_id"]].add((y, w))
        if r["test_type"] == "archiv":
            m["archive_files"] += 1
            up = _dt(r["uploaded_at"])
            if d and up and (up - d).days > 730:
                give(r["user_id"], "zeit", when=r["uploaded_at"])
        if (r.get("laps_valid") or 0) >= 50:
            give(r["user_id"], "kanister", when=r.get("done_at"))
        if (r.get("offtrack_laps") or 0) >= 5:
            give(r["user_id"], "kies", when=r.get("done_at"))
    for uid, ws in weeks.items():
        best = run = 0
        prev = None
        for y, w in sorted(ws):
            monday = datetime.fromisocalendar(y, w, 1)
            run = run + 1 if prev is not None and (monday - prev).days == 7 else 1
            best, prev = max(best, run), monday
        metrics[uid]["streak"] = best
    for uid, ts in tracks.items():
        metrics[uid]["tracks"] = len(ts)

    cars_tested: dict[str, set] = defaultdict(set)
    garage_gt3: dict[str, set] = defaultdict(set)
    topics: dict[str, set] = defaultdict(set)
    days: dict[str, dict] = defaultdict(lambda: defaultdict(set))
    for t in ordered:
        uid, m, s = t["user"], metrics[t["user"]], t["sum"]
        if t["kind"] == "archiv":
            m["archive_tests"] += 1
            continue
        m["tests"] += 1
        m["garage_tests" if t["kind"] == "garage" else "incar_tests"] += 1
        if t["car"]:
            cars_tested[uid].add(t["car"])
            if t["kind"] == "garage" and car_class(t["car"]) == "GT3":
                garage_gt3[uid].add(t["car"])
        for part in (s.get("changes") or "").split(";"):
            if part.strip() and "keine Änderung" not in part:
                tp = topic_of(part)
                if tp != "Sonstiges":
                    topics[uid].add(tp)
        when = t["done"].isoformat(timespec="seconds")
        sd, p, ci, eff = s.get("lap_sd_s"), s.get("p_value"), s.get("ci95_s"), s.get("effect_s")
        if sd is not None and sd <= 0.20:
            m["steady"] += 1
        if sd is not None and sd <= 0.06:
            give(uid, "metronom", when=when)
        if p is not None and p < 0.001:
            give(uid, "treffer", when=when)
        if s.get("verdict") == "nicht entscheidbar" and ci and eff is not None and abs(eff) <= 0.1 and ci[1] - ci[0] <= 0.3:
            give(uid, "haut", when=when)
        if p is not None and p < 0.05 and eff is not None:
            felt_better = "besser" in t["feeling"] and "nicht besser" not in t["feeling"]
            felt_worse = "schlechter" in t["feeling"]
            if (felt_better and eff > 0) or (felt_worse and eff < 0):
                give(uid, "spiegel", when=when)
        if t["track"] and ("nordschleife" in t["track"].lower() or "combined" in t["track"].lower()):
            give(uid, "hoelle", when=when)
        if t["start"]:
            ld = local(t["start"])
            if ld.hour < 5:
                give(uid, "nacht", when=when)
            elif ld.hour < 7:
                give(uid, "frueh", when=when)
            days[uid][ld.date()].add(t["car"])
        # Comeback: vorher über 60 Tage nichts hochgeladen
        mine = sorted(d for d in (_dt(r["uploaded_at"]) for r in done if r["user_id"] == uid) if d)
        first = min((_dt(r["uploaded_at"]) for r in t["rows"]), default=None)
        before = [d for d in mine if first and d < first - timedelta(minutes=5)]
        if before and first and (first - before[-1]).days > 60:
            give(uid, "come", when=when)
    for uid, per_day in days.items():
        for day, cars in per_day.items():
            if len(cars) >= 2:
                give(uid, "doppel")
            if day.weekday() == 5 and (day + timedelta(days=1)) in per_day:
                give(uid, "wochenende")
    # Synchron: zwei Fahrer, gleicher Tag, gleiches Auto, gleiche Änderung
    seen: dict[tuple, set] = defaultdict(set)
    for t in planned:
        ch = (t["sum"].get("changes") or "")
        if t["start"] and t["car"] and ch and "keine Änderung" not in ch:
            seen[(local(t["start"]).date(), t["car"], ch)].add(t["user"])
    for users_same in seen.values():
        if len(users_same) >= 2:
            for uid in users_same:
                give(uid, "sync")

    for uid, m in metrics.items():
        m["cars"] = len(cars_tested[uid])
        m["topics"] = len(topics[uid])
        for tid, value in (("test", m["tests"]), ("box", m["garage_tests"]), ("km", m["laps"]), ("dauer", m["streak"]),
                           ("garage", m["cars"]), ("strecke", m["tracks"]), ("ing", m["topics"]),
                           ("archiv", m["archive_files"]), ("uhr", m["steady"])):
            t = _tier(value, CATALOG[tid]["steps"])
            if t is not None:
                give(uid, tid, t)
        if m["incar_tests"] and m["garage_tests"]:
            give(uid, "allround")
        if sum(1 for c in cars_tested[uid] if car_class(c) == "GTP") >= CLASS_SIZE["GTP"]:
            give(uid, "gtp")
        if len(garage_gt3[uid]) >= CLASS_SIZE["GT3"]:
            give(uid, "gt3")

    # ---- Autos: Pionier, Grundstein, Stufen, Kartograf, Champion
    by_car: dict[str, list] = defaultdict(list)
    for t in ordered:
        if t["car"]:
            by_car[t["car"]].append(t)
    stage_time: dict[tuple[str, int], datetime] = {}
    for car, ts in by_car.items():
        firsts = [t for t in ts if t["kind"] != "archiv"]
        if firsts:
            give(firsts[0]["user"], "pionier", when=firsts[0]["done"].isoformat(timespec="seconds"))
        for t in firsts[:5]:
            give(t["user"], "stein")
        score = 0.0
        counts: dict[str, float] = defaultdict(float)
        reached_at: dict[str, datetime] = {}
        for t in ts:
            w = 0.5 if t["kind"] == "archiv" else 1.0
            score += w
            counts[t["user"]] += w
            reached_at[t["user"]] = t["done"]
            for level, goal in ((1, STAGE1), (2, STAGE2)):
                if score >= goal and (car, level) not in stage_time:
                    stage_time[(car, level)] = t["done"]
                    when = t["done"].isoformat(timespec="seconds")
                    for uid in counts:
                        give(uid, f"s{level}:{car}", when=when)
                    if level == 2:
                        give(t["user"], "karte", when=when)
                        champ = max(counts, key=lambda u: (counts[u], -reached_at[u].timestamp()))
                        give(champ, f"champ:{car}", when=when)

    # ---- Klassen: Krone (alle Stufe 1) und Gürtel (alle Stufe 2)
    for cls, size in CLASS_SIZE.items():
        for level, prefix in ((1, "krone"), (2, "guertel")):
            times = sorted(v for (car, lv), v in stage_time.items() if lv == level and car_class(car) == cls)
            if len(times) < size:
                continue
            moment = times[size - 1]
            cls_tests = [t for t in ordered if t["car"] and car_class(t["car"]) == cls and t["done"] <= moment]
            when = moment.isoformat(timespec="seconds")
            if prefix == "krone":
                for uid in {t["user"] for t in cls_tests}:
                    give(uid, f"krone:{cls}", when=when)
            else:
                cnt: dict[str, float] = defaultdict(float)
                last: dict[str, datetime] = {}
                for t in cls_tests:
                    cnt[t["user"]] += 0.5 if t["kind"] == "archiv" else 1.0
                    last[t["user"]] = t["done"]
                if cnt:
                    give(max(cnt, key=lambda u: (cnt[u], -last[u].timestamp())), f"guertel:{cls}", when=when)

    # ---- Team: Dateien und Runden der ganzen Community
    total_files = total_laps = 0
    contributors: set = set()
    hit_files: set = set()
    hit_laps: set = set()
    for r in sorted(done, key=lambda r: r["uploaded_at"]):
        total_files += 1
        total_laps += r.get("laps_valid") or 0
        contributors.add(r["user_id"])
        if total_files == 1000:
            give(r["user_id"], "klee", when=r["uploaded_at"])
        for tid, value, hit in (("schale", total_files, hit_files), ("runden", total_laps, hit_laps)):
            t = _tier(value, CATALOG[tid]["steps"])
            if t is not None and t not in hit:
                hit.add(t)
                for uid in contributors:
                    give(uid, tid, t, when=r["uploaded_at"])

    # ---- Pannen
    for ev in db.events():
        if ev["kind"] == "dup":
            give(ev["user_id"], "dejavu", when=ev["at"])
    for uid, stamps in _grouped(db.events(kind="reload_wait")).items():
        stamps.sort()
        for i in range(len(stamps) - 9):
            if stamps[i + 9] - stamps[i] <= timedelta(minutes=15):
                give(uid, "kaffee")
                break
    expired: dict[str, set] = defaultdict(set)
    for r in rows_all:
        note = r.get("test_note") or ""
        if "mehr als einmal umgestellt" in note:
            give(r["user_id"], "finger", when=r.get("done_at"))
        if r["test_type"] in ("aba", "garage") and r.get("raw_deleted_at") and not r.get("ab_summary") and r["status"] == "fertig":
            expired[r["user_id"]].add(r.get("pair_id") or r["id"])
    for uid, keys in expired.items():
        if len(keys) >= 2:
            give(uid, "verfall")

    return {"awards": awards, "metrics": metrics}


def _grouped(events: list[dict]) -> dict[str, list[datetime]]:
    out: dict[str, list[datetime]] = defaultdict(list)
    for e in events:
        d = _dt(e["at"])
        if d:
            out[e["user_id"]].append(d)
    return out


def evaluate(db, tz_name: str = "Europe/Berlin") -> int:
    """Neu verdiente Trophäen speichern (nie automatisch entfernen). Gibt die Zahl neuer Einträge zurück."""
    with _lock:
        try:
            state = compute(db, tz_name)
        except Exception:  # noqa: BLE001 – Trophäen dürfen nie die Auswertung stören
            log.exception("Trophäen-Berechnung fehlgeschlagen")
            return 0
        new = 0
        have = {(t["user_id"], t["trophy_id"]): t for t in db.trophies(include_revoked=True)}
        for uid, items in state["awards"].items():
            for tid, (tier, when) in items.items():
                cur = have.get((uid, tid))
                if cur is None:
                    db.award_trophy(uid, tid, tier)
                    new += 1
                elif cur["revoked_at"] is None and tier is not None and (cur["tier"] or 0) < tier:
                    db.award_trophy(uid, tid, tier)  # nächste Stufe -> Pop-up erneut
                    new += 1
        return new


# ------------------------------------------------------------------ Ansichten
def user_totals(db, metrics: dict) -> dict[str, dict]:
    """Punkte, Lizenz und Trophäen je Teilnehmer (für Pokalschrank und Bestenliste)."""
    out: dict[str, dict] = {}
    by_user: dict[str, list] = defaultdict(list)
    for t in db.trophies():
        by_user[t["user_id"]].append(t)
    for u in db.users_with_stats():
        if u.get("banned_at"):
            continue
        uid = u["discord_id"]
        m = metrics.get(uid, {})
        own = by_user.get(uid, [])
        tpts = sum(points(t["trophy_id"], t["tier"]) for t in own)
        total = int(m.get("tests", 0) * TEST_PTS + m.get("archive_tests", 0) * ARCHIVE_TEST_PTS + tpts)
        out[uid] = dict(uid=uid, name=u.get("display_name") or u["username"], tests=int(m.get("tests", 0)),
                        trophies=own, trophy_pts=tpts, total=total, license=license_of(total))
    return out


def ranking(totals: dict[str, dict]) -> list[dict]:
    rows = [t for t in totals.values() if t["total"] > 0]
    return sorted(rows, key=lambda t: (-t["total"], -t["tests"], t["name"].lower()))


def progress_of(tid: str, tier: int | None, m: dict) -> dict | None:
    """Wie weit ist es bis zur nächsten Stufe? Nur für eigene Trophäen mit Stufen (nicht Team)."""
    i = CATALOG.get(tid)
    if not i or not i.get("tiered") or i["kind"] == "team" or tier is None or tier >= 3:
        return None
    key = {"test": "tests", "box": "garage_tests", "km": "laps", "dauer": "streak", "garage": "cars", "strecke": "tracks",
           "ing": "topics", "archiv": "archive_files", "uhr": "steady"}[tid]
    have, nxt = int(m.get(key, 0)), i["steps"][tier + 1]
    return {"have": have, "next": nxt, "missing": max(nxt - have, 0), "pct": min(100, round(have / nxt * 100)),
            "tier": TIER_NAMES[tier + 1], "unit": i["unit"]}

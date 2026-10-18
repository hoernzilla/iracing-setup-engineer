"""Aufbewahrung der Rohdateien (.ibt).

Das gemeinsame Wissen steckt in den Testergebnissen (community-history.json), Berichten und der
Datenbank – nicht in den Rohdateien. Die werden nur für eine Weile gebraucht (Neuauswertung,
Paarbildung) und danach gelöscht bzw. in einen Sicherungsordner verschoben.

Regeln (in der Verwaltung einstellbar):
* komplett ausgewertet  -> Rohdatei nach KEEP_DAYS Tagen weg
* Test unvollständig     -> bleibt, bis alle unvollständigen zusammen mehr als LIMIT_GB belegen;
                           dann bekommen sie eine Frist von GRACE_DAYS Tagen (der Fahrer sieht einen Hinweis)
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("portal.retention")

DEFAULTS = {"keep_days": 14, "limit_gb": 60, "grace_days": 30}


def config(db) -> dict:
    out = {}
    for key, default in DEFAULTS.items():
        v = db.get_setting(f"retention_{key}")
        out[key] = int(v) if v.isdigit() and int(v) > 0 else default
    out["move_to"] = db.get_setting("retention_move_to").strip()
    return out


def _dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    d = datetime.fromisoformat(iso)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def is_complete(row: dict) -> bool:
    """Fertig ausgewertet und nichts mehr offen: Grunddaten/Archiv nach der Auswertung,
    Tests sobald der Vergleich vorliegt. Aussortierte Dateien gelten ebenfalls als erledigt."""
    if row["status"] != "fertig":
        return False
    if row.get("excluded_at") or row["test_type"] in ("normal", "archiv"):
        return True
    return bool(row.get("ab_summary"))


def status(row: dict, cfg: dict, now: datetime | None = None) -> dict:
    """Was passiert mit der Rohdatei? Für die Anzeige beim Fahrer und in der Verwaltung."""
    now = now or datetime.now(timezone.utc)
    if row.get("raw_deleted_at"):
        return {"kind": "geloescht", "date": row["raw_deleted_at"], "text": "Rohdatei gelöscht – Auswertung bleibt"}
    if row["status"] in ("wartet", "läuft"):
        return {"kind": "laeuft", "date": None, "text": "wird ausgewertet"}
    if is_complete(row):
        base = _dt(row.get("done_at") or row["uploaded_at"])
        until = base + timedelta(days=cfg["keep_days"])
        return {"kind": "komplett", "date": until.isoformat(timespec="minutes"),
                "days": max(0, (until - now).days), "text": "komplett ausgewertet"}
    why = _why_incomplete(row)
    if row.get("delete_after"):
        until = _dt(row["delete_after"])
        return {"kind": "frist", "date": row["delete_after"], "days": max(0, (until - now).days),
                "text": "Test unvollständig – bitte vervollständigen", "why": why}
    return {"kind": "offen", "date": None, "text": "Test unvollständig – Datei bleibt erhalten", "why": why}


def _why_incomplete(row: dict) -> str:
    if row["status"] == "fehler":
        return "Die Auswertung ist fehlgeschlagen. Die Admins schauen sich das an."
    if row.get("test_note"):
        return row["test_note"]
    if row["test_type"] == "aba":
        return ("In der Datei wurde keine Umstellung im Auto erkannt. Fahr den A-B-A-Test bitte noch einmal: "
                "Block A, umstellen, Block B, auf exakt A zurückstellen, Block A – alles in einer Session.")
    if row["test_type"] == "garage":
        return "Die anderen Runs dieses Garagen-Tests werden noch ausgewertet."
    return "Noch nicht vollständig ausgewertet."


def _remove(row: dict, move_to: str) -> None:
    src = Path(row["stored_path"])
    if not src.exists():
        return
    if move_to:
        dest = Path(move_to) / row["user_id"]
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest / f"{row['id']}_{row['filename']}"))
    else:
        src.unlink()


def run(db, now: datetime | None = None) -> dict:
    """Einmal aufräumen. Gibt eine Zusammenfassung zurück (für Protokoll und Verwaltung)."""
    now = now or datetime.now(timezone.utc)
    cfg = config(db)
    rows = [r for r in db.all_uploads(limit=10_000_000) if not r.get("raw_deleted_at")]
    incomplete = [r for r in rows if r["status"] in ("fertig", "fehler") and not is_complete(r)]
    inc_bytes = sum(r["size"] or 0 for r in incomplete)
    flagged = 0
    if inc_bytes > cfg["limit_gb"] * 1024**3:
        until = (now + timedelta(days=cfg["grace_days"])).isoformat(timespec="minutes")
        for r in incomplete:
            if not r.get("delete_after"):
                db.update_upload(r["id"], delete_after=until)
                r["delete_after"] = until
                flagged += 1
    removed, freed = 0, 0
    for r in rows:
        st = status(r, cfg, now)
        if st["kind"] in ("komplett", "frist") and _dt(st["date"]) <= now:
            try:
                _remove(r, cfg["move_to"])
            except OSError as e:
                log.warning("Rohdatei %s nicht entfernt: %s", r["id"], e)
                continue
            db.update_upload(r["id"], raw_deleted_at=now.isoformat(timespec="minutes"))
            removed += 1
            freed += r["size"] or 0
    return {"removed": removed, "freed_gb": freed / 1024**3, "flagged": flagged, "incomplete_gb": inc_bytes / 1024**3}


def overview(db, data_dir: Path) -> dict:
    cfg = config(db)
    rows = [r for r in db.all_uploads(limit=10_000_000) if not r.get("raw_deleted_at")]
    gb = lambda rs: sum(r["size"] or 0 for r in rs) / 1024**3  # noqa: E731
    complete = [r for r in rows if is_complete(r)]
    incomplete = [r for r in rows if r["status"] in ("fertig", "fehler") and not is_complete(r)]
    try:
        disk = shutil.disk_usage(data_dir)
        free_gb, total_gb = disk.free / 1024**3, disk.total / 1024**3
    except OSError:
        free_gb = total_gb = None
    return {
        "cfg": cfg,
        "raw_gb": gb(rows),
        "complete_gb": gb(complete),
        "complete_n": len(complete),
        "incomplete_gb": gb(incomplete),
        "incomplete_n": len(incomplete),
        "flagged_n": sum(1 for r in incomplete if r.get("delete_after")),
        "free_gb": free_gb,
        "total_gb": total_gb,
        "last_run": db.get_setting("retention_last_run"),
    }

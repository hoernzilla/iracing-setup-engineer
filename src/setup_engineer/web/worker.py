"""Hintergrund-Auswertung hochgeladener IBT-Dateien.

Eine Datei nach der anderen (ein Arbeits-Thread): Analyse einer 100-MB-Session
dauert ~1 s, braucht aber Speicher – parallel bringt bei einer Community nichts.

Pro Upload:
* Analyse + Empfehlungen (mit dem gesammelten Community-Wissen)
* wurde im Auto umgestellt (A-B-A)? -> Vergleich der Rundengruppen, Test speichern
* Garage-Test (zwei Dateien) -> sobald beide fertig: A/B-Vergleich, Test speichern
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
import logging
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import __version__
from ..classes import car_class
from ..analysis import analyze_file
from ..compare import ab_compare, ab_within
from ..ibt import IbtError
from ..recommend.engine import recommend
from ..recommend.history import History, record_from_ab
from ..recommend.report import recommend_markdown
from ..report import ab_markdown, session_markdown
from .config import Settings
from .db import Database

log = logging.getLogger("portal.worker")

QUEUED, RUNNING, DONE, FAILED = "wartet", "läuft", "fertig", "fehler"
ARCHIVE = "archiv"
ARCHIVE_MIN_LAPS = 5
ARCHIVE_PAIR_HOURS = 4  # Altdaten: zwei Sessions gelten als Paar, wenn sie so nah beieinander liegen


class Worker:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.s = settings
        self.db = db
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="auswertung")
        self._history_lock = threading.Lock()

    def resume(self) -> None:
        """Nach einem Neustart liegengebliebene Uploads erneut einreihen."""
        for row in self.db.uploads_by_status(QUEUED, RUNNING):
            self.submit(row["id"])

    def submit(self, upload_id: str) -> None:
        self.pool.submit(self._run, upload_id)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    def _history(self) -> History:
        return History(self.s.history_path)

    def _save_test(self, record) -> None:
        with self._history_lock:
            h = self._history()
            h.add(record)
            h.save()

    def _counts(self, rows: list[dict]) -> bool:
        """Fließt der Test ins gemeinsame Wissen? Nicht bei aussortierten Uploads oder gesperrten Teilnehmern."""
        for r in rows:
            fresh = self.db.get_upload(r["id"]) or r
            user = self.db.get_user(fresh["user_id"])
            if fresh.get("excluded_at") or (user and user.get("banned_at")):
                return False
        return True

    def _run(self, upload_id: str) -> None:
        row = self.db.get_upload(upload_id)
        if row is None:
            return
        self.db.update_upload(upload_id, status=RUNNING, error=None)
        try:
            a = analyze_file(row["stored_path"])
            rs = recommend(a, self._history())
            report = session_markdown(a, recommend_markdown(a, rs, standalone=False))
            report = report.replace(Path(row["stored_path"]).name, row["filename"])  # Originalname statt interner ID
            report_path = self.s.reports_dir / f"{upload_id}.md"
            report_path.write_text(report, encoding="utf-8")
            best = a.laps.best
            fields = dict(
                car=a.ibt.car_name,
                track=a.ibt.track_name,
                session_start=a.ibt.start_date.isoformat(timespec="minutes"),
                laps_total=len(a.laps.laps),
                laps_valid=len(a.laps.valid),
                best_lap_s=best.time_s if best else None,
                report_path=str(report_path),
                analysis_version=__version__,
                next_test=_next_test(rs),
            )
            archive = row["test_type"] == ARCHIVE
            if archive:
                why = None
                if car_class(a.ibt.car_name) is None:
                    why = "kein GT3 oder GTP"
                elif len(a.laps.valid) < ARCHIVE_MIN_LAPS:
                    why = f"weniger als {ARCHIVE_MIN_LAPS} saubere Runden"
                if why:
                    self.db.update_upload(upload_id, status=DONE, **fields)
                    self.db.exclude_upload(upload_id, f"Archiv: {why}", "automatisch")
                    return
            # A-B-A innerhalb der Session (im Auto umgestellt)
            within = ab_within(a) if row["test_type"] != "garage" else None
            if within is not None:
                r, name_a, name_b = within
                ab_path = self.s.reports_dir / f"{upload_id}-ab.md"
                ab_text = ab_markdown(r, name_a, name_b).replace(Path(row["stored_path"]).name, row["filename"])
                ab_path.write_text(ab_text, encoding="utf-8")
                rec = record_from_ab(r, a, None, within_session=True)
                rec.file_a = rec.file_b = f"{row['user_id']}/{row['filename']}"
                if archive:
                    rec.source = ARCHIVE
                if self._counts([row]):
                    self._save_test(rec)
                fields.update(ab_report_path=str(ab_path), ab_summary=_summary(r))
            self.db.update_upload(upload_id, status=DONE, **fields)
            if row["pair_id"]:
                self._try_pair(row["pair_id"])
            elif archive and within is None:
                self._try_archive_pair(upload_id)
        except IbtError as e:
            self.db.update_upload(upload_id, status=FAILED, error=f"Keine gültige iRacing-Telemetrie: {e}")
        except Exception as e:  # noqa: BLE001 – Fehler gehören in die Oberfläche, nicht in den Absturz
            log.error("Auswertung %s fehlgeschlagen:\n%s", upload_id, traceback.format_exc())
            self.db.update_upload(upload_id, status=FAILED, error=f"Auswertung fehlgeschlagen ({type(e).__name__}: {e})")

    def _try_pair(self, pair_id: str) -> None:
        members = self.db.pair_members(pair_id)
        if len(members) != 2 or any(m["status"] != DONE for m in members) or any(m["ab_summary"] for m in members):
            return
        try:
            x, y = (analyze_file(m["stored_path"]) for m in members)

            def started(s) -> tuple:
                t = s.ibt.get("SessionTime")
                return (s.ibt.disk.session_start_date, float(t[0]) if len(t) else 0.0)

            pairs = list(zip((x, y), members))
            pairs.sort(key=lambda p: started(p[0]))
            (a, ma), (b, mb) = pairs
            r = ab_compare(a, b)
            ab_path = self.s.reports_dir / f"{pair_id}-ab.md"
            ab_path.write_text(ab_markdown(r, ma["filename"], mb["filename"]), encoding="utf-8")
            rec = record_from_ab(r, a, b)
            rec.file_a, rec.file_b = f"{ma['user_id']}/{ma['filename']}", f"{mb['user_id']}/{mb['filename']}"
            if self._counts(members):
                self._save_test(rec)
            summary = _summary(r)
            for m in members:
                self.db.update_upload(m["id"], ab_report_path=str(ab_path), ab_summary=summary)
        except Exception as e:  # noqa: BLE001
            log.error("Vergleich %s fehlgeschlagen:\n%s", pair_id, traceback.format_exc())
            for m in members:
                self.db.update_upload(m["id"], error=f"Vergleich fehlgeschlagen ({type(e).__name__}: {e})")


    def _try_archive_pair(self, upload_id: str) -> None:
        """Altdaten: Gibt es eine Session desselben Fahrers mit gleichem Auto und gleicher Strecke kurz davor
        oder danach, deren Setup sich in GENAU einer Einstellung unterscheidet? Dann ist das ein Garage-Test."""
        row = self.db.get_upload(upload_id)
        if not row or row["pair_id"] or not row["session_start"]:
            return
        t0 = datetime.fromisoformat(row["session_start"])
        best, best_gap = None, None
        for o in self.db.all_uploads(user_id=row["user_id"], status=DONE, excluded="nein", limit=100_000):
            if o["id"] == row["id"] or o["pair_id"] or o["ab_summary"] or o["test_type"] != ARCHIVE:
                continue
            if o["car"] != row["car"] or o["track"] != row["track"] or not o["session_start"]:
                continue
            gap = abs((datetime.fromisoformat(o["session_start"]) - t0).total_seconds()) / 3600
            if gap <= ARCHIVE_PAIR_HOURS and (best_gap is None or gap < best_gap):
                best, best_gap = o, gap
        if best is None:
            return
        try:
            x, y = analyze_file(row["stored_path"]), analyze_file(best["stored_path"])
            (a, ma), (b, mb) = sorted([(x, row), (y, best)], key=lambda p: p[1]["session_start"])
            r = ab_compare(a, b)
            if _distinct_changes(r.setup_changes) != 1:
                return  # keine oder mehrere Änderungen -> kein Test
            pid = uuid.uuid4().hex
            ab_path = self.s.reports_dir / f"{pid}-ab.md"
            ab_path.write_text(ab_markdown(r, ma["filename"], mb["filename"]), encoding="utf-8")
            rec = record_from_ab(r, a, b)
            rec.file_a, rec.file_b = f"{ma['user_id']}/{ma['filename']}", f"{mb['user_id']}/{mb['filename']}"
            rec.source = ARCHIVE
            if self._counts([ma, mb]):
                self._save_test(rec)
            summary = _summary(r)
            for m in (ma, mb):
                self.db.update_upload(m["id"], pair_id=pid, ab_report_path=str(ab_path), ab_summary=summary)
        except Exception:  # noqa: BLE001 – ein Fund weniger, kein Fehler für den Nutzer
            log.warning("Archiv-Paar %s nicht auswertbar:\n%s", upload_id, traceback.format_exc())


def _distinct_changes(changes) -> int:
    """Zahl der Änderungen; links/rechts gleich verstellt (z. B. beide Vorderfedern) zählt als eine."""
    keys = {(re.sub(r"(Left|Right)(Front|Rear)", r"\2", c.path), c.before, c.after) for c in changes}
    return len(keys)


def _next_test(rs) -> str | None:
    """Die oberste Empfehlung als konkreter nächster Test."""
    if not rs.recommendations:
        return None
    r = rs.recommendations[0]
    how = "im Auto als A-B-A in einer Session" if r.incar else "als Garage-Test mit zwei Runs"
    title = f"{r.parameter.replace(' (im Auto)', '')} zurück auf {r.proposed}" if r.revert_of else r.candidate.title
    return f"{title}: {r.parameter.replace(' (im Auto)', '')} {r.current} → {r.proposed}, {how}."


def _summary(r) -> str:
    changes = "; ".join(f"{c.path.replace('Im Auto: ', '')} {c.before} → {c.after}" for c in r.setup_changes) or "keine Änderung erkannt"
    return json.dumps(
        {
            "changes": changes,
            "verdict": r.verdict,
            "effect_s": None if r.effect_s != r.effect_s else round(r.effect_s, 3),
            "laps_a": r.laps_a,
            "laps_b": r.laps_b,
        },
        ensure_ascii=False,
    )


def report_text(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else None

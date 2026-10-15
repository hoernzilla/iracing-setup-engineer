"""Berichte als Markdown (für Menschen) und JSON (für spätere Phasen)."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, is_dataclass
from typing import Any

from .analysis import SessionAnalysis
from .compare import ABResult


def _fmt_time(s: float) -> str:
    if not math.isfinite(s):
        return "–"
    m, sec = divmod(s, 60)
    return f"{int(m)}:{sec:06.3f}"


def _f(x: float | None, digits: int = 1, suffix: str = "") -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "–"
    return f"{x:.{digits}f}{suffix}"


def _pct(x: float | None) -> str:
    return _f(None if x is None else x * 100, 0, " %")


def session_markdown(a: SessionAnalysis) -> str:
    ibt = a.ibt
    L: list[str] = []
    L.append(f"# Analyse: {ibt.car_name} – {ibt.track_name}\n")
    best = a.laps.best
    L.append(f"- Datei: `{ibt.path.name}`")
    L.append(f"- Aufnahme: {ibt.start_date:%d.%m.%Y %H:%M} UTC, {ibt.duration_s / 60:.1f} min, {ibt.tick_rate} Hz")
    L.append(f"- Runden: {len(a.laps.laps)} gesamt, {len(a.laps.valid)} gültig")
    if best:
        L.append(f"- Bestzeit: **{_fmt_time(best.time_s)}** (Runde {best.number})")
    L.append(f"- Kanäle: {a.inventory.total}, davon {len(a.inventory.hi_res)} hochauflösend")
    L.append("")

    if a.notes:
        L.append("## Hinweise\n")
        L += [f"- {n}" for n in a.notes]
        L.append("")

    # Runden
    L.append("## Runden\n")
    L.append("| Runde | Zeit | Δ Best | Sprit Start (l) | Strecke °C | Status |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for lap in a.laps.laps:
        delta = lap.time_s - best.time_s if best else float("nan")
        status = "gültig" if lap.valid else ", ".join(lap.reasons)
        L.append(
            f"| {lap.number} | {_fmt_time(lap.time_s)} | {_f(delta, 3)} | {_f(lap.fuel_start_l)} | "
            f"{_f(lap.track_temp_c)} | {status} |"
        )
    L.append("")

    # Kurven
    if a.corners:
        L.append("## Erkannte Kurven\n")
        L.append("| Kurve | Richtung | Bremsbeginn | Einlenken | Scheitel | Ende | v min (km/h) | Radius min (m) |")
        L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for c in a.corners:
            L.append(
                f"| {c.name} | {c.direction} | {c.brake_start:.3f} | {c.start:.3f} | {c.apex:.3f} | "
                f"{c.end:.3f} | {c.min_speed_kmh:.0f} | {c.min_radius_m:.0f} |"
            )
        L.append("\nPositionen als Anteil der Runde (LapDistPct).\n")

    # Balance
    if a.balance:
        L.append("## Balance (Unter-/Übersteuern)\n")
        if a.steer_model:
            L.append(f"Lenkmodell aus {a.steer_model.samples} Messpunkten im linearen Bereich gelernt.\n")
        L.append("| Kurve | Phase | Lenküberschuss | Streuung | Gegenlenken | Tendenz | Ursache | r(Eingangstempo) |")
        L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for b in a.balance:
            L.append(
                f"| {b.corner} | {b.phase} | {_f(b.understeer * 100, 0, ' %')} | {_f(b.lap_spread * 100, 0, ' %')} | "
                f"{_pct(b.countersteer_share)} | {b.tendency} | {b.verdict} | {_f(b.entry_speed_corr, 2)} |"
            )
        L.append(
            "\nLenküberschuss > 0 = mehr Lenkung als neutral nötig (Untersteuern). "
            "„Auto“ = konstant über die Runden → Setup-Thema; „Fahrer“ = hängt vom Eingangstempo ab → Fahrweise.\n"
        )

    # Plattform
    p = a.platform
    if p:
        if p.ride_height:
            L.append("## Plattform / Ride Height\n")
            L.append("| Zone | vorne (mm) | hinten (mm) | Rake (mm) | Minimum (mm) | Runden mit Aufsetzer |")
            L.append("| --- | --- | --- | --- | --- | --- |")
            for r in p.ride_height:
                L.append(
                    f"| {r.zone} | {_f(r.front_mm)} | {_f(r.rear_mm)} | {_f(r.rake_mm)} | {_f(r.min_mm)} | {r.bottoming_laps} |"
                )
            L.append("")
        if p.bump_stops:
            L.append("## Bump Stops\n")
            L.append("| Rad | Gap (mm) | max. Federweg (mm) | Kontaktanteil |")
            L.append("| --- | --- | --- | --- |")
            for r in p.bump_stops:
                L.append(f"| {r.wheel} | {_f(r.gap_mm)} | {_f(r.max_defl_mm)} | {_pct(r.contact_share)} |")
            L.append(f"\n{p.bump_stops[0].note}\n")
        if p.dampers:
            L.append("## Dämpfer\n")
            L.append("| Rad | Quelle | Einfedern | Low-Speed-Anteil | p95 Bump (mm/s) | p95 Rebound (mm/s) | Symmetrie |")
            L.append("| --- | --- | --- | --- | --- | --- | --- |")
            for d in p.dampers:
                L.append(
                    f"| {d.wheel} | `{d.source}` | {_pct(d.bump_share)} | {_pct(d.ls_share)} | "
                    f"{_f(d.p95_bump_mms, 0)} | {_f(d.p95_rebound_mms, 0)} | {_f(d.symmetry, 2)} |"
                )
            L.append("")
        if p.notes:
            L += [f"- {n}" for n in p.notes]
            L.append("")

    # Fahrstil
    s = a.style
    if s:
        L.append("## Fahrstil\n")
        L.append(f"- Trail Braking (Anteil Einlenkphase mit Bremse): {_pct(s.trail_braking)}")
        L.append(f"- Mittlerer Spitzen-Bremsdruck: {_pct(s.peak_brake)}")
        L.append(f"- ABS-Eingriff in Bremsphasen: {_pct(s.abs_usage)}")
        L.append(f"- Konstanz Scheitelgeschwindigkeit: ±{_f(s.consistency_kmh)} km/h\n")
        L.append("| Kurve | Spitzenbremse | Trail Braking | ABS | v min (km/h) | Streuung (km/h) | Vollgas nach Scheitel |")
        L.append("| --- | --- | --- | --- | --- | --- | --- |")
        for c in s.corners:
            L.append(
                f"| {c.corner} | {_pct(c.peak_brake)} | {_pct(c.trail_share)} | {_pct(c.abs_share)} | "
                f"{_f(c.min_speed_kmh, 0)} | {_f(c.min_speed_spread_kmh)} | {_f(c.full_throttle_after_apex_pct, 0, ' %')} |"
            )
        L.append("")

    # Kanal-Inventar
    L.append("## Verfügbare Kanäle\n")
    for g, names in a.inventory.groups.items():
        L.append(f"- **{g}** ({len(names)}): {', '.join(names) if names else '—'}")
    if a.inventory.other:
        L.append(f"- **Sonstige** ({len(a.inventory.other)}): {', '.join(a.inventory.other)}")
    L.append("")

    # Setup
    if len(a.setup):
        L.append("## Setup\n")
        L.append("| Parameter | Wert |")
        L.append("| --- | --- |")
        for path, v in a.setup.values.items():
            L.append(f"| {path} | {v.raw} |")
        L.append("")
    return "\n".join(L)


def ab_markdown(r: ABResult, name_a: str, name_b: str) -> str:
    L = [f"# A/B-Vergleich\n", f"- A: `{name_a}` ({r.laps_a} gültige Runden, Ø {_fmt_time(r.mean_a)})"]
    L.append(f"- B: `{name_b}` ({r.laps_b} gültige Runden, Ø {_fmt_time(r.mean_b)})")
    L.append(f"- Effekt B − A (bereinigt): **{_f(r.effect_s, 3, ' s')}**, 95-%-Intervall {_f(r.ci95_s[0], 3)} … {_f(r.ci95_s[1], 3)} s")
    L.append(f"- p-Wert: {_f(r.p_value, 3)} → **{r.verdict}**")
    if r.covariates:
        L.append(f"- Herausgerechnet: {', '.join(r.covariates)}")
    if r.laps_needed and r.verdict == "nicht entscheidbar":
        L.append(f"- Für ein klares Ergebnis bei diesem Effekt: ca. {r.laps_needed} Runden je Variante")
    L.append("\n## Setup-Unterschiede\n")
    if not r.setup_changes:
        L.append("Keine Unterschiede gefunden.")
    else:
        L.append("| Parameter | A | B | Δ |")
        L.append("| --- | --- | --- | --- |")
        for c in r.setup_changes:
            L.append(f"| {c.path} | {c.before or '–'} | {c.after or '–'} | {_f(c.delta, 3) if c.delta is not None else '–'} |")
    return "\n".join(L) + "\n"


def _jsonable(o: Any) -> Any:
    if is_dataclass(o) and not isinstance(o, type):
        return {k: _jsonable(v) for k, v in asdict(o).items()}
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if hasattr(o, "item"):  # numpy-Skalare
        return _jsonable(o.item())
    return o


def session_json(a: SessionAnalysis) -> str:
    ibt = a.ibt
    payload = {
        "file": ibt.path.name,
        "car": ibt.car_name,
        "car_path": ibt.car_path,
        "track": ibt.track_name,
        "track_length_m": ibt.track_length_m,
        "start_utc": ibt.start_date.isoformat(),
        "tick_rate": ibt.tick_rate,
        "laps": [
            {k: v for k, v in asdict(lap).items() if k not in ("start", "end")} for lap in a.laps.laps
        ],
        "corners": a.corners,
        "steer_model": a.steer_model,
        "balance": a.balance,
        "platform": a.platform,
        "style": a.style,
        "inventory": a.inventory,
        "setup": {p: {"raw": v.raw, "value": v.value, "unit": v.unit} for p, v in a.setup.values.items()},
        "notes": a.notes,
    }
    return json.dumps(_jsonable(payload), ensure_ascii=False, indent=2)

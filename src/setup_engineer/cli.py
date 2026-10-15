"""Kommandozeile.

    setup-engineer analyze   SESSION.ibt [--out ORDNER]
    setup-engineer recommend SESSION.ibt [--out ORDNER]
    setup-engineer compare   A.ibt [B.ibt] [--save] [--out ORDNER]
    setup-engineer channels  SESSION.ibt
    setup-engineer setup     SESSION.ibt

compare mit nur EINER Datei vergleicht die Rundengruppen eines A-B-A-Tests
(Einstellung im Auto während der Session verstellt).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analysis import analyze_file
from .channels import build_inventory
from .compare import ab_compare, ab_within
from .recommend.engine import recommend
from .recommend.history import History, record_from_ab
from .recommend.report import recommend_markdown
from .ibt import IbtError, IbtFile
from .report import ab_markdown, session_json, session_markdown
from .setup import CarSetup

DEFAULT_HISTORY = Path(__file__).resolve().parents[2] / "data" / "history.json"


def _write(out: Path | None, name: str, text: str) -> None:
    if out is None:
        print(text)
        return
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(text, encoding="utf-8")
    print(f"geschrieben: {out / name}")


def _history(args: argparse.Namespace) -> History:
    return History(args.history or DEFAULT_HISTORY)


def cmd_analyze(args: argparse.Namespace) -> int:
    hist = _history(args)
    for path in args.files:
        a = analyze_file(path)
        stem = Path(path).stem
        recs = recommend_markdown(a, recommend(a, hist), standalone=False)
        _write(args.out, f"{stem}.md", session_markdown(a, recs))
        if args.out:
            _write(args.out, f"{stem}.json", session_json(a))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    a = analyze_file(args.a)
    if args.b is None:
        res = ab_within(a)
        if res is None:
            print("Keine Verstellung im Auto zwischen gewerteten Runden gefunden – für A-B-A in einer Session "
                  "die Einstellung im Auto ändern, oder zwei Dateien angeben.")
            return 1
        r, name_a, name_b = res
        b = None
        out_name = f"ab_{Path(args.a).stem}.md"
    else:
        b = analyze_file(args.b)
        # Windows legt beim Drag & Drop die Reihenfolge nicht fest -> nach Aufnahmezeit sortieren:
        # die ältere Aufnahme ist A (vorher), die neuere B (nachher).
        def started(x) -> tuple:
            t = x.ibt.get("SessionTime")
            return (x.ibt.disk.session_start_date, float(t[0]) if len(t) else 0.0)

        if started(b) < started(a):
            a, b = b, a
        print(f"A (vorher):  {a.ibt.path.name}  ({a.ibt.start_date:%d.%m.%Y %H:%M} UTC)")
        print(f"B (nachher): {b.ibt.path.name}  ({b.ibt.start_date:%d.%m.%Y %H:%M} UTC)")
        r = ab_compare(a, b)
        name_a, name_b = a.ibt.path.name, b.ibt.path.name
        out_name = "ab_vergleich.md"
    _write(args.out, out_name, ab_markdown(r, name_a, name_b))
    if args.save:
        hist = _history(args)
        hist.add(record_from_ab(r, a, b, within_session=b is None))
        hist.save()
        print(f"Test in der Historie gespeichert: {hist.path}")
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    a = analyze_file(args.file)
    _write(args.out, f"empfehlungen_{Path(args.file).stem}.md", recommend_markdown(a, recommend(a, _history(args))))
    return 0


def cmd_channels(args: argparse.Namespace) -> int:
    ibt = IbtFile.open(args.file)
    inv = build_inventory(ibt)
    print(f"{ibt.car_name} – {ibt.track_name}: {inv.total} Kanäle\n")
    for g, names in inv.groups.items():
        print(f"[{g}] {len(names)}")
        for n in names:
            vh = ibt.var_headers[n]
            hz = f" ×{vh.count}" if vh.count > 1 else ""
            print(f"  {n:<28} {vh.type_name:<8}{hz:<5} {vh.unit:<10} {vh.desc}")
    if inv.other:
        print(f"[Sonstige] {len(inv.other)}")
        for n in inv.other:
            vh = ibt.var_headers[n]
            print(f"  {n:<28} {vh.type_name:<8} {vh.unit:<10} {vh.desc}")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    ibt = IbtFile.open(args.file)
    setup = CarSetup.from_session_info(ibt.session_info)
    print(f"{ibt.car_name} – {ibt.track_name}: {len(setup)} Setup-Werte\n")
    for path, v in setup.values.items():
        ro = "  (Anzeige)" if v.likely_read_only else ""
        print(f"  {path:<55} {v.raw}{ro}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="setup-engineer", description="iRacing Setup-Engineer")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("analyze", help="Session analysieren und Bericht erzeugen")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--out", type=Path, help="Ausgabeordner (sonst Markdown auf die Konsole)")
    s.add_argument("--history", type=Path, help="Test-Historie (Standard: data/history.json)")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("recommend", help="Setup-Empfehlungen für eine Session")
    s.add_argument("file", type=Path)
    s.add_argument("--out", type=Path)
    s.add_argument("--history", type=Path)
    s.set_defaults(func=cmd_recommend)

    s = sub.add_parser("compare", help="A/B-Vergleich zweier Runs oder (eine Datei) der A-B-A-Gruppen")
    s.add_argument("a", type=Path)
    s.add_argument("b", type=Path, nargs="?")
    s.add_argument("--out", type=Path)
    s.add_argument("--save", action="store_true", help="Ergebnis in der Test-Historie speichern")
    s.add_argument("--history", type=Path)
    s.set_defaults(func=cmd_compare)

    s = sub.add_parser("channels", help="Verfügbare Telemetriekanäle auflisten")
    s.add_argument("file", type=Path)
    s.set_defaults(func=cmd_channels)

    s = sub.add_parser("setup", help="Setup aus der IBT-Datei ausgeben")
    s.add_argument("file", type=Path)
    s.set_defaults(func=cmd_setup)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (IbtError, FileNotFoundError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

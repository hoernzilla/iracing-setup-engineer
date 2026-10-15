"""Kommandozeile.

    setup-engineer analyze  SESSION.ibt [--out ORDNER]
    setup-engineer compare  A.ibt B.ibt [--out ORDNER]
    setup-engineer channels SESSION.ibt
    setup-engineer setup    SESSION.ibt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analysis import analyze_file
from .channels import build_inventory
from .compare import ab_compare
from .ibt import IbtError, IbtFile
from .report import ab_markdown, session_json, session_markdown
from .setup import CarSetup


def _write(out: Path | None, name: str, text: str) -> None:
    if out is None:
        print(text)
        return
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(text, encoding="utf-8")
    print(f"geschrieben: {out / name}")


def cmd_analyze(args: argparse.Namespace) -> int:
    for path in args.files:
        a = analyze_file(path)
        stem = Path(path).stem
        _write(args.out, f"{stem}.md", session_markdown(a))
        if args.out:
            _write(args.out, f"{stem}.json", session_json(a))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    a, b = analyze_file(args.a), analyze_file(args.b)
    r = ab_compare(a, b)
    _write(args.out, "ab_vergleich.md", ab_markdown(r, Path(args.a).name, Path(args.b).name))
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
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("compare", help="A/B-Vergleich zweier Runs")
    s.add_argument("a", type=Path)
    s.add_argument("b", type=Path)
    s.add_argument("--out", type=Path)
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

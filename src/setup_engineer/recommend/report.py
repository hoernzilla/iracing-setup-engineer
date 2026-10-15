"""Empfehlungen als Markdown."""

from __future__ import annotations

from ..analysis import SessionAnalysis
from .engine import RecommendationSet


def recommend_markdown(a: SessionAnalysis, rs: RecommendationSet, *, standalone: bool = True) -> str:
    L: list[str] = []
    h = "##"
    if standalone:
        L.append(f"# Setup-Empfehlungen: {a.ibt.car_name} – {a.ibt.track_name}\n")
        L.append(f"Grundlage: `{a.ibt.path.name}`, {len(a.laps.valid)} gültige Runden.\n")
    L.append(f"{h} Empfohlene Änderungen\n")

    if not rs.recommendations:
        L.append("Keine Änderung mit klarem Nutzen gefunden – das Auto zeigt keine deutlichen Setup-Symptome.\n")
    for i, r in enumerate(rs.recommendations, 1):
        c = r.candidate
        title = f"{r.parameter.replace(' (im Auto)', '')} zurück auf {r.proposed}" if r.revert_of else c.title
        L.append(f"{h}# {i}. {title}\n")
        if r.revert_of is not None:
            t = r.revert_of
            L.append(
                f"Du fährst gerade mit dem Wert aus deinem Test {t.file_a} → {t.file_b}. Dort warst du "
                f"{t.lap_delta_s:+.3f} s pro Runde langsamer (Messung: {t.quality}).\n"
            )
        L.append(f"- **Änderung:** {r.parameter}: **{r.current} → {r.proposed}**")
        L.append(f"- **Wo:** {'im Auto während der Fahrt' if r.incar else 'in der Garage'}")
        L.append(f"- **Konfidenz:** {r.confidence}")
        L.append(f"- **Warum:** {c.why}")
        if r.helps:
            L.append("- **Hilft gegen:** " + "; ".join(t for t, _ in r.helps))
        if r.hurts:
            L.append("- **Kann verschlechtern:** " + "; ".join(t for t, _ in r.hurts))
        L.append(f"- **Risiko:** {c.risks}")
        for e in r.evidence:
            L.append(f"- **Beleg:** {e.text()}")
        if r.tested is not None:
            lt = r.tested.lap_delta_s
            L.append(
                f"- **Schon getestet:** {r.tested.file_a} → {r.tested.file_b}"
                + (f", Rundenzeit {lt:+.3f} s ({r.tested.quality})" if lt is not None else "")
            )
        L.append(f"- **Testplan:** {r.test_plan()}")
        L.append("")

    if rs.symptoms:
        L.append(f"{h} Erkannte Setup-Symptome\n")
        L.append("| Symptom | Schweregrad | Belege |")
        L.append("| --- | --- | --- |")
        for s in rs.symptoms:
            L.append(f"| {s.title} | {s.severity * 100:.0f} % | {'; '.join(s.evidence[:5])} |")
        L.append("")

    if rs.avoid:
        L.append(f"{h} Nicht empfohlen (Messung spricht dagegen)\n")
        for r in rs.avoid:
            L.append(f"- {r.candidate.title}: " + " ".join(e.text() for e in r.evidence if not e.confirms))
        L.append("")

    if rs.driver_hints:
        L.append(f"{h} Fahrhinweise (kein Setup-Thema)\n")
        L.append("Hier wurdest du mit mehr Eingangstempo insgesamt langsamer – das ist Fahrweise, kein Setup:\n")
        for d in rs.driver_hints:
            L.append(f"- **{d.corner}** {d.text}")
        L.append("")

    L.append(
        "_Empfehlungen beruhen auf Fahrdynamik-Grundlagen und – soweit vorhanden – auf deinen gemessenen Tests. "
        "Immer nur eine Änderung zur Zeit testen._\n"
    )
    return "\n".join(L)

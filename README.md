# iRacing Setup-Engineer

Privates Projekt: ein lokaler „Race Engineer“ für iRacing, der aus der eigenen Telemetrie
ein besseres Setup ableitet – mit Fokus auf **GT3** und **GTP**.

Konzept & Marktanalyse: https://claude.ai/code/artifact/ef2f48ff-029a-4ca5-bd09-af62bce56a8c

## Kernidee

1. **Erfassung** – Live-SDK (60 Hz, Federung 360 Hz), IBT-Import, Setup aus CarSetup-YAML
2. **Aufbereitung** – Runden, Kurven und Phasen erkennen; Normalisierung auf Sprit, Temperatur, Reifenalter
3. **Diagnose** – Balance-Index, Plattform, Dämpfer, Bremse, Traktion; Fahrer vs. Auto trennen
4. **Empfehlung** – Regelbasis + lernendes Antwortmodell pro Auto
5. **Ausgabe** – Klick-genaue Änderungsliste mit Begründung, Effekt und Konfidenz
6. **A/B-Test** – jede Änderung wird statistisch überprüft

## Status

Phase 1 + erster Teil von Phase 2 stehen, getestet mit synthetischen Daten.
Kalibrierung an echten GT3-/GTP-Daten steht noch aus.

| Baustein | Stand |
| --- | --- |
| IBT-Parser inkl. 360-Hz-Kanäle, robustes Session-YAML, abgebrochene Dateien | fertig |
| Setup aus IBT lesen, Werte + Einheiten, Setup-Diff | fertig |
| Runden schneiden, Out-/Inlaps, Off-Track, Ausreißer | fertig |
| Kurven + Phasen automatisch erkennen (ohne Streckendatenbank) | fertig |
| Balance-Index mit Fahrer-vs-Auto-Trennung | fertig, Schwellen vorläufig |
| Ride Height, Rake, Aufsetzer, Bump-Stop-Kontakt, Dämpfer-Histogramme | fertig, Schwellen vorläufig |
| Fahrstil: Trail Braking, ABS, Konstanz, Vollgaspunkt | fertig |
| A/B-Vergleich mit Sprit-/Temperaturbereinigung und Signifikanztest | fertig |
| Live-Telemetrie (Shared Memory, Windows) | Grundgerüst, ungetestet |
| Empfehlungs-Engine (Phase 3) | offen |

## Benutzung (Windows)

1. Python 3.11+ installieren: https://www.python.org/downloads/ – „Add python.exe to PATH“ anhaken.
2. Eine oder mehrere `.ibt`-Dateien per Drag & Drop auf **`Analyse.bat`** ziehen.
3. Berichte (`.md` + `.json`) liegen danach im Ordner `Berichte` neben den IBT-Dateien.

Kommandozeile:

```
python -m setup_engineer analyze  SESSION.ibt --out Berichte
python -m setup_engineer compare  A.ibt B.ibt          # A/B-Test zweier Runs
python -m setup_engineer channels SESSION.ibt           # welche Kanäle liefert das Auto?
python -m setup_engineer setup    SESSION.ibt           # Setup ausgeben
```

(vorher `set PYTHONPATH=src` bzw. `pip install -e .`)

## Tests

```
python -m unittest discover -s tests -v
```

Die Tests erzeugen synthetische IBT-Dateien mit bekannten, eingebauten Effekten
(T2 untersteuert konstant = Setup-Problem, T3 untersteuert nur bei zu hohem
Eingangstempo = Fahrerproblem) und prüfen, ob die Diagnose beides richtig trennt.

## Struktur

```
src/setup_engineer/
  ibt/          IBT-Format, Datei-Reader, Session-YAML, Live-Shared-Memory
  segment/      Runden, Kurven, Phasen
  diagnose/     Balance, Plattform/Dämpfer, Fahrstil
  setup.py      Setup lesen und vergleichen
  channels.py   Kanal-Inventar (GT3 vs. GTP)
  analysis.py   Gesamtablauf einer Session
  compare.py    A/B-Test
  report.py     Markdown-/JSON-Berichte
  synth.py      Synthetische Testdaten
  cli.py        Kommandozeile
tests/          Ende-zu-Ende-Tests
data/           Lokale Telemetrie (nicht im Repo)
```

## Testdaten

IBT-Dateien liegen unter `Dokumente\iRacing\telemetry` (Aufnahme in iRacing mit Alt+L).
Sie werden **nicht** ins Repo eingecheckt, sondern lokal unter `data/` abgelegt.

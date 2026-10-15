# Anleitung: Setup-Engineer unter Windows benutzen

## Einmalig einrichten

1. **Python installieren** (falls noch nicht vorhanden): https://www.python.org/downloads/
   Beim Installieren unten **„Add python.exe to PATH“** anhaken, dann „Install Now“.
2. **Programmordner entpacken**, zum Beispiel nach `C:\SetupEngineer`.
   Wichtig: Der ganze Ordner bleibt zusammen – die `.bat`-Dateien brauchen den Unterordner `src`
   und speichern die Test-Historie im Unterordner `data`.
3. Beim ersten Start installiert die `.bat` automatisch drei Python-Pakete (numpy, pyyaml, scipy).
   Dafür ist einmal Internet nötig; das dauert etwa eine Minute.

Tipp: Rechtsklick auf `Vergleich.bat` / `Analyse.bat` → „Senden an“ → „Desktop (Verknüpfung erstellen)“.
Auf die Verknüpfungen kannst du genauso Dateien ziehen.

## Telemetrie aufnehmen

- In iRacing während der Fahrt **Alt + L** drücken (oder in den Einstellungen „Telemetrie immer aufzeichnen“).
- Die Dateien landen in `Dokumente\iRacing\telemetry`; der Name enthält Auto, Strecke, Datum und Uhrzeit
  (z. B. `porsche963gtp_watkinsglen…_2026-10-15_02-41-44.ibt`).

## Analyse und Empfehlungen: `Analyse.bat`

Eine oder mehrere `.ibt`-Dateien auf **`Analyse.bat`** ziehen.
Ergebnis: im Ordner **`Berichte`** neben den `.ibt`-Dateien je ein Bericht `<Dateiname>.md`
(mit Empfehlungen ganz oben).

## Einen Test auswerten: `Vergleich.bat`

### Variante 1 – A-B-A in einer Session (empfohlen, am genauesten)

1. Eine Session fahren, Telemetrie läuft durchgehend.
2. 5 Runden mit der alten Einstellung, **im Auto** umstellen (z. B. Front-Stabi), 5 Runden,
   wieder zurückstellen, 5 Runden.
3. Die **eine** `.ibt`-Datei auf **`Vergleich.bat`** ziehen.

Die Runde, in der umgestellt wurde, wird automatisch nicht gewertet.

### Variante 2 – zwei Runs (für Garage-Änderungen)

1. Run A fahren (vorher), in die Box, Setup in der Garage ändern, Run B fahren (nachher).
2. **Beide** `.ibt`-Dateien markieren und **gleichzeitig** auf **`Vergleich.bat`** ziehen.
   Die Reihenfolge ist egal – die ältere Aufnahme wird automatisch A.

Ergebnis: Bericht `ab_vergleich.md` bzw. `ab_<Dateiname>.md` im Ordner `Berichte`.
Der Test wird zusätzlich in `data\history.json` gespeichert und fließt in künftige Empfehlungen ein.

## Berichte öffnen

Die Berichte sind Textdateien (`.md`). Sie lassen sich mit dem Editor öffnen
(Rechtsklick → Öffnen mit → Editor) – oder einfach an Claude schicken.

## Häufige Probleme

| Meldung | Lösung |
| --- | --- |
| „Python wurde nicht gefunden“ | Python installieren und „Add python.exe to PATH“ anhaken, danach Rechner neu anmelden |
| Windows warnt „Der Computer wurde durch Windows geschützt“ | „Weitere Informationen“ → „Trotzdem ausführen“ (passiert bei Dateien aus dem Internet) |
| „Keine Verstellung im Auto … gefunden“ | Bei Variante 1 wurde zwischen gewerteten Runden nichts im Auto verstellt – oder zwei Dateien ziehen |
| „No module named setup_engineer“ | Die `.bat` wurde aus dem Ordner herauskopiert – sie muss im Programmordner neben `src` liegen |

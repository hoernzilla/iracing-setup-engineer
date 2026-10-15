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

Phase 1 (Fundament): IBT-Parser, Setup-Parser, Segmentierung.

## Struktur

```
src/setup_engineer/   Python-Paket (Prototyp)
  ibt/                IBT-Datei lesen (Header, Kanäle, Session-YAML)
  segment/            Runden, Kurven, Phasen
  diagnose/           KPIs pro Kurve/Phase
data/                 Lokale Telemetrie (nicht im Repo)
docs/                 Notizen, Kanal-Inventar GT3/GTP
```

## Testdaten

IBT-Dateien liegen unter `Dokumente\iRacing\telemetry` (Aufnahme in iRacing mit Alt+L).
Sie werden **nicht** ins Repo eingecheckt, sondern lokal unter `data/` abgelegt.

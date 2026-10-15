# Erkenntnisse aus echten Daten

## Porsche 963 GTP – Watkins Glen Boot (15.10.2026)

### Datenformat
- 303 Kanäle, 60 Hz. 25 Kanäle liegen hochauflösend (360 Hz) als **6 Werte pro Datensatz unter dem
  normalen Namen** vor – nicht als `*_ST`. Betrifft u. a. `YawRate`, `LatAccel`, `LongAccel`,
  `VertAccel`, `Velocity*`, alle `*shockDefl`/`*shockVel` inkl. `HF`- und `ROLLF`-Kanälen.
- GTP-spezifisch: `HFshock*` (Front-Heave), `ROLLFshock*` (Front-Roll), `CFSRrideHeight` (Splitter),
  Hybrid-Kanäle (`PowerMGU_K`, `EnergyERSBattery*` …). Kein `HRshock*`.
- Radgeschwindigkeiten `LF/RF/LR/RRspeed` vorhanden → Schlupf direkt messbar.

### Reifen
- Karkassentemperaturen (`*tempCL/CM/CR`) und Verschleiß (`*wear*`) sind während der Fahrt **konstant**
  (nur Boxenstopp-Update).
- Live: Reifendruck (`*pressure`) und **eine** Oberflächentemperatur (`*tempL`).

### Setup ↔ Telemetrie
- Setup-Anzeigen der Form `"30.9 mm 100.0 mm"` = statischer Wert / maximaler Weg.
  Im Stand stimmen sie exakt mit der Telemetrie überein:
  `LeftRear.ShockDefl 30.9` ↔ `LRshockDefl 30.8`, `Front.HeaveSliderDefl 35.5` ↔ `HFshockDefl 35.4`,
  `Front.RollDamperDefl 0.0` ↔ `ROLLFshockDefl 0.1`.
- `*SpringDefl` hat einen anderen Bezug (Feder selbst) und wird nicht direkt zugeordnet.
- `TiresAero.AeroCalculator.*` (FrontRhAtSpeed, RearRhAtSpeed, DownforceBalance, LD) sind Eingaben/
  Ausgaben des iRacing-Aero-Rechners, keine Fahrzeugeinstellung.

### Ride Height
- Negative Werte kommen vor: kurze Ereignisse (≤ 150 ms) an festen Stellen.
  Sehr negative Werte (bis −38 mm) an Kerbs (Bus Stop, Kurvenausgänge) → Fahrbahn unter dem Messpunkt
  angehoben. Knapp unter 0 → vermutlich echtes Aufsetzen. Grenze −8 mm vorläufig.

### Balance
- Gelerntes Lenkmodell: 61 rad Lenkrad pro 1/m Krümmung (≈ 3,15 m Radstand × ~19:1) – plausibel.
- Klares Muster: neutral < 150 km/h, ca. +20 % Lenküberschuss > 200 km/h → Highspeed-Untersteuern.
- Passend dazu: Ride Height bei ~300 km/h vorne −2,8 mm, hinten −6,0 mm gegenüber dem Aero-Rechner
  (Rake 21,8 statt 25,0 mm).

### Offen
- Bezugspunkt der Aero-Rechner-Ride-Heights gegenüber den Telemetrie-Kanälen bestätigen.
- Kerb-/Aufsetz-Grenze an weiteren Strecken prüfen.
- GT3-Datei: Kanalumfang (ABS, Bump Rubber Gap?) vergleichen.

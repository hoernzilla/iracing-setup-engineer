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

### Verstellungen im Auto
- Der CarSetup-Block der IBT-Datei ist der **Garage-Stand**. Im Auto verstellte Werte stehen nur in den
  `dc*`-Kanälen (z. B. `dcAntiRollFront`, `dcBrakeBias`). Run 2: Garage `Front.ArbAdj 1`, im Auto in der
  Outlap auf 3 gestellt. Bremsbalance in beiden Runs in der Outlap von 48,25 auf 47,25 % gestellt.
- Wird innerhalb der gewerteten Runden verstellt, teilt die Analyse die Runden nach Einstellung auf
  (gleiche Session = vergleichbare Bedingungen).

### Run 2 (03:13 Uhr): Front-Stabi 1 → 3 (im Auto)
- Run B im Schnitt **0,8 s langsamer** (p < 0,001).
- Balance-Fingerabdruck des härteren Front-Stabis: mehr Untersteuern im mittleren Tempobereich
  (150–200 km/h +7 Pkt.; T11 +15, T3 +8, T12 +8 Pkt.), kaum Änderung > 250 km/h (+1 Pkt.).
  Passt zur Lehrbuchwirkung (mehr Wanksteifigkeit vorne → mehr Untersteuern).
- Gleichzeitig andere Bedingungen: **Luftdichte −4,6 %** (1,188 → 1,133 kg/m³), Strecke +1 °C.
  Passend dazu: Vmax −2,7 km/h (Stabi beeinflusst Vmax nicht → das ist die Luftdichte).
- Fazit: Der Zeitverlust ist eine Mischung aus Stabi und Bedingungen und lässt sich mit getrennten
  Runs nicht sauber aufteilen. Die Balance-Verschiebung im mittleren Tempo ist dagegen klar dem Stabi
  zuzuordnen, denn die Luftdichte wirkt vor allem im schnellen Bereich, und dort änderte sich kaum etwas.
- Folgen für die Methode:
  - Getrennte Runs sind nur bei gleichen Bedingungen vergleichbar → Bedingungen werden jetzt
    im A/B-Bericht gezeigt und gewarnt.
  - Störgrößen, die pro Run konstant sind, dürfen nicht ins Regressionsmodell (führte zu
    „2,7 s schneller“) → behoben, Regressionstest vorhanden.
  - Erste Runde nach der Box ist eine Aufwärmrunde (~1,5–2,5 s langsamer) → wird im A/B nicht gewertet.
  - Rundenstreuung des Fahrers ≈ ±0,3 s → für 0,2 s Effekt braucht es grob 30+ Runden je Variante;
    bessere Testabläufe (A-B-A in einer Session) nötig.

### Fahrer oder Auto? (Korrektur nach echten Daten)
- Erste Logik („Abweichung hängt vom Eingangstempo ab → Fahrer“) war falsch für den GTP: In schnellen
  Kurven schiebt das Auto mit mehr Tempo immer mehr – das ist Fahrzeugverhalten am Limit.
- Neues Kriterium: Fahrerfehler (Überfahren) nur, wenn mehr Eingangstempo die Abschnittszeit
  **verschlechtert**. In beiden echten Runs: kein Überfahren gefunden → Untersteuern in T2/T11/T12 ist Setup.

### Empfehlungs-Engine (Stand Run 2)
1. Stabilisator vorne zurück auf 1 (eigener Test: mit 3 langsamer und mehr Untersteuern)
2. Stabilisator hinten 15 → 14 (Übersteuern/Durchdrehen am Ausgang, Übersteuern beim Einlenken)
3. Traktionskontrolle +1 (Durchdrehen; Richtung der Stufen am Display prüfen)
- Für Run 1 erscheint zusätzlich Rake/Ride Height hinten gegen Highspeed-Untersteuern.

### Offen
- Bezugspunkt der Aero-Rechner-Ride-Heights gegenüber den Telemetrie-Kanälen bestätigen.
- Kerb-/Aufsetz-Grenze an weiteren Strecken prüfen.
- GT3-Datei: Kanalumfang (ABS, Bump Rubber Gap?) vergleichen.

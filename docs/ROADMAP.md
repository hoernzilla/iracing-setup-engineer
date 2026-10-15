# Roadmap

1. **Fundament** – Live-SDK-Reader und IBT-Import, Setup-Parser, Segmentierung, lokale Datenbank.
   Ergebnis: Eine beliebige IBT-Datei wird vollständig zerlegt und mit Setup verknüpft.
2. **Diagnose v1** – Balance-Index, Plattform (Ride Height, Bump Stops, Aufsetzer), Dämpfer-Histogramme, Bremsen, Traktion.
   Ergebnis: Diagnose deckt sich mit der Einschätzung eines erfahrenen Fahrers.
3. **Empfehlungen v1** – Regelbasis für GT3 und GTP, Fahrer-vs-Auto-Trennung, Klick-genaue Änderungsliste.
4. **Test-Loop** – Normalisierung, A/B-Vergleich mit Signifikanz, Rollback.
5. **Lernendes Modell** – setup-abhängiges Antwortmodell pro Auto, Bayes'sche Optimierung.
6. **Produkt** – Overlay/UI, Quali-/Rennvarianten, Abo.

## Nächster Schritt

Testdaten: je ein GT3- und ein GTP-Auto, mindestens 10 saubere Runden,
plus ein zweiter Run mit genau einer geänderten Einstellung (erster A/B-Fall).

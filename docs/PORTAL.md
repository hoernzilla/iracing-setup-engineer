# Community-Portal einrichten (Windows-Server)

Das Portal läuft als eigenes Programm neben dem RaceDirector – eigener Ordner, eigener Port.
Am RaceDirector wird nichts verändert.

Erreichbar ist es wie die Regie direkt über die Server-IP und einen eigenen Port:
**`http://SERVER-IP:29630`**. Bewusst nicht Port 80 oder 443, damit bei einem Blick auf die offenen
Ports kein Standard-Webserver auffällt. Eine Domain wird nicht gebraucht.

Gesamtdauer beim ersten Mal: etwa 30–45 Minuten.

---

## 1. Discord-Anwendung anlegen (einmalig, ca. 10 Minuten)

1. https://discord.com/developers/applications öffnen und mit deinem Discord-Konto anmelden.
2. **New Application** → Name z. B. „Setup-Engineer Portal“ → Bedingungen bestätigen → **Create**.
3. Links **OAuth2** öffnen:
   - **Client ID** kopieren → später in `DISCORD_CLIENT_ID`.
   - Bei **Client Secret** auf **Reset Secret** klicken, kopieren → später in `DISCORD_CLIENT_SECRET`.
     Das Secret ist wie ein Passwort: nicht weitergeben, nicht in den Chat posten.
   - Unter **Redirects** → **Add Redirect** die Adresse eintragen, die `Portal-Einrichten.bat` am Ende
     anzeigt, z. B. `http://203.0.113.7:29630/auth/callback` (mit der echten Server-IP).
     **Save Changes** nicht vergessen.
4. **Server-ID** eures Community-Discords holen:
   Discord → Einstellungen → Erweitert → **Entwicklermodus** einschalten.
   Dann Rechtsklick auf euren Server → **Server-ID kopieren** → später in `DISCORD_GUILD_ID`.
5. **Deine eigene Nutzer-ID** (für die Admin-Übersicht): Rechtsklick auf deinen Namen → **Nutzer-ID kopieren**
   → später in `PORTAL_ADMIN_DISCORD_IDS`. Mehrere Admins mit Komma trennen.
6. Optional – nur bestimmte Rolle zulassen: Rechtsklick auf die Rolle (Servereinstellungen → Rollen) →
   **Rollen-ID kopieren** → `DISCORD_REQUIRED_ROLE_IDS`. Leer lassen = alle Server-Mitglieder dürfen rein.

Ein Bot muss **nicht** auf den Server eingeladen werden. Das Portal fragt beim Login nur ab, ob die
Person Mitglied eures Servers ist (Scope `guilds.members.read`).

## 2. Portal auf den Server bringen

1. Den Projektordner auf den Server kopieren, z. B. nach `C:\SetupEngineer`
   (ZIP aus dem Chat entpacken oder das Repo klonen).
2. Falls noch nicht vorhanden: Python 3.11+ von https://www.python.org/downloads/ installieren.
   Im Installer **„Add python.exe to PATH“** anhaken und unter „Customize installation“
   **„Install Python for all users“** wählen (nötig für den Autostart).
3. **`Portal-Einrichten.bat`** mit Rechtsklick → **Als Administrator ausführen**. Sie
   - installiert alles und lädt die Schrift,
   - legt `portal.env` an, ermittelt die öffentliche IP des Servers und trägt die Redirect-Adresse ein,
   - zeigt die Adresse des Portals und die Redirect-Adresse für Discord an,
   - gibt Port 29630 in der Windows-Firewall frei,
   - öffnet `portal.env` im Editor: Dort die Werte aus Schritt 1 eintragen, speichern, schließen.
4. Hat der Hoster im Kundenmenü eine eigene Firewall, dort **TCP-Port 29630** eingehend freigeben.

## 3. Testen

1. **`Portal-Starten.bat`** doppelklicken. Das Fenster offen lassen. Es zeigt die Adresse für die Community an.
2. Von deinem eigenen Rechner aus `http://SERVER-IP:29630` öffnen (mit der echten IP).
3. **Mit Discord anmelden** → Discord fragt einmal nach der Freigabe → zurück im Portal
   → Einwilligung und Leitfaden bestätigen → eine `.ibt`-Datei hochladen.

Klappt das, kann der Link in den Community-Discord.

## 4. Port ändern (nur bei Bedarf)

Ist 29630 schon belegt oder soll ein anderer Port her:
1. In `portal.env` `PORTAL_PORT` ändern und in `DISCORD_REDIRECT_URI` denselben Port eintragen.
2. In der Discord-Anwendung die Redirect-Adresse genauso anpassen.
3. `Portal-Einrichten.bat` erneut als Administrator ausführen (setzt die Firewall-Freigabe neu),
   beim Hoster den neuen Port freigeben, Portal neu starten.

**Zur Verschlüsselung:** Ohne Domain läuft das Portal über `http://`, also unverschlüsselt – das ist bei
einer Adresse aus IP und Port der Normalfall. Für eine Community-Sammelstelle mit Telemetrie ist das vertretbar; Passwörter gibt es im Portal
keine, die Anmeldung läuft über Discord. Für den späteren bezahlten Dienst braucht es eine Domain mit
HTTPS; dann `PORTAL_HTTPS_ONLY=1` setzen.

## 5. Dauerbetrieb

- **`Portal-Autostart.bat`** mit Rechtsklick → **Als Administrator ausführen**: Das Portal startet dann
  bei jedem Hochfahren automatisch. Abschalten: `Portal-Autostart.bat entfernen` in einer
  Admin-Eingabeaufforderung.

## Verwaltung

Admins (aus `PORTAL_ADMIN_DISCORD_IDS` oder in der Verwaltung ernannt) sehen oben den Menüpunkt **Verwaltung**:
- **Teilnehmer:** sperren (mit Grund, 1/7/30 Tage oder dauerhaft, optional Daten aussortieren oder löschen),
  entsperren, entfernen (Konto und Daten löschen), zum Admin machen, Notizen, Leitfaden neu bestätigen lassen.
- **Uploads:** aussortieren (Datei bleibt, zählt aber nicht fürs gemeinsame Wissen), wieder werten, neu auswerten, löschen.
- **Protokoll:** jede Admin-Aktion mit Zeit und Name.
- **Einstellungen:** Ankündigungs-Banner, Uploads pausieren, Leitfaden von allen neu bestätigen lassen, alles neu auswerten.

Öffentlich sind **Das Projekt** (Motivationstext) und **Fortschritt** (Phasen, Tests je Auto, getestete Einstellungen).

## Altdaten (Archiv)

Unter **/archiv** laden Mitglieder alte Telemetrie gesammelt hoch (ohne Leitfaden-Pflicht). Der Browser prüft vorab Auto,
Klasse und Runden und überträgt nur GT3/GTP mit genug Runden. Alternativ gibt es `Telemetrie-Pruefen.bat` zum Herunterladen
(reines PowerShell, keine Installation), das passende Dateien auflistet und in `telemetry\Setup-Engineer-Upload` kopiert.
Der Server wertet: Grunddaten ab 5 sauberen Runden, versteckte Garagen-Tests (drei Sessions mit gleichem Auto/Strecke
innerhalb von 4 h: in der mittleren genau eine Änderung – links/rechts gleich zählt als eine –, die letzte exakt wie die erste)
und A-B-A-Verstellungen im Auto. Archiv-Tests zählen halb.
Ein- und ausschalten unter Verwaltung → Einstellungen.

## Speicher und Aufbewahrung

Gespeichert bleiben immer: Testergebnisse (`community-history.json`), Berichte, Datenbank. Die `.ibt`-Rohdateien werden
stündlich aufgeräumt (Verwaltung → Einstellungen → Speicher und Aufbewahrung):
- komplett ausgewertet (Grunddaten, Archiv, Tests mit Vergleich, aussortierte): Rohdatei nach 14 Tagen weg,
- unvollständige Tests: bleiben, bis sie zusammen mehr als 60 GB belegen; dann 30 Tage Frist, der Fahrer sieht einen roten Hinweis.
Optional ein Sicherungsordner: Dateien werden dorthin verschoben statt gelöscht. Ohne Rohdatei ist keine Neuauswertung möglich,
die bisherigen Ergebnisse bleiben aber erhalten.

## Was als Test zählt

Ins gemeinsame Wissen kommen nur **komplette** Tests:

* **A-B-A im Auto** (eine Datei): Block A, Block B, danach wieder exakt die Werte von A. Ohne zweites A, mit mehr als
  einer Umstellung oder unterbrochenem B gilt der Test als unvollständig.
* **Garagen-Test** (drei Dateien in einem Upload): Run A, Run B mit genau einer Änderung, Run A mit exakt demselben
  Setup wie der erste (vom Fahrer gespeichert und wieder geladen). Verglichen wird B gegen beide A; der Verlauf über die
  drei Runs (Strecke, Reifen, Fahrer) wird herausgerechnet.
* In jedem Block mindestens 4 gewertete Runden. Nie gewertet werden Out-Lap, die erste fliegende Runde nach der Box
  (kalte Reifen), Umstell-Runden, Runden neben der Strecke und deutliche Ausreißer.

Unvollständige Tests zählen nicht; der Fahrer sieht beim Upload den Grund (Spalte `test_note` in `uploads`).
Alte Garagen-Tests mit nur zwei Runs werden beim Neu-Auswerten nicht mehr gezählt.

## Trophäen und Bestenliste

Angemeldete Mitglieder sehen unter **Pokale** ihren eigenen Pokalschrank und unter **Bestenliste** die Top 10
(nur für Angemeldete, weil dort Namen stehen). Neue Trophäen erscheinen beim nächsten Seitenaufruf als Pop-up mit
Konfetti – Team-, geheime und Champion-Trophäen mit Feuerwerk, Pannen-Trophäen mit Wackeln.

* **Punkte:** 10 je komplettem Test, 5 je Test aus Altdaten, dazu die Trophäenpunkte (bei Stufen zählen alle
  erreichten Stufen). Lizenz: R, D ab 100, C ab 250, B ab 500, A ab 900, Pro ab 1.400.
* **Sichtbarkeit:** Den kompletten Katalog zeigt das Portal nirgends. Eine Trophäe ist erst sichtbar, wenn jemand sie hat.
* **Berechnung:** nach jeder Auswertung, nach dem stündlichen Aufräumen und bei Pannen-Ereignissen – aus dem Datenbestand,
  ohne aussortierte Uploads und gesperrte Teilnehmer. Einmal verdient bleibt verdient.
* **Je Auto:** Stufe-1- und Stufe-2-Kristall für alle Beteiligten, Champion für die meisten kompletten Tests im Auto,
  sobald es Stufe 2 erreicht (Gleichstand: wer die Zahl zuerst hatte). Je Klasse Krone und Meistergürtel, sobald alle
  5 GTP bzw. 11 GT3 so weit sind (`CLASS_SIZE` in `web/trophies.py`).
* **Aberkennen:** Verwaltung → Teilnehmer → Person → Trophäen. Aberkannte Trophäen werden nicht automatisch neu vergeben;
  „Zurückgeben“ macht das rückgängig. Beides steht im Protokoll.

Katalog, Schwellen und Punkte stehen in `src/setup_engineer/web/trophies.py`, die Zeichnungen in `web/static/trophies.js`.

## Test-Leitfaden

Vor dem ersten Upload muss jeder den Leitfaden bis zum Ende durchscrollen und bestätigen; vorher
lehnt der Server Uploads ab. Der Text steht in `src/setup_engineer/web/templates/_leitfaden.html`.
Bestätigt wird einmal beim ersten Login. Erneut bestätigen müssen alle nur, wenn ein Admin das unter
Verwaltung → Einstellungen → „Leitfaden von allen neu bestätigen lassen“ auslöst – auch nach Änderungen am Text.
Wer wann bestätigt hat, steht in der
Admin-Übersicht bzw. in `portal.sqlite3` (Spalten `guidelines_version`, `guidelines_at`).

## Aktualisieren

1. Die neue `SetupEngineer-Portal.zip` in den Portal-Ordner oder den Download-Ordner legen.
2. **`Portal-Aktualisieren.bat`** im Portal-Ordner mit Rechtsklick → **Als Administrator ausführen**.

Die Datei beendet das Portal, legt daneben eine Sicherung `…-Sicherung-Datum` an, spielt den neuen Stand ein
(`portal.env` und `portal-data` bleiben unberührt), prüft Pakete, Einstellungen und Firewall, startet das Portal und
prüft, ob es antwortet. Startet es nicht, wird die Sicherung automatisch zurückgespielt.
Beim allerersten Mal `Portal-Aktualisieren.bat` aus der ZIP in den Portal-Ordner kopieren.

Hintergrund-Betrieb von Hand (Eingabeaufforderung als Administrator):
`schtasks /run /tn "Setup-Engineer Portal"` · `schtasks /end /tn "Setup-Engineer Portal"` · `schtasks /query /tn "Setup-Engineer Portal"`

## Wo die Daten liegen

Alles im Ordner `portal-data` neben dem Programm (oder dem in `PORTAL_DATA_DIR` angegebenen Ordner):

| Datei/Ordner | Inhalt |
| --- | --- |
| `uploads\<Discord-ID>\` | hochgeladene `.ibt`-Dateien |
| `reports\` | fertige Auswertungen |
| `portal.sqlite3` | Teilnehmer und Uploads |
| `community-history.json` | gemessene Wirkung von Setup-Änderungen (das gemeinsame Wissen) |
| `session.key` | Schlüssel für die Login-Cookies – nicht weitergeben |

**Sicherung:** den Ordner `portal-data` regelmäßig kopieren (eine Session ≈ 100 MB).
`portal.env` und `portal-data` sind vom Git-Repo ausgeschlossen.

## Häufige Probleme

| Problem | Ursache / Lösung |
| --- | --- |
| „Discord-Anmeldung noch nicht eingerichtet“ | `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` oder `DISCORD_GUILD_ID` fehlen in `portal.env`; danach Portal neu starten |
| Discord meldet „Invalid OAuth2 redirect_uri“ | `DISCORD_REDIRECT_URI` und der Eintrag unter Redirects in der Discord-Anwendung müssen zeichengenau gleich sein |
| „Nur für Mitglieder“, obwohl Mitglied | falsche `DISCORD_GUILD_ID` (Server-ID, nicht Kanal-ID) |
| Nach dem Login sofort wieder abgemeldet | `PORTAL_HTTPS_ONLY=1`, aber Aufruf über `http://` – entweder HTTPS nutzen oder auf 0 setzen |
| Seite lädt von außen nicht | läuft `Portal-Starten.bat`? Firewall-Freigabe (Einrichten als Administrator) und Freigabe beim Hoster für TCP 29630 prüfen; auf dem Server selbst testen mit `http://localhost:29630` |
| Upload bricht bei großen Dateien ab | `PORTAL_MAX_UPLOAD_MB` in `portal.env` |
| Uhrzeiten um ein oder zwei Stunden verschoben | Gespeichert wird UTC, angezeigt in `PORTAL_TIMEZONE` (Standard `Europe/Berlin`); unter Windows braucht das das Paket `tzdata` – `Portal-Aktualisieren.bat` installiert es mit |

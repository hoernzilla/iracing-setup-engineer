# Community-Portal einrichten (Windows-Server)

Das Portal läuft als eigenes Programm neben dem RaceDirector – eigener Ordner, eigener Port (8420).
Am RaceDirector wird nichts verändert.

Gesamtdauer beim ersten Mal: etwa 30–45 Minuten.

---

## 1. Discord-Anwendung anlegen (einmalig, ca. 10 Minuten)

1. https://discord.com/developers/applications öffnen und mit deinem Discord-Konto anmelden.
2. **New Application** → Name z. B. „Setup-Engineer Portal“ → Bedingungen bestätigen → **Create**.
3. Links **OAuth2** öffnen:
   - **Client ID** kopieren → später in `DISCORD_CLIENT_ID`.
   - Bei **Client Secret** auf **Reset Secret** klicken, kopieren → später in `DISCORD_CLIENT_SECRET`.
     Das Secret ist wie ein Passwort: nicht weitergeben, nicht in den Chat posten.
   - Unter **Redirects** → **Add Redirect** die Adresse eintragen, unter der das Portal erreichbar ist,
     plus `/auth/callback`. Zum Beispiel:
     - zum Testen direkt auf dem Server: `http://localhost:8420/auth/callback`
     - im Betrieb: `https://telemetrie.deine-domain.de/auth/callback`

     Beide dürfen gleichzeitig eingetragen sein. **Save Changes** nicht vergessen.
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
3. **`Portal-Einrichten.bat`** doppelklicken. Sie installiert alles, lädt die Schrift und öffnet
   `portal.env` im Editor. Dort die Werte aus Schritt 1 eintragen, speichern, schließen.

## 3. Testen

1. **`Portal-Starten.bat`** doppelklicken. Das Fenster offen lassen.
2. Auf dem Server im Browser `http://localhost:8420` öffnen.
3. **Mit Discord anmelden** → Discord fragt einmal nach der Freigabe → zurück im Portal
   → Einwilligung bestätigen → eine `.ibt`-Datei hochladen.

Läuft das, fehlt nur noch die Erreichbarkeit von außen.

## 4. Von außen erreichbar machen (HTTPS)

Für die Community braucht das Portal eine Adresse mit `https://`. Empfohlen: **Caddy**, ein kleines
Programm, das das Zertifikat automatisch besorgt und erneuert.

Voraussetzungen:
- eine (Sub-)Domain, z. B. `telemetrie.deine-domain.de`, deren DNS-Eintrag (A-Record) auf die
  öffentliche IP des Servers zeigt,
- Ports **80 und 443** in der Server-Firewall bzw. beim Hoster freigegeben.
  Falls der RaceDirector oder ein anderer Dienst diese Ports schon belegt, vorher Bescheid geben –
  dann binden wir das Portal dort mit ein.

Schritte:
1. `caddy_windows_amd64.exe` von https://caddyserver.com/download herunterladen, in `C:\Caddy` legen und
   in `caddy.exe` umbenennen.
2. `deploy\Caddyfile` aus dem Projekt nach `C:\Caddy` kopieren und `telemetrie.example.de` durch die
   eigene Domain ersetzen.
3. In `portal.env`:
   - `DISCORD_REDIRECT_URI=https://telemetrie.deine-domain.de/auth/callback`
   - `PORTAL_HTTPS_ONLY=1`
   und dieselbe Adresse in der Discord-Anwendung unter Redirects eintragen.
4. Eingabeaufforderung in `C:\Caddy` öffnen: `caddy run`.
5. `https://telemetrie.deine-domain.de` aufrufen – fertig.

Das Portal selbst lauscht weiter nur auf `127.0.0.1:8420`, ist also nur über Caddy erreichbar.

## 5. Dauerbetrieb

- **`Portal-Autostart.bat`** mit Rechtsklick → **Als Administrator ausführen**: Das Portal startet dann
  bei jedem Hochfahren automatisch. Abschalten: `Portal-Autostart.bat entfernen` in einer
  Admin-Eingabeaufforderung.
- Caddy als Dienst: in einer Admin-Eingabeaufforderung in `C:\Caddy`:
  `sc create Caddy binPath= "C:\Caddy\caddy.exe run --config C:\Caddy\Caddyfile" start= auto`
  und `sc start Caddy`.

## Test-Leitfaden

Vor dem ersten Upload muss jeder den Leitfaden bis zum Ende durchscrollen und bestätigen; vorher
lehnt der Server Uploads ab. Der Text steht in `src/setup_engineer/web/templates/_leitfaden.html`.
Wird er inhaltlich geändert, in `web/app.py` das Datum in `GUIDELINES_VERSION` hochsetzen –
dann muss jeder ihn beim nächsten Besuch erneut bestätigen. Wer wann bestätigt hat, steht in der
Admin-Übersicht bzw. in `portal.sqlite3` (Spalten `guidelines_version`, `guidelines_at`).

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
| Upload bricht bei großen Dateien ab | in Caddy `max_size` prüfen; `PORTAL_MAX_UPLOAD_MB` in `portal.env` |

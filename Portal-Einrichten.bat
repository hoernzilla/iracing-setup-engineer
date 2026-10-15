@echo off
rem Setup-Engineer Community-Portal - einmalige Einrichtung
rem Installiert die benoetigten Python-Pakete, laedt die Schrift herunter,
rem legt die Einstellungsdatei portal.env an (Server-IP wird automatisch eingetragen)
rem und gibt den Port in der Windows-Firewall frei.
rem Am besten mit Rechtsklick -> "Als Administrator ausfuehren" starten (fuer die Firewall-Freigabe).

setlocal
cd /d "%~dp0"

echo.
echo === Setup-Engineer Portal: Einrichtung ===
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo Python wurde nicht gefunden.
    echo Bitte Python 3.11 oder neuer installieren: https://www.python.org/downloads/
    echo Beim Installieren "Add python.exe to PATH" anhaken und danach diese Datei erneut starten.
    pause
    exit /b 1
)

echo [1/4] Python-Pakete installieren ...
python -m pip install --upgrade --quiet -r requirements-portal.txt
if errorlevel 1 (
    echo Fehler beim Installieren der Pakete. Internetverbindung pruefen und erneut starten.
    pause
    exit /b 1
)

echo [2/4] Schrift "Saira" herunterladen (wird vom eigenen Server ausgeliefert) ...
if not exist "src\setup_engineer\web\static\fonts" mkdir "src\setup_engineer\web\static\fonts"
if not exist "src\setup_engineer\web\static\fonts\Saira.ttf" (
    powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/google/fonts/raw/main/ofl/saira/Saira%%5Bwdth%%2Cwght%%5D.ttf' -OutFile 'src\setup_engineer\web\static\fonts\Saira.ttf'; exit 0 } catch { exit 1 }"
    if errorlevel 1 (
        echo    Schrift konnte nicht geladen werden - die Seite nutzt dann eine Ersatzschrift. Nicht schlimm.
    ) else (
        echo    Schrift geladen.
    )
) else (
    echo    Schrift ist schon vorhanden.
)

echo [3/4] Einstellungen ...
set "PYTHONPATH=%~dp0src"
set "NEU=0"
if not exist "portal.env" set "NEU=1"
python -m setup_engineer.web.einrichten
if errorlevel 1 (
    echo    Fehler beim Anlegen von portal.env.
    pause
    exit /b 1
)
if "%NEU%"=="1" (
    echo.
    echo    portal.env wird jetzt im Editor geoeffnet.
    echo    Bitte die Discord-Werte eintragen ^(Anleitung: docs\PORTAL.md^), speichern und schliessen.
    notepad "portal.env"
)

echo [4/4] Port in der Windows-Firewall freigeben ...
for /f %%p in ('python -m setup_engineer.web.einrichten --port') do set "PORT=%%p"
net session >nul 2>&1
if errorlevel 1 (
    echo    Uebersprungen: dafuer diese Datei mit Rechtsklick -^> "Als Administrator ausfuehren" starten.
) else (
    netsh advfirewall firewall delete rule name="Setup-Engineer Portal" >nul 2>&1
    netsh advfirewall firewall add rule name="Setup-Engineer Portal" dir=in action=allow protocol=TCP localport=%PORT% >nul
    if errorlevel 1 (
        echo    Firewall-Regel konnte nicht angelegt werden.
    ) else (
        echo    Port %PORT% ist freigegeben.
    )
)
echo    Hinweis: Hat der Hoster eine eigene Firewall im Kundenmenue, dort TCP-Port %PORT% ebenfalls freigeben.

echo.
echo Fertig. Zum Starten: Portal-Starten.bat
echo.
pause

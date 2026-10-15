@echo off
rem Setup-Engineer Community-Portal - einmalige Einrichtung
rem Installiert die benoetigten Python-Pakete, laedt die Schrift herunter
rem und legt die Einstellungsdatei portal.env an.

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

echo [1/3] Python-Pakete installieren ...
python -m pip install --upgrade --quiet -r requirements-portal.txt
if errorlevel 1 (
    echo Fehler beim Installieren der Pakete. Internetverbindung pruefen und erneut starten.
    pause
    exit /b 1
)

echo [2/3] Schrift "Saira" herunterladen (wird vom eigenen Server ausgeliefert) ...
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

echo [3/3] Einstellungen ...
if not exist "portal.env" (
    copy /y "portal.env.example" "portal.env" >nul
    echo    portal.env wurde angelegt und wird jetzt im Editor geoeffnet.
    echo    Bitte die Discord-Werte eintragen (Anleitung: docs\PORTAL.md), speichern und schliessen.
    notepad "portal.env"
) else (
    echo    portal.env ist schon vorhanden - bleibt unveraendert.
)

echo.
echo Fertig. Zum Starten: Portal-Starten.bat
echo.
pause

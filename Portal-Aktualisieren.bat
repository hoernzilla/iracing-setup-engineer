@echo off
rem Setup-Engineer Portal aktualisieren - mit einem Doppelklick (als Administrator).
rem Ablauf: neue ZIP suchen, Portal beenden, Sicherung anlegen, neuen Stand einspielen,
rem         Pakete pruefen, Portal starten, pruefen ob es antwortet - sonst Sicherung zurueckspielen.
rem portal.env und der Datenordner portal-data werden nie angefasst.
rem Die ZIP (SetupEngineer-Portal*.zip) neben diese Datei oder in den Download-Ordner legen.

setlocal EnableDelayedExpansion
rem Diese Datei wird beim Einspielen selbst ersetzt -> zuerst eine Kopie im TEMP-Ordner starten
if /i not "%~1"=="--kopie" (
    copy /y "%~f0" "%TEMP%\SE-Portal-Update.bat" >nul
    "%TEMP%\SE-Portal-Update.bat" --kopie "%~dp0"
    exit /b
)
set "ZIEL=%~2"
if "%ZIEL:~-1%"=="\" set "ZIEL=%ZIEL:~0,-1%"
cd /d "%ZIEL%"
title Setup-Engineer Portal aktualisieren
echo.
echo === Setup-Engineer Portal aktualisieren ===
echo Portal-Ordner: %ZIEL%
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo Bitte mit Rechtsklick -^> "Als Administrator ausfuehren" starten.
    goto :ende
)
if not exist "%ZIEL%\portal.env" (
    echo In diesem Ordner liegt kein eingerichtetes Portal ^(portal.env fehlt^).
    echo Diese Datei bitte in den Portal-Ordner legen, z. B. C:\SetupEngineer.
    goto :ende
)

rem ---------------------------------------------------------------- 1. ZIP suchen
set "ZIP="
for /f "delims=" %%z in ('powershell -NoProfile -Command "$d=@('%ZIEL%', (Join-Path $env:USERPROFILE 'Downloads')); Get-ChildItem -Path $d -Filter 'SetupEngineer-Portal*.zip' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName"') do set "ZIP=%%z"
if not defined ZIP (
    echo Keine SetupEngineer-Portal*.zip gefunden - weder hier noch im Download-Ordner.
    goto :ende
)
echo [1/6] Neuer Stand: %ZIP%

rem ---------------------------------------------------------------- 2. Portal beenden
echo [2/6] Portal beenden ...
schtasks /end /tn "Setup-Engineer Portal" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'Portal-Starten\.bat|setup_engineer\.web' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

rem ---------------------------------------------------------------- 3. Sicherung
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set "STAMP=%%t"
set "SICH=%ZIEL%-Sicherung-%STAMP%"
echo [3/6] Sicherung nach %SICH% ...
robocopy "%ZIEL%" "%SICH%" /E /XD portal-data __pycache__ /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo Sicherung fehlgeschlagen - Abbruch, nichts wurde veraendert.
    goto :starten
)

rem ---------------------------------------------------------------- 4. Einspielen
echo [4/6] Neuen Stand einspielen ...
set "TMPX=%TEMP%\SE-Portal-Neu"
if exist "%TMPX%" rmdir /s /q "%TMPX%"
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%TMPX%' -Force"
if not exist "%TMPX%\SetupEngineer\src" (
    echo Die ZIP hat nicht den erwarteten Inhalt - Abbruch, nichts wurde veraendert.
    goto :starten
)
rem Programmdateien ersetzen; geloeschte Dateien des alten Stands entfernen (keine Dateileichen),
rem portal.env, portal-data und Sicherungen bleiben unberuehrt.
robocopy "%TMPX%\SetupEngineer\src" "%ZIEL%\src" /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NP >nul
robocopy "%TMPX%\SetupEngineer" "%ZIEL%" /E /XD src portal-data /XF portal.env /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo Fehler beim Kopieren - spiele Sicherung zurueck.
    goto :zurueck
)
rmdir /s /q "%TMPX%"

rem ---------------------------------------------------------------- 5. Pakete und Einstellungen
echo [5/6] Pakete und Einstellungen pruefen ...
python -m pip install --quiet --disable-pip-version-check -r requirements-portal.txt
set "PYTHONPATH=%ZIEL%\src"
python -m setup_engineer.web.einrichten
for /f %%p in ('python -m setup_engineer.web.einrichten --port') do set "FWPORT=%%p"
netsh advfirewall firewall delete rule name="Setup-Engineer Portal" >nul 2>&1
netsh advfirewall firewall add rule name="Setup-Engineer Portal" dir=in action=allow protocol=TCP localport=!FWPORT! >nul

:starten
rem ---------------------------------------------------------------- 6. Starten und pruefen
echo [6/6] Portal starten ...
set "PORT=29630"
for /f "tokens=1,* delims==" %%a in ('findstr /b /c:"PORTAL_PORT=" "%ZIEL%\portal.env"') do if not "%%b"=="" set "PORT=%%b"
schtasks /query /tn "Setup-Engineer Portal" >nul 2>&1
if errorlevel 1 (
    start "Setup-Engineer Portal" "%ZIEL%\Portal-Starten.bat"
) else (
    schtasks /run /tn "Setup-Engineer Portal" >nul
)
powershell -NoProfile -Command "for($i=0;$i -lt 30;$i++){ try { $r=Invoke-RestMethod -Uri 'http://localhost:%PORT%/health' -TimeoutSec 2; Write-Host ('    laeuft, Version ' + $r.version); exit 0 } catch { Start-Sleep 1 } }; exit 1"
if errorlevel 1 (
    if defined RUECK (
        echo Auch der alte Stand startet nicht. Bitte Portal-Starten.bat ausfuehren und die Meldung ansehen.
        goto :ende
    )
    if not exist "%SICH%" goto :ende
    echo Das Portal antwortet nicht - spiele Sicherung zurueck.
    goto :zurueck
)
echo.
echo Fertig. Im Browser mit Strg+F5 neu laden:  http://localhost:%PORT%
echo Die Sicherung liegt in %SICH% und kann geloescht werden, wenn alles passt.
goto :ende

:zurueck
set "RUECK=1"
schtasks /end /tn "Setup-Engineer Portal" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'Portal-Starten\.bat|setup_engineer\.web' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
robocopy "%SICH%" "%ZIEL%" /MIR /XD portal-data /XF portal.env /NFL /NDL /NJH /NJS /NP >nul
echo Alter Stand ist wiederhergestellt.
goto :starten

:ende
echo.
pause

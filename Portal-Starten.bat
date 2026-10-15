@echo off
rem Setup-Engineer Community-Portal starten.
rem Das Fenster muss offen bleiben, solange das Portal laufen soll.
rem Beenden: dieses Fenster schliessen oder Strg+C druecken.

setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
title Setup-Engineer Portal

if not exist "portal.env" (
    echo portal.env fehlt - bitte zuerst Portal-Einrichten.bat ausfuehren.
    pause
    exit /b 1
)

echo Setup-Engineer Portal laeuft. Fenster offen lassen.
echo.
:loop
python -m setup_engineer.web
echo.
echo Das Portal wurde beendet. Neustart in 5 Sekunden - zum Abbrechen dieses Fenster schliessen.
ping -n 6 127.0.0.1 >nul
goto loop

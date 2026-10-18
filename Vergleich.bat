@echo off
rem iRacing Setup-Engineer - A/B-Vergleich
rem Benutzung:
rem   - EINE .ibt-Datei, wenn du waehrend der Session im Auto umgestellt und wieder zurueckgestellt hast (A-B-A)
rem   - oder DREI .ibt-Dateien gleichzeitig (Garagen-Test A, B, A - Reihenfolge egal, sortiert nach Aufnahmezeit)
rem Ergebnis: Bericht im Ordner "Berichte" neben der ersten Datei; der Test wird in der
rem Test-Historie gespeichert und fliesst in kuenftige Empfehlungen ein.

setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src"

where python >nul 2>nul
if errorlevel 1 (
    echo Python wurde nicht gefunden. Bitte Python 3.11 oder neuer installieren:
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)
python -c "import numpy, yaml, scipy" >nul 2>nul
if errorlevel 1 python -m pip install --quiet numpy pyyaml scipy

if "%~1"=="" (
    echo Bitte eine .ibt-Datei (A-B-A im Auto) oder drei .ibt-Dateien (Garagen-Test) auf diese Datei ziehen.
    pause
    exit /b 0
)

python -m setup_engineer compare %* --save --out "%~dp1Berichte"
echo.
pause

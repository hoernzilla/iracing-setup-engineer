@echo off
rem iRacing Setup-Engineer - IBT-Dateien analysieren
rem Benutzung: eine oder mehrere .ibt-Dateien per Drag & Drop auf diese Datei ziehen.
rem Die Berichte landen im Unterordner "Berichte" neben den IBT-Dateien.

setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src"

where python >nul 2>nul
if errorlevel 1 (
    echo Python wurde nicht gefunden. Bitte Python 3.11 oder neuer installieren:
    echo https://www.python.org/downloads/
    echo Beim Installieren "Add python.exe to PATH" anhaken.
    pause
    exit /b 1
)

python -c "import numpy, yaml, scipy" >nul 2>nul
if errorlevel 1 (
    echo Benoetigte Pakete werden einmalig installiert ...
    python -m pip install --quiet numpy pyyaml scipy
)

if "%~1"=="" (
    echo Bitte eine oder mehrere .ibt-Dateien auf diese Datei ziehen.
    echo Die Dateien liegen normalerweise unter Dokumente\iRacing\telemetry
    pause
    exit /b 0
)

:loop
if "%~1"=="" goto done
echo.
echo Analysiere %~nx1 ...
python -m setup_engineer analyze "%~1" --out "%~dp1Berichte"
shift
goto loop

:done
echo.
echo Fertig. Die Berichte liegen im Ordner "Berichte" neben den IBT-Dateien.
pause

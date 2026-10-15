@echo off
rem Richtet ein, dass das Portal beim Hochfahren des Servers automatisch startet
rem (Windows-Aufgabenplanung). Rechtsklick -> "Als Administrator ausfuehren".
rem Wieder abschalten: in einer Admin-Eingabeaufforderung  Portal-Autostart.bat entfernen
rem Voraussetzung: Python wurde "fuer alle Benutzer" installiert (der Autostart laeuft als SYSTEM).

setlocal
cd /d "%~dp0"

if /i "%~1"=="entfernen" (
    schtasks /delete /tn "Setup-Engineer Portal" /f
    echo Autostart entfernt.
    pause
    exit /b 0
)

net session >nul 2>&1
if errorlevel 1 (
    echo Bitte mit Rechtsklick -^> "Als Administrator ausfuehren" starten.
    pause
    exit /b 1
)

schtasks /create /tn "Setup-Engineer Portal" /tr "\"%~dp0Portal-Starten.bat\"" /sc onstart /ru SYSTEM /rl HIGHEST /f
if errorlevel 1 (
    echo Autostart konnte nicht eingerichtet werden.
) else (
    echo Autostart eingerichtet: Das Portal startet ab jetzt bei jedem Hochfahren automatisch.
    echo Jetzt sofort starten? Dann Portal-Starten.bat ausfuehren oder den Server neu starten.
)
pause

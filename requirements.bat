@echo off
REM Installiert alles, was SoundControl zum Starten braucht.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python wurde nicht gefunden.
    echo Bitte Python von https://www.python.org/downloads/ installieren
    echo und dabei den Haken bei "Add Python to PATH" setzen.
    echo Danach diese Datei erneut starten.
    pause
    exit /b 1
)

echo Installiere benoetigte Pakete ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Fehler bei der Installation.
    pause
    exit /b 1
)

echo.
echo Fertig! Jetzt kannst du start.bat doppelklicken.
pause

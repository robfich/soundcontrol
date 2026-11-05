@echo off
REM Baut aus soundcontrol.py eine einzelne SoundControl.exe (Ordner "dist").
cd /d "%~dp0"

echo [1/2] Installiere benoetigte Pakete ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fehler

echo [2/2] Erzeuge EXE ...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name SoundControl soundcontrol.py
if errorlevel 1 goto fehler

echo.
echo Fertig: %~dp0dist\SoundControl.exe
pause
exit /b 0

:fehler
echo.
echo Es ist ein Fehler aufgetreten. Ist Python installiert und im PATH?
pause
exit /b 1

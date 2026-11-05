@echo off
REM Startet SoundControl ohne Konsolenfenster.
cd /d "%~dp0"
start "" pythonw soundcontrol.py

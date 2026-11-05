# SoundControl

Einfache Soundsteuerung für Windows – alles in **einem Fenster**, ohne Scrollen:

- **Ausgabe**: alle aktiven Lautsprecher/Kopfhörer werden als Liste angezeigt.
  Ein Klick auf ein Gerät macht es zum Standardgerät (grün = aktiv).
  Darüber: Lautstärke-Regler und „Stumm“ für das aktive Ausgabegerät.
- **Eingabe**: dasselbe für Mikrofone.
- **Anwendungen**: jede Anwendung, die gerade Audio nutzt, mit eigenem
  Lautstärke-Regler und „Stumm“-Häkchen (auf allen Ausgabegeräten).

Das Fenster aktualisiert sich automatisch alle 1,5 Sekunden (neue Geräte,
neu gestartete Programme, Änderungen aus dem Windows-Mixer). Regler lassen sich
auch mit dem Mausrad bedienen. Optional: „Immer im Vordergrund“.

## Starten

1. Python 3.8+ für Windows installieren (Haken bei „Add Python to PATH“ setzen).
2. Abhängigkeiten installieren:
   ```
   pip install -r requirements.txt
   ```
3. `start.bat` doppelklicken (oder `python soundcontrol.py`).

## EXE erzeugen

`build_exe.bat` doppelklicken. Danach liegt die fertige Datei unter
`dist\SoundControl.exe` – diese läuft auch auf PCs ohne Python.

## Hinweise

- Das Umschalten des Standardgeräts nutzt die Windows-Schnittstelle
  `IPolicyConfig` und setzt das Gerät für alle Rollen (Standard, Multimedia,
  Kommunikation).
- Anwendungen werden nach Programmname zusammengefasst (z. B. alle
  Chrome-Tabs = ein Regler).
- `python soundcontrol.py --demo` zeigt die Oberfläche mit Beispieldaten
  (funktioniert auch ohne Windows).

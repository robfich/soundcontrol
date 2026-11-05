"""
SoundControl - einfache Soundsteuerung für Windows.

Ein einziges Fenster (ohne Scrollen) mit:
  * allen Ausgabegeraeten  -> Klick auf ein Gerät macht es zum Standardgerät
  * allen Eingabegeräten  -> Klick auf ein Gerät macht es zum Standardgerät
  * Lautstärke + Stumm für das aktuelle Ausgabe- und Eingabegerät
  * Lautstärke + Stumm für jede Anwendung, die gerade Audio nutzt

Benötigt: Windows, Python 3.8+, pycaw, comtypes, psutil, pystray, Pillow
    pip install -r requirements.txt

Start:  python soundcontrol.py
Direkt im Infobereich (Tray) starten:  python soundcontrol.py --minimiert
Demo ohne Windows (nur Oberfläche ansehen):  python soundcontrol.py --demo

Tray-Icon (benötigt pystray + Pillow): Linksklick öffnet/versteckt das Fenster,
Rechtsklick zeigt ein Menü zum schnellen Umschalten und Stummschalten.
Minimieren oder Schließen (X) schickt das Fenster in den Tray, "Beenden" im
Tray-Menü beendet das Programm.
"""

import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

REFRESH_MS = 1500        # wie oft Geräte/Anwendungen neu eingelesen werden
APP_COLUMNS = 2          # Spalten für Anwendungen (bei mehr als 8 Anwendungen automatisch 3)

# Konstanten der Windows Core Audio API
E_RENDER, E_CAPTURE = 0, 1                  # EDataFlow: Ausgabe / Eingabe
E_CONSOLE, E_MULTIMEDIA, E_COMMUNICATIONS = 0, 1, 2   # ERole
DEVICE_STATE_ACTIVE = 0x1
SESSION_STATE_EXPIRED = 2


# ---------------------------------------------------------------------------
# Datenobjekte, die die Oberfläche kennt
# ---------------------------------------------------------------------------
class Device:
    def __init__(self, dev_id, name, is_default, volume, muted):
        self.id = dev_id
        self.name = name
        self.is_default = is_default
        self.volume = volume      # 0..100
        self.muted = muted


class App:
    def __init__(self, key, name, volume, muted):
        self.key = key            # eindeutiger Schlüssel (Prozessname)
        self.name = name
        self.volume = volume      # 0..100
        self.muted = muted


# ---------------------------------------------------------------------------
# Windows-Backend (pycaw / comtypes)
# ---------------------------------------------------------------------------
class WindowsAudioBackend:
    def __init__(self):
        import comtypes
        from ctypes import HRESULT, POINTER, cast
        from ctypes.wintypes import DWORD, LPCWSTR
        from comtypes import COMMETHOD, GUID, IUnknown
        from pycaw.pycaw import (
            AudioUtilities,
            IAudioEndpointVolume,
            IAudioSessionControl2,
            ISimpleAudioVolume,
        )
        import psutil

        self._comtypes = comtypes
        self._cast = cast
        self._POINTER = POINTER
        self._AudioUtilities = AudioUtilities
        self._IAudioEndpointVolume = IAudioEndpointVolume
        self._IAudioSessionControl2 = IAudioSessionControl2
        self._ISimpleAudioVolume = ISimpleAudioVolume
        self._psutil = psutil

        # Undokumentiertes, aber seit Windows 7 stabiles Interface zum Setzen
        # des Standard-Audiogeraets (wird u.a. auch von SoundSwitch genutzt).
        class IPolicyConfig(IUnknown):
            _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
            _methods_ = [COMMETHOD([], HRESULT, "Unused%d" % i) for i in range(1, 11)] + [
                COMMETHOD([], HRESULT, "SetDefaultEndpoint",
                          (["in"], LPCWSTR, "pwstrDeviceId"),
                          (["in"], DWORD, "role")),
            ]

        self._IPolicyConfig = IPolicyConfig
        self._CLSID_PolicyConfigClient = GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}")

        # Cache: device id -> IMMDevice / Endpoint-Volume, app key -> Liste von ISimpleAudioVolume
        self._devices = {}
        self._endpoint_volumes = {}
        self._app_volumes = {}
        self._name_cache = {}

    # -- Hilfsfunktionen ----------------------------------------------------
    def _enumerator(self):
        return self._AudioUtilities.GetDeviceEnumerator()

    def _default_id(self, enumerator, flow):
        try:
            return enumerator.GetDefaultAudioEndpoint(flow, E_MULTIMEDIA).GetId()
        except Exception:
            return None

    def _device_name(self, dev, dev_id):
        name = self._name_cache.get(dev_id)
        if name is None:
            try:
                name = self._AudioUtilities.CreateDevice(dev).FriendlyName
            except Exception:
                name = None
            name = name or dev_id
            self._name_cache[dev_id] = name
        return name

    def _endpoint_volume(self, dev_id):
        vol = self._endpoint_volumes.get(dev_id)
        if vol is None:
            dev = self._devices[dev_id]
            iface = dev.Activate(self._IAudioEndpointVolume._iid_,
                                 self._comtypes.CLSCTX_ALL, None)
            vol = self._cast(iface, self._POINTER(self._IAudioEndpointVolume))
            self._endpoint_volumes[dev_id] = vol
        return vol

    def _active_devices(self, enumerator, flow):
        coll = enumerator.EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE)
        result = []
        for i in range(coll.GetCount()):
            dev = coll.Item(i)
            dev_id = dev.GetId()
            self._devices[dev_id] = dev
            result.append((dev_id, dev))
        return result

    # -- Geräte ------------------------------------------------------------
    def list_devices(self, flow):
        enumerator = self._enumerator()
        default_id = self._default_id(enumerator, flow)
        devices = []
        for dev_id, dev in self._active_devices(enumerator, flow):
            volume, muted = 0, False
            try:
                ev = self._endpoint_volume(dev_id)
                volume = round(ev.GetMasterVolumeLevelScalar() * 100)
                muted = bool(ev.GetMute())
            except Exception:
                self._endpoint_volumes.pop(dev_id, None)
            devices.append(Device(dev_id, self._device_name(dev, dev_id),
                                  dev_id == default_id, volume, muted))
        devices.sort(key=lambda d: d.name.lower())
        return devices

    def set_default_device(self, dev_id):
        policy = self._comtypes.CoCreateInstance(
            self._CLSID_PolicyConfigClient, self._IPolicyConfig, self._comtypes.CLSCTX_ALL)
        for role in (E_CONSOLE, E_MULTIMEDIA, E_COMMUNICATIONS):
            policy.SetDefaultEndpoint(dev_id, role)

    def set_device_volume(self, dev_id, volume):
        self._endpoint_volume(dev_id).SetMasterVolumeLevelScalar(volume / 100.0, None)

    def set_device_mute(self, dev_id, muted):
        self._endpoint_volume(dev_id).SetMute(1 if muted else 0, None)

    # -- Anwendungen --------------------------------------------------------
    def _process_name(self, pid):
        if pid == 0:
            return "systemsounds", "Systemsounds"
        try:
            exe = self._psutil.Process(pid).name()
        except Exception:
            exe = "pid %d" % pid
        key = exe.lower()
        name = exe[:-4] if key.endswith(".exe") else exe
        return key, name

    def list_apps(self):
        """Alle Audio-Sitzungen auf allen aktiven Ausgabegeraeten, nach Programm gruppiert."""
        enumerator = self._enumerator()
        groups = {}
        for dev_id, dev in self._active_devices(enumerator, E_RENDER):
            try:
                mgr = self._AudioUtilities.CreateDevice(dev).AudioSessionManager
                sess_enum = mgr.GetSessionEnumerator()
                count = sess_enum.GetCount()
            except Exception:
                continue
            for i in range(count):
                try:
                    ctl = sess_enum.GetSession(i)
                    if ctl is None:
                        continue
                    ctl2 = ctl.QueryInterface(self._IAudioSessionControl2)
                    if ctl2.GetState() == SESSION_STATE_EXPIRED:
                        continue
                    pid = ctl2.GetProcessId()
                    vol = ctl2.QueryInterface(self._ISimpleAudioVolume)
                except Exception:
                    continue
                key, name = self._process_name(pid)
                groups.setdefault(key, (name, []))[1].append(vol)

        self._app_volumes = {k: v[1] for k, v in groups.items()}
        apps = []
        for key, (name, vols) in groups.items():
            try:
                volume = round(vols[0].GetMasterVolume() * 100)
                muted = all(bool(v.GetMute()) for v in vols)
            except Exception:
                volume, muted = 0, False
            apps.append(App(key, name, volume, muted))
        apps.sort(key=lambda a: (a.key != "systemsounds", a.name.lower()))
        return apps

    def set_app_volume(self, key, volume):
        for v in self._app_volumes.get(key, []):
            try:
                v.SetMasterVolume(volume / 100.0, None)
            except Exception:
                pass

    def set_app_mute(self, key, muted):
        for v in self._app_volumes.get(key, []):
            try:
                v.SetMute(1 if muted else 0, None)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Demo-Backend (zum Ausprobieren der Oberfläche ohne Windows)
# ---------------------------------------------------------------------------
class DemoAudioBackend:
    def __init__(self):
        self._dev = {
            E_RENDER: [Device("o1", "Lautsprecher (Realtek High Definition Audio)", True, 45, False),
                       Device("o2", "Kopfhörer (USB Headset)", False, 70, False),
                       Device("o3", "Monitor (NVIDIA High Definition Audio)", False, 100, False)],
            E_CAPTURE: [Device("i1", "Mikrofon (USB Headset)", True, 80, False),
                        Device("i2", "Mikrofon (Realtek High Definition Audio)", False, 60, True)],
        }
        self._apps = [App("systemsounds", "Systemsounds", 50, False),
                      App("chrome.exe", "chrome", 100, False),
                      App("discord.exe", "Discord", 80, False),
                      App("spotify.exe", "Spotify", 35, True),
                      App("teams.exe", "ms-teams", 90, False)]

    def _find(self, dev_id):
        for devs in self._dev.values():
            for d in devs:
                if d.id == dev_id:
                    return devs, d
        raise KeyError(dev_id)

    def list_devices(self, flow):
        return [Device(d.id, d.name, d.is_default, d.volume, d.muted) for d in self._dev[flow]]

    def set_default_device(self, dev_id):
        devs, dev = self._find(dev_id)
        for d in devs:
            d.is_default = d is dev

    def set_device_volume(self, dev_id, volume):
        self._find(dev_id)[1].volume = volume

    def set_device_mute(self, dev_id, muted):
        self._find(dev_id)[1].muted = muted

    def list_apps(self):
        return [App(a.key, a.name, a.volume, a.muted) for a in self._apps]

    def set_app_volume(self, key, volume):
        for a in self._apps:
            if a.key == key:
                a.volume = volume

    def set_app_mute(self, key, muted):
        for a in self._apps:
            if a.key == key:
                a.muted = muted


# ---------------------------------------------------------------------------
# Oberfläche
# ---------------------------------------------------------------------------
class VolumeRow:
    """Eine Zeile: [Name] [Stumm] [Schieberegler 0-100]."""

    def __init__(self, parent, row, label, on_volume, on_mute, label_width=18, length=220):
        self._on_volume = on_volume
        self._on_mute = on_mute
        self._busy = False        # True, während der Wert programmatisch gesetzt wird
        self.dragging = False     # True, während die Maus den Regler haelt

        self.label = ttk.Label(parent, text=label, width=label_width, anchor="w")
        self.label.grid(row=row, column=0, sticky="w", padx=(0, 4))

        self.mute_var = tk.BooleanVar()
        self.mute_btn = ttk.Checkbutton(parent, text="Stumm", variable=self.mute_var,
                                        command=self._mute_changed)
        self.mute_btn.grid(row=row, column=1, sticky="w", padx=4)

        self.scale = tk.Scale(parent, from_=0, to=100, orient="horizontal", length=length,
                              showvalue=True, command=self._volume_changed,
                              highlightthickness=0, sliderlength=18, width=12)
        self.scale.grid(row=row, column=2, sticky="we", padx=4)
        self.scale.bind("<ButtonPress-1>", lambda e: setattr(self, "dragging", True))
        self.scale.bind("<ButtonRelease-1>", lambda e: setattr(self, "dragging", False))
        self.scale.bind("<MouseWheel>", self._wheel)

    def _wheel(self, event):
        step = 2 if event.delta > 0 else -2
        self.scale.set(max(0, min(100, int(self.scale.get()) + step)))

    def _volume_changed(self, value):
        if not self._busy:
            self._on_volume(int(float(value)))

    def _mute_changed(self):
        if not self._busy:
            self._on_mute(self.mute_var.get())

    def update(self, volume, muted, label=None):
        self._busy = True
        try:
            if label is not None:
                self.label.configure(text=label)
            if not self.dragging and int(self.scale.get()) != volume:
                self.scale.set(volume)
            if self.mute_var.get() != muted:
                self.mute_var.set(muted)
        finally:
            self._busy = False

    def set_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.scale.configure(state=state)
        self.mute_btn.configure(state=state)


class DeviceSection:
    """Ein Block für Ausgabe oder Eingabe: Lautstärke des Standardgeräts + Geräteliste."""

    def __init__(self, app, parent, title, flow):
        self.app = app
        self.flow = flow
        self.frame = ttk.LabelFrame(parent, text=title, padding=8)
        self.default_id = None
        self.default_name = ""
        self.default_volume = 0
        self.muted = False
        self.devices = []          # [(id, name)] - wird auch vom Tray-Menü gelesen
        self._signature = None

        top = ttk.Frame(self.frame)
        top.pack(fill="x")
        self.volume_row = VolumeRow(top, 0, "Lautstärke", self._set_volume, self._set_mute,
                                    label_width=11, length=240)

        ttk.Label(self.frame, text="Gerät anklicken = als Standard verwenden:").pack(
            anchor="w", pady=(8, 2))
        self.list_frame = ttk.Frame(self.frame)
        self.list_frame.pack(fill="x")
        self.selected = tk.StringVar()
        self.buttons = {}

    def _set_volume(self, v):
        if self.default_id:
            self.app.safe(self.app.backend.set_device_volume, self.default_id, v)

    def _set_mute(self, m):
        if self.default_id:
            self.app.safe(self.app.backend.set_device_mute, self.default_id, m)

    def toggle_mute(self):
        if self.default_id:
            self._set_mute(not self.muted)
            self.app.refresh(reschedule=False)

    def _choose(self, dev_id):
        if self.app.safe(self.app.backend.set_default_device, dev_id) is not False:
            self.app.status("Standardgerät geändert: " + self.buttons[dev_id].cget("text").strip())
        self.app.refresh(reschedule=False)

    def show(self, devices):
        self.devices = [(d.id, d.name) for d in devices]
        signature = tuple((d.id, d.name) for d in devices)
        if signature != self._signature:
            self._signature = signature
            for w in self.list_frame.winfo_children():
                w.destroy()
            self.buttons = {}
            if not devices:
                ttk.Label(self.list_frame, text="(keine aktiven Geräte gefunden)").pack(anchor="w")
            for d in devices:
                b = tk.Radiobutton(self.list_frame, text="  " + d.name, value=d.id,
                                   variable=self.selected, indicatoron=False, anchor="w",
                                   selectcolor="#b9e6b9", padx=6, pady=3, width=46,
                                   command=lambda i=d.id: self._choose(i))
                b.pack(fill="x", pady=1)
                self.buttons[d.id] = b

        default = next((d for d in devices if d.is_default), None)
        self.default_id = default.id if default else None
        self.default_name = default.name if default else ""
        self.default_volume = default.volume if default else 0
        self.muted = default.muted if default else False
        self.selected.set(self.default_id or "")
        for dev_id, b in self.buttons.items():
            b.configure(font=self.app.bold_font if dev_id == self.default_id else self.app.normal_font)
        if default:
            self.volume_row.set_enabled(True)
            self.volume_row.update(default.volume, default.muted)
        else:
            self.volume_row.set_enabled(False)


class AppsSection:
    def __init__(self, app, parent):
        self.app = app
        self.frame = ttk.LabelFrame(parent, text="Anwendungen", padding=8)
        self.inner = ttk.Frame(self.frame)
        self.inner.pack(fill="x")
        self.rows = {}
        self._signature = None

    def show(self, apps):
        signature = tuple((a.key, a.name) for a in apps)
        if signature != self._signature:
            self._signature = signature
            for w in self.inner.winfo_children():
                w.destroy()
            self.rows = {}
            if not apps:
                ttk.Label(self.inner, text="(keine Anwendung gibt gerade Audio aus)").grid(
                    row=0, column=0, sticky="w")
            cols = APP_COLUMNS if len(apps) <= 8 else APP_COLUMNS + 1
            rows_per_col = (len(apps) + cols - 1) // cols if apps else 0
            for idx, a in enumerate(apps):
                col, row = divmod(idx, rows_per_col)
                cell = ttk.Frame(self.inner)
                cell.grid(row=row, column=col, sticky="w", padx=(0 if col == 0 else 24, 0))
                self.rows[a.key] = VolumeRow(
                    cell, 0, a.name,
                    lambda v, k=a.key: self.app.safe(self.app.backend.set_app_volume, k, v),
                    lambda m, k=a.key: self.app.safe(self.app.backend.set_app_mute, k, m),
                    label_width=18, length=200)
        for a in apps:
            self.rows[a.key].update(a.volume, a.muted)


class TrayIcon:
    """Symbol im Infobereich (pystray). Läuft in eigenem Thread; alle Aktionen
    werden über eine Queue an den Tk-Hauptthread übergeben."""

    def __init__(self, app):
        self.app = app
        self.queue = queue.Queue()
        self.icon = None
        self._menu_signature = None
        self._title = None
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception:
            return   # ohne pystray/Pillow läuft das Programm einfach ohne Tray-Icon

        M, I = pystray.Menu, pystray.MenuItem
        self._M, self._I = M, I
        menu = M(
            I("SoundControl öffnen / verstecken", self._action(app.toggle_window), default=True),
            I("Ausgabegerät", M(lambda: self._device_items(app.output))),
            I("Eingabegerät", M(lambda: self._device_items(app.input))),
            M.SEPARATOR,
            I("Ausgabe stumm", self._action(app.output.toggle_mute),
              checked=lambda item: app.output.muted),
            I("Mikrofon stumm", self._action(app.input.toggle_mute),
              checked=lambda item: app.input.muted),
            M.SEPARATOR,
            I("Beenden", self._action(app.quit)),
        )
        try:
            self.icon = pystray.Icon("SoundControl", self._make_image(Image, ImageDraw),
                                     "SoundControl", menu)
            # eigener Hintergrund-Thread (unter Windows unproblematisch)
            threading.Thread(target=self.icon.run, daemon=True).start()
        except Exception:
            self.icon = None

    @staticmethod
    def _make_image(Image, ImageDraw):
        """Einfaches Lautsprecher-Symbol zeichnen."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, 63, 63), radius=14, fill=(40, 120, 70, 255))
        d.polygon([(12, 25), (22, 25), (34, 13), (34, 51), (22, 39), (12, 39)],
                  fill=(255, 255, 255, 255))
        d.arc((26, 20, 46, 44), -50, 50, fill=(255, 255, 255, 255), width=4)
        d.arc((26, 11, 56, 53), -50, 50, fill=(255, 255, 255, 255), width=4)
        return img

    def _action(self, func, *args):
        def run():
            self.queue.put((func, args))
        return run

    def _device_items(self, section):
        items = []
        for dev_id, name in section.devices:
            items.append(self._I(
                name, self._action(section._choose, dev_id), radio=True,
                checked=(lambda i: lambda item: section.default_id == i)(dev_id)))
        if not items:
            items.append(self._I("(keine Geräte)", None, enabled=False))
        return items

    def process_queue(self):
        while True:
            try:
                func, args = self.queue.get_nowait()
            except queue.Empty:
                return
            func(*args)

    def update(self):
        """Tooltip und Menü an den aktuellen Zustand anpassen."""
        if not self.icon:
            return
        out = self.app.output
        title = "SoundControl\n%s: %s" % (
            out.default_name or "kein Ausgabegerät",
            "stumm" if out.muted else "%d %%" % out.default_volume)
        title = title[:120]
        sig = (tuple(out.devices), out.default_id, out.muted,
               tuple(self.app.input.devices), self.app.input.default_id, self.app.input.muted)
        try:
            if title != self._title:
                self._title = title
                self.icon.title = title
            if sig != self._menu_signature:
                self._menu_signature = sig
                self.icon.update_menu()
        except Exception:
            pass

    def notify(self, text):
        if self.icon:
            try:
                self.icon.notify(text, "SoundControl")
            except Exception:
                pass

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass


class SoundControlApp:
    def __init__(self, root, backend, start_hidden=False):
        self.root = root
        self.backend = backend
        self._after_id = None
        self._tray_hint_shown = False

        root.title("SoundControl")
        root.resizable(False, False)
        try:
            ttk.Style().theme_use("vista" if sys.platform == "win32" else "clam")
        except tk.TclError:
            pass

        import tkinter.font as tkfont
        self.normal_font = tkfont.nametofont("TkDefaultFont").copy()
        self.bold_font = self.normal_font.copy()
        self.bold_font.configure(weight="bold")

        main = ttk.Frame(root, padding=10)
        main.pack(fill="both", expand=True)

        self.output = DeviceSection(self, main, "Ausgabe (Lautsprecher / Kopfhörer)", E_RENDER)
        self.input = DeviceSection(self, main, "Eingabe (Mikrofone)", E_CAPTURE)
        self.apps = AppsSection(self, main)

        self.output.frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.input.frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.apps.frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        main.columnconfigure(0, weight=1, uniform="half")
        main.columnconfigure(1, weight=1, uniform="half")

        bottom = ttk.Frame(main)
        bottom.grid(row=2, column=0, columnspan=2, sticky="we", pady=(8, 0))
        self.status_var = tk.StringVar(value="Bereit.")
        ttk.Label(bottom, textvariable=self.status_var, foreground="#555").pack(side="left")
        self.topmost = tk.BooleanVar(value=False)
        ttk.Checkbutton(bottom, text="Immer im Vordergrund", variable=self.topmost,
                        command=lambda: root.attributes("-topmost", self.topmost.get())
                        ).pack(side="right")
        ttk.Button(bottom, text="Aktualisieren",
                   command=lambda: self.refresh(reschedule=False)).pack(side="right", padx=8)

        self.tray = TrayIcon(self)
        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        root.bind("<Unmap>", self._on_unmap)

        self.refresh()
        self._poll_tray()
        if start_hidden and self.tray.icon:
            root.withdraw()

    # -- Fenster / Tray -------------------------------------------------------
    def _poll_tray(self):
        self.tray.process_queue()
        self.root.after(100, self._poll_tray)

    def _on_unmap(self, event):
        # Minimieren -> statt Taskleiste in den Tray
        if event.widget is self.root and self.tray.icon and self.root.state() == "iconic":
            self.root.after(0, self.hide_to_tray)

    def hide_to_tray(self):
        if not self.tray.icon:      # kein Tray verfügbar -> X beendet wie gewohnt
            self.quit()
            return
        self.root.withdraw()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.notify("SoundControl läuft im Infobereich weiter. "
                             "Klick auf das Symbol öffnet das Fenster.")

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.refresh(reschedule=False)

    def toggle_window(self):
        if self.root.state() in ("withdrawn", "iconic"):
            self.show_window()
        else:
            self.root.withdraw()

    def quit(self):
        self.tray.stop()
        self.root.destroy()

    def status(self, text):
        self.status_var.set(text)

    def safe(self, func, *args):
        try:
            return func(*args)
        except Exception as exc:   # COM-Fehler sollen die Oberfläche nicht beenden
            self.status("Fehler: %s" % exc)
            return False

    def refresh(self, reschedule=True):
        try:
            self.output.show(self.backend.list_devices(E_RENDER))
            self.input.show(self.backend.list_devices(E_CAPTURE))
            if self.root.state() != "withdrawn":   # Anwendungen nur bei sichtbarem Fenster
                self.apps.show(self.backend.list_apps())
        except Exception as exc:
            self.status("Fehler beim Einlesen: %s" % exc)
        if hasattr(self, "tray"):
            self.tray.update()
        if reschedule:
            self._after_id = self.root.after(REFRESH_MS, self.refresh)


def main():
    demo = "--demo" in sys.argv
    if not demo and sys.platform != "win32":
        print("SoundControl läuft nur unter Windows. Zum Ansehen der Oberfläche: --demo")
        sys.exit(1)
    backend = DemoAudioBackend() if demo else WindowsAudioBackend()
    root = tk.Tk()
    SoundControlApp(root, backend, start_hidden="--minimiert" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    main()

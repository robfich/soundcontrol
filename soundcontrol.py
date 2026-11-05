"""
SoundControl - einfache Soundsteuerung für Windows.

Ein einziges Fenster (ohne Scrollen) mit:
  * allen Ausgabegeräten  -> Klick auf ein Gerät macht es zum Standardgerät
  * allen Eingabegeräten  -> Klick auf ein Gerät macht es zum Standardgerät
  * Lautstärke + Stumm für das aktuelle Ausgabe- und Eingabegerät
  * Lautstärke + Stumm für jede Anwendung, die gerade Audio nutzt

Design: Zephyr (zephyr_tk.py im selben Ordner), hell/dunkel + Farbpaletten.

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

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zephyr_tk as z   # Zephyr-Design (Datei liegt neben diesem Programm)

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
# Oberfläche im Zephyr-Design (zephyr_tk.py liegt im selben Ordner)
# ---------------------------------------------------------------------------
# Zusätzliche Symbole (Segoe MDL2 Assets, Ersatzzeichen ohne diese Schrift)
z.ICONS.setdefault("volume", (chr(0xE767), "♪"))
z.ICONS.setdefault("mute", (chr(0xE74F), "×"))
z.ICONS.setdefault("speaker", (chr(0xE7F5), "♪"))
z.ICONS.setdefault("mic", (chr(0xE720), "●"))
z.ICONS.setdefault("pin", (chr(0xE718), "⊤"))


class VolumeRow:
    """Eine Zeile im Zephyr-Stil: [Name] [Regler] [45 %] [Stumm]."""

    def __init__(self, ui, parent, name, on_volume, on_mute, name_width=14, length=210):
        self.ui = ui
        self._on_volume = on_volume
        self._on_mute = on_mute
        self._busy = False        # True, während der Wert programmatisch gesetzt wird
        self.dragging = False     # True, während die Maus den Regler hält
        self.muted = False
        self.enabled = True
        t, bg = ui.t, parent.cget("bg")

        self.frame = tk.Frame(parent, bg=bg)
        self.name = tk.Label(self.frame, text=name, font=ui.f["btn"], bg=bg, fg=t["text"],
                             width=name_width, anchor="w")
        self.name.pack(side="left")
        self.scale = ttk.Scale(self.frame, from_=0, to=100, orient="horizontal",
                               length=ui.px(length), command=self._volume_changed)
        self.scale.pack(side="left", padx=(ui.px(6), ui.px(8)))
        self.value = tk.Label(self.frame, text="0 %", font=ui.f["small"], bg=bg, fg=t["dim"],
                              width=5, anchor="e")
        self.value.pack(side="left")
        self.mute = tk.Label(self.frame, font=ui.f["small"], padx=ui.px(10), pady=ui.px(3),
                             cursor="hand2")
        self.mute.pack(side="left", padx=(ui.px(10), 0))
        self.mute.bind("<ButtonRelease-1>", lambda e: self.enabled and self._on_mute(not self.muted))
        self.mute.bind("<Enter>", lambda e: not self.muted and self.enabled
                       and self.mute.configure(bg=t["hover"]))
        self.mute.bind("<Leave>", lambda e: self._paint_mute())
        self.scale.bind("<ButtonPress-1>", lambda e: setattr(self, "dragging", True))
        self.scale.bind("<ButtonRelease-1>", lambda e: setattr(self, "dragging", False))
        for w in (self.scale, self.name, self.value):
            w.bind("<MouseWheel>", self._wheel)
        self._paint_mute()

    def _paint_mute(self):
        t, ui = self.ui.t, self.ui
        if self.muted:   # Stumm = Akzent (rot), wie ein gewählter Chip
            self.mute.configure(text=ui.icon("mute") + "  Stumm", bg=t["accent"], fg=t["on_accent"])
        else:
            self.mute.configure(text=ui.icon("volume") + "  Stumm", bg=t["card2"],
                                fg=t["dim"] if self.enabled else t["line"])

    def _wheel(self, event):
        if self.enabled:
            step = 2 if event.delta > 0 else -2
            self.scale.set(max(0, min(100, round(float(self.scale.get())) + step)))

    def _volume_changed(self, value):
        v = round(float(value))
        self.value.configure(text="%d %%" % v)
        if not self._busy and self.enabled:
            self._on_volume(v)

    def update(self, volume, muted):
        self._busy = True
        try:
            if not self.dragging and round(float(self.scale.get())) != volume:
                self.scale.set(volume)
            self.value.configure(text="%d %%" % round(float(self.scale.get())))
            if muted != self.muted:
                self.muted = muted
                self._paint_mute()
        finally:
            self._busy = False

    def set_enabled(self, enabled):
        if enabled != self.enabled:
            self.enabled = enabled
            self.scale.state(["!disabled"] if enabled else ["disabled"])
            self._paint_mute()


class DeviceSection:
    """Karte für Ausgabe oder Eingabe. Der Zustand bleibt erhalten, die Widgets werden bei
    einem Designwechsel neu gebaut (build)."""

    def __init__(self, app, flow, title, hint, icon):
        self.app = app
        self.flow = flow
        self.title, self.hint, self.icon = title, hint, icon
        self.default_id = None
        self.default_name = ""
        self.default_volume = 0
        self.muted = False
        self.devices = []          # [(id, name)] - wird auch vom Tray-Menü gelesen

    def build(self, parent):
        ui = self.app.ui
        body = ui.card(parent, self.title, self.hint, icon=self.icon)
        self.volume_row = VolumeRow(ui, body, "Lautstärke", self._set_volume, self._set_mute,
                                    name_width=10, length=200)
        self.volume_row.frame.pack(fill="x")
        ui.caption(body, "Geräte").pack(fill="x", pady=(ui.px(16), ui.px(6)))
        self.list_frame = tk.Frame(body, bg=body.cget("bg"))
        self.list_frame.pack(fill="x")
        self.items = {}
        self._signature = None

    # Aktionen
    def _set_volume(self, v):
        if self.default_id:
            self.app.safe(self.app.backend.set_device_volume, self.default_id, v)

    def _set_mute(self, m):
        if self.default_id:
            self.app.safe(self.app.backend.set_device_mute, self.default_id, m)
            self.app.refresh(reschedule=False)

    def toggle_mute(self):
        self._set_mute(not self.muted)

    def choose(self, dev_id):
        name = dict(self.devices).get(dev_id, "")
        if self.app.safe(self.app.backend.set_default_device, dev_id) is not False:
            self.app.status("Standardgerät: " + name, "ok")
        self.app.refresh(reschedule=False)

    # Anzeige
    def _item(self, dev_id, name):
        """Geräte-Eintrag wie ein Zephyr-Menüeintrag: aktiv = roter Balken links."""
        ui, t = self.app.ui, self.app.ui.t
        item = tk.Frame(self.list_frame, bg=t["card"], cursor="hand2")
        item.pack(fill="x", pady=1)
        bar = tk.Frame(item, bg=t["card"], width=ui.px(3))
        bar.pack(side="left", fill="y")
        ic = tk.Label(item, text=ui.icon(self.icon), font=ui.f["icon_small"], bg=t["card"], fg=t["dim"],
                      padx=ui.px(10), pady=ui.px(7))
        ic.pack(side="left")
        tx = tk.Label(item, text=name, font=ui.f["body"], bg=t["card"], fg=t["dim"], anchor="w")
        tx.pack(side="left", fill="x", expand=True)
        mark = tk.Label(item, text="", font=ui.f["small"], bg=t["card"], fg=t["accent"], padx=ui.px(10))
        mark.pack(side="right")
        parts = (item, bar, ic, tx, mark)
        self.items[dev_id] = parts
        for w in (item, ic, tx, mark):
            w.bind("<ButtonRelease-1>", lambda e, i=dev_id: self.choose(i))
            w.bind("<Enter>", lambda e, i=dev_id: self._paint(i, True))
            w.bind("<Leave>", lambda e, i=dev_id: self._paint(i, False))

    def _paint(self, dev_id, inside=False):
        t, ui = self.app.ui.t, self.app.ui
        item, bar, ic, tx, mark = self.items[dev_id]
        active = dev_id == self.default_id
        bg = t["hover"] if inside or active else t["card"]
        for w in (item, ic, tx, mark):
            w.configure(bg=bg)
        bar.configure(bg=t["accent"] if active else bg)
        ic.configure(fg=t["accent"] if active else t["dim"])
        tx.configure(fg=t["text"] if active or inside else t["dim"],
                     font=ui.f["btn"] if active else ui.f["body"])
        mark.configure(text="Standard" if active else "")

    def show(self, devices):
        self.devices = [(d.id, d.name) for d in devices]
        default = next((d for d in devices if d.is_default), None)
        self.default_id = default.id if default else None
        self.default_name = default.name if default else ""
        self.default_volume = default.volume if default else 0
        self.muted = default.muted if default else False

        signature = tuple(self.devices)
        if signature != self._signature:
            self._signature = signature
            for w in self.list_frame.winfo_children():
                w.destroy()
            self.items = {}
            if not devices:
                self.app.ui.para(self.list_frame, "Keine aktiven Geräte gefunden.").pack(fill="x")
            for d in devices:
                self._item(d.id, d.name)
        for dev_id in self.items:
            self._paint(dev_id)
        self.volume_row.set_enabled(default is not None)
        if default:
            self.volume_row.update(default.volume, default.muted)


class AppsSection:
    def __init__(self, app):
        self.app = app

    def build(self, parent):
        ui = self.app.ui
        body = ui.card(parent, "Anwendungen",
                       "Lautstärke und Stumm für jedes Programm, das gerade Ton ausgibt.", icon="apps")
        self.inner = tk.Frame(body, bg=body.cget("bg"))
        self.inner.pack(fill="x")
        self.rows = {}
        self._signature = None

    def show(self, apps):
        ui = self.app.ui
        signature = tuple((a.key, a.name) for a in apps)
        if signature != self._signature:
            self._signature = signature
            for w in self.inner.winfo_children():
                w.destroy()
            self.rows = {}
            if not apps:
                ui.para(self.inner, "Gerade gibt keine Anwendung Ton aus.").grid(row=0, column=0, sticky="w")
            cols = APP_COLUMNS if len(apps) <= 8 else APP_COLUMNS + 1
            rows_per_col = (len(apps) + cols - 1) // cols if apps else 0
            for idx, a in enumerate(apps):
                col, row = divmod(idx, rows_per_col)
                vr = VolumeRow(
                    ui, self.inner, a.name,
                    lambda v, k=a.key: self.app.safe(self.app.backend.set_app_volume, k, v),
                    lambda m, k=a.key: (self.app.safe(self.app.backend.set_app_mute, k, m),
                                        self.app.refresh(reschedule=False)),
                    name_width=14, length=170 if cols == 2 else 120)
                vr.frame.grid(row=row, column=col, sticky="w", pady=ui.px(3),
                              padx=(0 if col == 0 else ui.px(28), 0))
                self.rows[a.key] = vr
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
            I("SoundControl öffnen / verstecken", self._action(lambda: app.toggle_window()), default=True),
            I("Ausgabegerät", M(lambda: self._device_items(app.output))),
            I("Eingabegerät", M(lambda: self._device_items(app.input))),
            M.SEPARATOR,
            I("Ausgabe stumm", self._action(lambda: app.output.toggle_mute()),
              checked=lambda item: app.output.muted),
            I("Mikrofon stumm", self._action(lambda: app.input.toggle_mute()),
              checked=lambda item: app.input.muted),
            M.SEPARATOR,
            I("Beenden", self._action(lambda: app.quit())),
        )
        try:
            self.icon = pystray.Icon("SoundControl", self._make_image(Image, ImageDraw, app.ui.t["accent"]),
                                     "SoundControl", menu)
            # eigener Hintergrund-Thread (unter Windows unproblematisch)
            threading.Thread(target=self.icon.run, daemon=True).start()
        except Exception:
            self.icon = None

    @staticmethod
    def _make_image(Image, ImageDraw, accent="#e5484d"):
        """Lautsprecher-Symbol im Zephyr-Stil: flaches Quadrat in Akzentfarbe, weißes Symbol."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, 63, 63), fill=accent)
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
                name, self._action(section.choose, dev_id), radio=True,
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
        self._tray_hint_shown = False
        self._status = ("Bereit", "ok")
        self.settings = z.Settings("SoundControl")
        self.topmost = bool(self.settings.get("topmost", False))

        root.title("SoundControl")
        root.resizable(False, False)
        self.ui = z.Zephyr(root, self.settings.get("theme", "dark"),
                           self.settings.get("palette", z.DEFAULT_PALETTE))

        self.output = DeviceSection(self, E_RENDER, "Ausgabe",
                                    "Klick auf ein Gerät macht es zum Standard für den Ton.", "speaker")
        self.input = DeviceSection(self, E_CAPTURE, "Eingabe",
                                   "Klick auf ein Mikrofon macht es zum Standard für die Aufnahme.", "mic")
        self.apps = AppsSection(self)

        self.build()
        root.attributes("-topmost", self.topmost)

        self.tray = TrayIcon(self)
        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        root.bind("<Unmap>", self._on_unmap)

        self.refresh()
        self._poll_tray()
        if start_hidden and self.tray.icon:
            root.withdraw()

    # -- Aufbau (auch nach Wechsel Hell/Dunkel bzw. Palette) -----------------------
    def build(self):
        ui, t, px = self.ui, self.ui.t, self.ui.px
        for child in self.root.winfo_children():
            child.destroy()

        # Kopf: Marke links, Schalter rechts
        head = tk.Frame(self.root, bg=t["bg"])
        head.pack(fill="x", padx=px(24), pady=(px(20), px(14)))
        tk.Label(head, text=ui.icon("volume"), font=ui.f["icon"], bg=t["accent"], fg=t["on_accent"],
                 padx=px(8), pady=px(6)).pack(side="left")
        names = tk.Frame(head, bg=t["bg"])
        names.pack(side="left", padx=px(12))
        tk.Label(names, text="SoundControl", font=ui.f["title"], bg=t["bg"], fg=t["text"]).pack(anchor="w")
        tk.Label(names, text="Ausgabe, Eingabe und Anwendungen auf einen Blick", font=ui.f["body"],
                 bg=t["bg"], fg=t["dim"]).pack(anchor="w")

        right = tk.Frame(head, bg=t["bg"])
        right.pack(side="right")
        ui.button(right, "Helles Design" if ui.dark else "Dunkles Design", self.toggle_theme, "ghost",
                  icon="sun" if ui.dark else "moon").pack(side="right")
        self.pin_btn = ui.button(right, "Immer vorne", self.toggle_topmost,
                                 "primary" if self.topmost else "ghost", icon="pin")
        self.pin_btn.pack(side="right", padx=(0, px(4)))
        ui.button(right, "Aktualisieren", lambda: self.refresh(reschedule=False), "ghost",
                  icon="refresh").pack(side="right", padx=(0, px(4)))
        self.palette_box = ui.combobox(right, list(z.PALETTES), width=16)
        self.palette_box.set(ui.palette)
        self.palette_box.bind("<<ComboboxSelected>>", lambda e: self.set_palette(self.palette_box.get()))
        self.palette_box.pack(side="right", padx=(0, px(10)))

        # Statuszeile ganz unten
        status = tk.Frame(self.root, bg=t["card"], highlightthickness=1, highlightbackground=t["line"])
        status.pack(side="bottom", fill="x")
        self.status_dot = tk.Label(status, text="●", font=ui.f["small"], bg=t["card"], fg=t["ok"])
        self.status_dot.pack(side="left", padx=(px(18), px(6)), pady=px(8))
        self.status_label = tk.Label(status, font=ui.f["small"], bg=t["card"], fg=t["dim"], anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.status_right = tk.Label(status, font=ui.f["small"], bg=t["card"], fg=t["dim"])
        self.status_right.pack(side="right", padx=px(18))

        # Karten: oben Ausgabe | Eingabe, darunter Anwendungen
        main = tk.Frame(self.root, bg=t["bg"])
        main.pack(fill="both", expand=True, padx=px(24), pady=(0, px(6)))
        top = tk.Frame(main, bg=t["bg"])
        top.pack(fill="x")
        left_col = tk.Frame(top, bg=t["bg"])
        right_col = tk.Frame(top, bg=t["bg"])
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, px(7)))
        right_col.grid(row=0, column=1, sticky="nsew", padx=(px(7), 0))
        top.columnconfigure(0, weight=1, uniform="half")
        top.columnconfigure(1, weight=1, uniform="half")
        self.output.build(left_col)
        self.input.build(right_col)
        self.apps.build(main)

        self.status(*self._status)

    def toggle_theme(self):
        self.ui.apply("light" if self.ui.dark else "dark")
        self.settings["theme"] = self.ui.theme
        self.settings.save()
        self.build()
        self.refresh(reschedule=False)

    def set_palette(self, name):
        self.ui.apply(self.ui.theme, name)
        self.settings["palette"] = self.ui.palette
        self.settings.save()
        self.build()
        self.refresh(reschedule=False)
        self.status("Farbpalette: " + self.ui.palette, "ok")

    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.settings["topmost"] = self.topmost
        self.settings.save()
        self.build()
        self.refresh(reschedule=False)

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

    # -- Status / Fehler / Aktualisieren -------------------------------------------
    def status(self, text, kind="ok"):
        """kind: ok (grün) · busy (gelb) · err (rot) · info (grau)."""
        self._status = (text, kind)
        t = self.ui.t
        self.status_label.configure(text=text)
        self.status_dot.configure(fg={"ok": t["ok"], "busy": t["warn"], "err": t["err"], "info": t["dim"]}[kind])

    def safe(self, func, *args):
        try:
            return func(*args)
        except Exception as exc:   # COM-Fehler sollen die Oberfläche nicht beenden
            self.status("Fehler: %s" % exc, "err")
            return False

    def refresh(self, reschedule=True):
        try:
            self.output.show(self.backend.list_devices(E_RENDER))
            self.input.show(self.backend.list_devices(E_CAPTURE))
            if self.root.state() != "withdrawn":   # Anwendungen nur bei sichtbarem Fenster
                self.apps.show(self.backend.list_apps())
        except Exception as exc:
            self.status("Fehler beim Einlesen: %s" % exc, "err")
        tray = "Tray aktiv" if getattr(self, "tray", None) and self.tray.icon else "ohne Tray"
        self.status_right.configure(text="%s · Zephyr %s" % (tray, z.VERSION))
        if hasattr(self, "tray"):
            self.tray.update()
        if reschedule:
            self.root.after(REFRESH_MS, self.refresh)


def main():
    demo = "--demo" in sys.argv
    if not demo and sys.platform != "win32":
        print("SoundControl läuft nur unter Windows. Zum Ansehen der Oberfläche: --demo")
        sys.exit(1)
    backend = DemoAudioBackend() if demo else WindowsAudioBackend()
    z.dpi_aware()
    root = tk.Tk()
    SoundControlApp(root, backend, start_hidden="--minimiert" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    main()

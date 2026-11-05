"""Zephyr – gemeinsame Designsprache für meine Tkinter-Tools.

Herkunft: ASUS M16 Display Tool (ROG *Zephyrus* M16). Quelle, Regeln und Designset: https://github.com/robfich/zypher_design (DESIGN.md).

Benutzung (Datei neben das eigene Programm kopieren):

    import zephyr_tk as z
    z.dpi_aware()                       # vor tk.Tk()!
    root = tk.Tk()
    ui = z.Zephyr(root, theme="dark", palette="Zephyr Rot")   # Farben, Schriften, ttk-Stile
    body = ui.card(parent, "Titel", "Beschreibung", icon="phone")
    ui.button(body, "Los", start, "primary", icon="play").pack(side="left")

Nur Standardbibliothek. Läuft unter Windows 10/11 am schönsten (Segoe UI, Segoe MDL2 Assets,
dunkle Titelleiste); unter Linux/macOS mit Ersatzschriften und Ersatz-Symbolen.
"""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

VERSION = "1.2"

# ── Farben ───────────────────────────────────────────────────────────────────
# Graphit mit einem roten Akzent (dunkel) bzw. kühles Hellgrau (hell).
# Rolle → Wert. Neue Farben nur als neue Rolle hinzufügen, nie Hex-Werte im Tool-Code.
THEMES = {
    "dark": {
        "bg": "#101217",        # Fensterhintergrund
        "side": "#14161c",      # Seitenleiste
        "card": "#181b22",      # Karten, Statuszeile
        "card2": "#1f232c",     # normale Knöpfe, Eingabefelder, Kacheln
        "line": "#2a2e39",      # 1-px-Rahmen, Trennlinien
        "hover": "#2f3442",     # Hover auf Knöpfen/Menü
        "text": "#e9ebf1",      # Haupttext
        "dim": "#8a91a3",       # Beschreibungen, Beschriftungen
        "accent": "#e5484d",    # Hauptaktion, Auswahl, aktiver Menüeintrag
        "accent_hover": "#f0646a",
        "on_accent": "#ffffff",
        "ok": "#2a9d62",        # bereit / erfolgreich / unbedenklich
        "warn": "#e5a50a",      # arbeitet / Achtung
        "err": "#e5484d",       # Fehler / gefährlich
    },
    "light": {
        "bg": "#f2f3f7", "side": "#e8eaf0", "card": "#fdfdfe", "card2": "#eceef3", "line": "#e2e5ec",
        "hover": "#dfe2ea", "text": "#16181d", "dim": "#6b7280", "accent": "#d42f45",
        "accent_hover": "#b8263a", "on_accent": "#ffffff", "ok": "#1f8a52", "warn": "#b7791f",
        "err": "#d42f45",
    },
}

# ── Farbpaletten ─────────────────────────────────────────────────────────────
# „Zephyr Rot“ ist das Original (= THEMES). Dazu vier Paletten im Stil von Material Design 3:
# getönte Flächen, kräftige Primärfarbe im hellen, pastellige Primärfarbe im dunklen Design
# (darauf dunkler Text: on_accent). Eine Palette überschreibt nur die Rollen, die sie nennt;
# ok und warn bleiben überall gleich. Auswahl: Zephyr(root, theme, palette) oder ui.apply(theme, palette).
DEFAULT_PALETTE = "Zephyr Rot"
PALETTES: dict[str, dict[str, dict[str, str]]] = {
    "Zephyr Rot": {"dark": {}, "light": {}},
    "Material Violett": {
        "dark": {"bg": "#141218", "side": "#1d1b20", "card": "#211f26", "card2": "#2b2930", "line": "#36343b",
                 "hover": "#3b383e", "accent": "#d0bcff", "accent_hover": "#e8ddff", "on_accent": "#381e72",
                 "err": "#f2b8b5", "text": "#e6e0e9", "dim": "#cac4d0"},
        "light": {"bg": "#fef7ff", "side": "#f7f2fa", "card": "#ffffff", "card2": "#f3edf7", "line": "#e6e0e9",
                  "hover": "#ece6f0", "accent": "#6750a4", "accent_hover": "#523d8f", "on_accent": "#ffffff",
                  "err": "#b3261e", "text": "#1d1b20", "dim": "#625b71"}},
    "Material Blau": {
        "dark": {"bg": "#131314", "side": "#1b1c1d", "card": "#1e1f20", "card2": "#282a2c", "line": "#333537",
                 "hover": "#37393b", "accent": "#a8c7fa", "accent_hover": "#d3e3fd", "on_accent": "#062e6f",
                 "err": "#f2b8b5", "text": "#e3e3e3", "dim": "#c4c7c5"},
        "light": {"bg": "#f8fafd", "side": "#f0f4f9", "card": "#ffffff", "card2": "#e9eef6", "line": "#dde3ea",
                  "hover": "#e1e7ef", "accent": "#0b57d0", "accent_hover": "#0842a0", "on_accent": "#ffffff",
                  "err": "#b3261e", "text": "#1f1f1f", "dim": "#5e5e5e"}},
    "Material Grün": {
        "dark": {"bg": "#101510", "side": "#171d17", "card": "#1b211b", "card2": "#252b25", "line": "#303630",
                 "hover": "#353b35", "accent": "#6dd58c", "accent_hover": "#c4eed0", "on_accent": "#0a3818",
                 "err": "#f2b8b5", "text": "#dfe4db", "dim": "#c0c9bd"},
        "light": {"bg": "#f6fbf3", "side": "#eef3ea", "card": "#ffffff", "card2": "#e9efe5", "line": "#dfe4db",
                  "hover": "#e3e9de", "accent": "#146c2e", "accent_hover": "#0f5223", "on_accent": "#ffffff",
                  "err": "#b3261e", "text": "#171d17", "dim": "#58635a"}},
    "Material Orange": {
        "dark": {"bg": "#19120c", "side": "#211a13", "card": "#261e17", "card2": "#312821", "line": "#3d342b",
                 "hover": "#443a31", "accent": "#ffb870", "accent_hover": "#ffdcbe", "on_accent": "#4a2800",
                 "err": "#f2b8b5", "text": "#efe0d5", "dim": "#d6c3b5"},
        "light": {"bg": "#fff8f5", "side": "#fbf1ea", "card": "#ffffff", "card2": "#f6ebe3", "line": "#ecdfd5",
                  "hover": "#f0e3da", "accent": "#8b5000", "accent_hover": "#6a3c00", "on_accent": "#ffffff",
                  "err": "#b3261e", "text": "#221a14", "dim": "#6a5b4f"}},
}


def colors(theme: str = "dark", palette: str = DEFAULT_PALETTE) -> dict[str, str]:
    """Alle Rollen für Hell/Dunkel + Palette (unbekannte Namen → dark bzw. Zephyr Rot)."""
    theme = theme if theme in THEMES else "dark"
    return {**THEMES[theme], **PALETTES.get(palette, PALETTES[DEFAULT_PALETTE])[theme]}


# ── Symbole ──────────────────────────────────────────────────────────────────
# Segoe MDL2 Assets (in Windows 10/11 enthalten) als Zeichencode; zweiter Wert = Ersatz ohne diese Schrift.
ICONS = {
    "phone": (chr(0xE8EA), "▯"), "clean": (chr(0xE74D), "✕"), "chart": (chr(0xE9D9), "▤"), "link": (chr(0xE703), "⇄"),
    "usb": (chr(0xE88E), "⇄"), "wifi": (chr(0xE701), "≈"), "settings": (chr(0xE713), "⚙"), "folder": (chr(0xE8B7), "▭"),
    "play": (chr(0xE768), "▶"), "stop": (chr(0xE71A), "■"), "check": (chr(0xE73E), "✓"), "warning": (chr(0xE7BA), "⚠"),
    "info": (chr(0xE946), "ℹ"), "refresh": (chr(0xE72C), "↻"), "copy": (chr(0xE8C8), "⧉"), "move": (chr(0xE8DE), "➜"),
    "delete": (chr(0xE74D), "✕"), "star": (chr(0xE734), "★"), "doc": (chr(0xE8A5), "▤"), "help": (chr(0xE897), "?"),
    "shield": (chr(0xEA18), "◈"), "calendar": (chr(0xE787), "▦"), "monitor": (chr(0xE7F4), "▭"), "color": (chr(0xE790), "◐"),
    "apps": (chr(0xE71D), "▦"), "pc": (chr(0xE7F8), "▭"), "search": (chr(0xE721), "⌕"),
    "sun": ("☀", "☀"), "moon": ("☾", "☾"),
}
ICON_FONT = "Segoe MDL2 Assets"

# ── Schriften ────────────────────────────────────────────────────────────────
FONTS = {  # Rolle: (Familie, Größe, Gewicht)
    "title": ("Segoe UI Semibold", 20, "normal"), "h2": ("Segoe UI Semibold", 12, "normal"),
    "body": ("Segoe UI", 10, "normal"), "small": ("Segoe UI", 9, "normal"),
    "btn": ("Segoe UI Semibold", 10, "normal"), "nav": ("Segoe UI", 11, "normal"),
    "big": ("Segoe UI Semibold", 30, "normal"), "value": ("Segoe UI Semibold", 16, "normal"),
    "brand": ("Segoe UI Semibold", 13, "normal"), "mono": ("Consolas", 9, "normal"),
}

# ── Abstände (px bei 100 % Skalierung) ───────────────────────────────────────
SPACE = {"window": 32, "card_x": 22, "card_y": 18, "card_gap": 14, "btn_x": 16, "btn_y": 8, "gap": 8, "side": 232}


# ── Windows-Helfer ───────────────────────────────────────────────────────────
def dpi_aware() -> None:
    """Scharfe Darstellung bei 125/150 % Windows-Skalierung. Vor tk.Tk() aufrufen."""
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001 – ältere Windows-Versionen
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def titlebar_theme(window: tk.Misc, dark: bool) -> None:
    """Dunkle/helle Windows-Titelleiste (Windows 10 20H1+ / 11); anderswo ohne Wirkung."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes as W
        window.update_idletasks()
        user, dwm = ctypes.WinDLL("user32"), ctypes.WinDLL("dwmapi")
        user.GetParent.argtypes = [W.HWND]
        user.GetParent.restype = W.HWND
        dwm.DwmSetWindowAttribute.argtypes = [W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD]
        hwnd = user.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:  # noqa: BLE001
        pass


class Settings(dict):
    """Kleine JSON-Einstellungsdatei unter %LOCALAPPDATA%\\<App>\\einstellungen.json."""

    def __init__(self, app_name: str):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".config")
        self.path = base / app_name / "einstellungen.json"
        try:
            super().__init__(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            super().__init__()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


# ── Bausteine ────────────────────────────────────────────────────────────────
class Zephyr:
    """Hält Thema, Skalierung und Schriften und baut die Zephyr-Bausteine."""

    def __init__(self, root: tk.Tk, theme: str = "dark", palette: str = DEFAULT_PALETTE):
        self.root = root
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self.theme = theme if theme in THEMES else "dark"
        self.palette = palette if palette in PALETTES else DEFAULT_PALETTE
        self.has_icons = ICON_FONT in set(tkfont.families(root))
        self.apply(self.theme)

    # Grundlagen
    @property
    def t(self) -> dict:
        """Farbrollen des aktuellen Themas mit Palette, z.B. ui.t["card"]."""
        return self._colors

    @property
    def dark(self) -> bool:
        return self.theme == "dark"

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def icon(self, name: str) -> str:
        mdl2, fallback = ICONS.get(name, (name, name))
        return mdl2 if self.has_icons else fallback

    def apply(self, theme: str, palette: str | None = None) -> None:
        """Thema (und optional Palette) setzen, danach die Oberfläche neu aufbauen."""
        self.theme = theme if theme in THEMES else "dark"
        if palette is not None:
            self.palette = palette if palette in PALETTES else DEFAULT_PALETTE
        self._colors = colors(self.theme, self.palette)
        self.f = {k: tkfont.Font(root=self.root, family=fam, size=size, weight=w) for k, (fam, size, w) in FONTS.items()}
        icon_family = ICON_FONT if self.has_icons else "Segoe UI Symbol"
        self.f["icon"] = tkfont.Font(root=self.root, family=icon_family, size=14)
        self.f["icon_small"] = tkfont.Font(root=self.root, family=icon_family, size=11)
        self._style()
        self.root.configure(bg=self.t["bg"])
        titlebar_theme(self.root, self.dark)

    def _style(self) -> None:
        t, s = self.t, ttk.Style(self.root)
        s.theme_use("clam")
        s.configure("TCombobox", fieldbackground=t["card2"], background=t["card2"], foreground=t["text"],
                    arrowcolor=t["dim"], bordercolor=t["line"], lightcolor=t["card2"], darkcolor=t["card2"],
                    padding=self.px(6), arrowsize=self.px(14))
        s.map("TCombobox", fieldbackground=[("readonly", t["card2"]), ("disabled", t["card"])],
              foreground=[("disabled", t["dim"])], selectbackground=[("readonly", t["card2"])],
              selectforeground=[("readonly", t["text"])], bordercolor=[("focus", t["accent"])])
        for key, value in (("background", t["card2"]), ("foreground", t["text"]), ("selectBackground", t["accent"]),
                           ("selectForeground", t["on_accent"]), ("font", self.f["body"]), ("borderWidth", 0)):
            self.root.option_add(f"*TCombobox*Listbox.{key}", value)
        s.configure("TEntry", fieldbackground=t["card2"], foreground=t["text"], bordercolor=t["line"],
                    lightcolor=t["card2"], darkcolor=t["card2"], insertcolor=t["text"], padding=self.px(6))
        s.map("TEntry", bordercolor=[("focus", t["accent"])])
        s.configure("Horizontal.TScale", background=t["accent"], troughcolor=t["card2"], bordercolor=t["card"],
                    lightcolor=t["accent"], darkcolor=t["accent"], gripcount=0,
                    sliderlength=self.px(18), sliderthickness=self.px(18))
        s.map("Horizontal.TScale", background=[("active", t["accent_hover"])])
        s.configure("Treeview", background=t["card"], fieldbackground=t["card"], foreground=t["text"],
                    bordercolor=t["line"], lightcolor=t["card"], darkcolor=t["card"], rowheight=self.px(26),
                    font=self.f["body"])
        s.map("Treeview", background=[("selected", t["accent"])], foreground=[("selected", t["on_accent"])])
        s.configure("Treeview.Heading", background=t["card2"], foreground=t["dim"], font=self.f["small"],
                    bordercolor=t["line"], lightcolor=t["card2"], darkcolor=t["card2"], relief="flat",
                    padding=(self.px(8), self.px(6)))
        s.map("Treeview.Heading", background=[("active", t["hover"])])
        s.configure("Vertical.TScrollbar", background=t["card2"], troughcolor=t["bg"], bordercolor=t["bg"],
                    lightcolor=t["card2"], darkcolor=t["card2"], arrowcolor=t["dim"], gripcount=0)
        s.map("Vertical.TScrollbar", background=[("active", t["hover"])])

    # Text
    def para(self, parent, text: str = "", dim: bool = True, font: str = "body", **kw) -> tk.Label:
        """Absatz, der mit der Breite umbricht."""
        label = tk.Label(parent, text=text, bg=parent.cget("bg"), fg=self.t["dim" if dim else "text"],
                         font=self.f[font], justify="left", anchor="w", **kw)
        label.bind("<Configure>", lambda e: label.configure(wraplength=max(e.width - 4, 100)))
        return label

    def label(self, parent, text: str = "", font: str = "body", color: str = "text", **kw) -> tk.Label:
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=self.t[color], font=self.f[font], **kw)

    def caption(self, parent, text: str) -> tk.Label:
        """Kleine Überschrift in Großbuchstaben, z.B. „BELEGT“."""
        return self.label(parent, text.upper(), "small", "dim", anchor="w")

    # Knöpfe
    def button(self, parent, text: str, command, kind: str = "secondary", icon: str | None = None) -> tk.Label:
        """kind: primary (eine Hauptaktion je Bereich) · secondary · ghost (dezent) · danger."""
        t = self.t
        bg, fg, hover = {"primary": (t["accent"], t["on_accent"], t["accent_hover"]),
                         "secondary": (t["card2"], t["text"], t["hover"]),
                         "ghost": (parent.cget("bg"), t["dim"], t["hover"]),
                         "danger": (t["card2"], t["err"], t["hover"])}[kind]
        label = tk.Label(parent, text=(f"{self.icon(icon)}  " if icon else "") + text, bg=bg, fg=fg,
                         font=self.f["btn"], padx=self.px(SPACE["btn_x"]), pady=self.px(SPACE["btn_y"]), cursor="hand2")
        label.enabled = True

        def enter(_e):
            if label.enabled:
                label.configure(bg=hover)

        def release(e):
            if label.enabled and label.winfo_containing(e.x_root, e.y_root) is label:
                command()

        label.bind("<Enter>", enter)
        label.bind("<Leave>", lambda e: label.configure(bg=bg))
        label.bind("<ButtonRelease-1>", release)
        label.set_enabled = lambda on: (setattr(label, "enabled", on),
                                        label.configure(fg=fg if on else t["dim"], cursor="hand2" if on else "arrow"))
        return label

    def chips(self, parent, options: list[str], value: str, on_change, colors: dict | None = None) -> tk.Frame:
        """Auswahl-Chips (Segment-Schalter). Gewählter Chip = Akzent (oder Farbe aus `colors`)."""
        t = self.t
        frame = tk.Frame(parent, bg=parent.cget("bg"))
        frame.value = value
        labels = {}

        def paint():
            for opt, lab in labels.items():
                sel = opt == frame.value
                color = (colors or {}).get(opt, t["accent"])
                lab.configure(bg=color if sel else t["card2"], fg=t["on_accent"] if sel else t["dim"])

        def pick(opt):
            frame.value = opt
            paint()
            on_change(opt)

        for opt in options:
            lab = tk.Label(frame, text=opt, font=self.f["small"], padx=self.px(10), pady=self.px(5), cursor="hand2")
            lab.pack(side="left", padx=(0, 1))
            lab.bind("<ButtonRelease-1>", lambda e, o=opt: pick(o))
            lab.bind("<Enter>", lambda e, o=opt, l=lab: o != frame.value and l.configure(bg=t["hover"]))
            lab.bind("<Leave>", lambda e: paint())
            labels[opt] = lab
        frame.set = lambda v: (setattr(frame, "value", v), paint())
        paint()
        return frame

    def palettes(self, parent, on_change) -> tk.Frame:
        """Paletten-Auswahl: eine Kachel je Palette mit Farbmuster im aktuellen Hell/Dunkel.
        Gewählt = Rahmen in Akzentfarbe. on_change(name) speichert und ruft ui.apply(theme, name) + Neuaufbau."""
        t, px = self.t, self.px
        grid = tk.Frame(parent, bg=parent.cget("bg"))
        for column, name in enumerate(PALETTES):
            grid.columnconfigure(column, weight=1, uniform="palette")
            c = colors(self.theme, name)
            chosen = name == self.palette
            tile = tk.Frame(grid, bg=c["bg"], cursor="hand2", highlightthickness=2 if chosen else 1,
                            highlightbackground=t["accent"] if chosen else t["line"])
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else px(5), 0))
            swatch = tk.Frame(tile, bg=c["bg"])
            swatch.pack(fill="x", padx=px(12), pady=(px(12), px(8)))
            tk.Frame(swatch, bg=c["accent"], width=px(26), height=px(26)).pack(side="left")
            for role in ("card2", "hover", "dim"):
                tk.Frame(swatch, bg=c[role], width=px(12), height=px(26)).pack(side="left", padx=(px(3), 0))
            tk.Label(tile, text=name, font=self.f["btn"], bg=c["bg"], fg=c["text"], anchor="w").pack(fill="x", padx=px(12))
            tk.Label(tile, text="ausgewählt" if chosen else "Material 3" if name.startswith("Material") else "Original",
                     font=self.f["small"], bg=c["bg"], fg=c["accent"] if chosen else c["dim"], anchor="w"
                     ).pack(fill="x", padx=px(12), pady=(0, px(12)))
            for w in (tile, swatch, *swatch.winfo_children(), *tile.winfo_children()):
                w.bind("<ButtonRelease-1>", lambda e, n=name: n != self.palette and on_change(n))
        return grid

    # Flächen
    def card(self, parent, title: str, hint: str | None = None, icon: str | None = None, right=None,
             icon_color: str = "accent") -> tk.Frame:
        """Karte mit Symbol, Titel und Beschreibung. Gibt den Inhaltsbereich zurück.
        icon_color: Farbrolle des Symbols – normal „accent“, für Status-Karten ok/warn/err."""
        t = self.t
        outer = tk.Frame(parent, bg=t["card"], highlightthickness=1, highlightbackground=t["line"])
        outer.pack(fill="x", pady=(0, self.px(SPACE["card_gap"])))
        inner = tk.Frame(outer, bg=t["card"])
        inner.pack(fill="both", expand=True, padx=self.px(SPACE["card_x"]), pady=self.px(SPACE["card_y"]))
        head = tk.Frame(inner, bg=t["card"])
        head.pack(fill="x")
        if icon:
            tk.Label(head, text=self.icon(icon), font=self.f["icon_small"], bg=t["card"],
                     fg=t[icon_color]).pack(side="left", padx=(0, self.px(8)))
        tk.Label(head, text=title, font=self.f["h2"], bg=t["card"], fg=t["text"]).pack(side="left")
        if right:
            right(head).pack(side="right")
        if hint:
            self.para(inner, hint).pack(fill="x", pady=(self.px(4), 0))
        body = tk.Frame(inner, bg=t["card"])
        body.pack(fill="both", expand=True, pady=(self.px(14), 0))
        return body

    def row(self, parent, pady=(0, 0)) -> tk.Frame:
        frame = tk.Frame(parent, bg=parent.cget("bg"))
        frame.pack(fill="x", pady=(self.px(pady[0]), self.px(pady[1])))
        return frame

    def badge(self, parent, text: str, color: str = "accent") -> tk.Label:
        """Kleines farbiges Etikett, z.B. „165 Hz“ oder „unbedenklich“."""
        return tk.Label(parent, text=text, font=self.f["small"], bg=self.t[color], fg=self.t["on_accent"],
                        padx=self.px(7), pady=self.px(1))

    def meter(self, parent, width: int = 220, height: int = 6) -> tk.Canvas:
        """Flacher Balken (Speicher, Fortschritt). meter.set(anteil 0..1, farbrolle)."""
        t = self.t
        canvas = tk.Canvas(parent, width=self.px(width), height=self.px(height), bg=t["card2"],
                           highlightthickness=0, bd=0)
        bar = canvas.create_rectangle(0, 0, 0, self.px(height), width=0, fill=t["accent"])
        canvas.state = (0.0, "accent")

        def draw(_e=None):
            fraction, color = canvas.state
            w = canvas.winfo_width() if canvas.winfo_width() > 1 else self.px(width)
            canvas.coords(bar, 0, 0, max(0.0, min(1.0, fraction)) * w, self.px(height))
            canvas.itemconfigure(bar, fill=self.t[color])

        def set_value(fraction: float, color: str = "accent"):
            canvas.state = (fraction, color)
            draw()
        canvas.set = set_value
        canvas.bind("<Configure>", draw)
        return canvas

    def check(self, parent, text: str, var: tk.BooleanVar) -> tk.Label:
        """Ankreuzfeld: ☑ in Akzentfarbe wenn an, ☐ in „dim“ wenn aus. Klick schaltet um."""
        t = self.t
        label = tk.Label(parent, bg=parent.cget("bg"), font=self.f["body"], cursor="hand2", anchor="w")

        def paint(*_a):
            if label.winfo_exists():
                on = var.get()
                label.configure(text=("☑  " if on else "☐  ") + text, fg=t["text"] if on else t["dim"])
        label.bind("<ButtonRelease-1>", lambda e: var.set(not var.get()))
        trace = var.trace_add("write", paint)
        label.bind("<Destroy>", lambda e: var.trace_remove("write", trace))
        paint()
        return label

    def table(self, parent, columns: dict[str, int], height: int = 14) -> ttk.Treeview:
        """Tabelle (ttk.Treeview) mit Scrollbalken. columns: Spaltenname → Breite in px.
        Zeilen-Tags: „err“ (rot), „dim“ (grau), „ok“ (grün markiert)."""
        t = self.t
        frame = tk.Frame(parent, bg=parent.cget("bg"))
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=list(columns), show="headings", selectmode="browse", height=height)
        for col, width in columns.items():
            tree.heading(col, text=col)
            tree.column(col, width=self.px(width), stretch=col == next(iter(columns)),
                        anchor="e" if width < 100 else "w")
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        tree.tag_configure("err", foreground=t["err"])
        tree.tag_configure("dim", foreground=t["dim"])
        tree.tag_configure("ok", foreground=t["ok"], background=t["card2"])
        return tree

    def entry(self, parent, var: tk.StringVar, width: int = 40) -> ttk.Entry:
        return ttk.Entry(parent, textvariable=var, width=width, font=self.f["body"])

    def combobox(self, parent, values=(), width: int = 30) -> ttk.Combobox:
        return ttk.Combobox(parent, state="readonly", values=list(values), width=width, font=self.f["body"])

    def log(self, parent, height: int = 6) -> tk.Text:
        t = self.t
        text = tk.Text(parent, height=height, wrap="word", font=self.f["mono"], bg=t["card2"], fg=t["dim"],
                       insertbackground=t["text"], relief="flat", bd=0, padx=self.px(10), pady=self.px(8),
                       state="disabled", highlightthickness=0)

        def write(line: str):
            text.configure(state="normal")
            text.insert("end", line.rstrip() + "\n")
            text.see("end")
            text.configure(state="disabled")
        text.write = write
        return text

    def scroll_page(self, parent) -> tuple[tk.Frame, tk.Canvas, tk.Frame]:
        """Scrollbare Seite: (rahmen, canvas, inhalt)."""
        t = self.t
        frame = tk.Frame(parent, bg=t["bg"])
        canvas = tk.Canvas(frame, bg=t["bg"], highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=t["bg"])
        window = canvas.create_window(0, 0, window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = tk.Frame(body, bg=t["bg"])
        content.pack(fill="both", expand=True, padx=(self.px(SPACE["window"]), self.px(20)), pady=(0, self.px(18)))
        return frame, canvas, content

    # Fenster-Gerüst
    def shell(self, brand_icon: str, brand: str, brand_sub: str, pages: list[tuple[str, str, str, str]],
              on_page, on_theme=None) -> "Shell":
        """Seitenleiste + Kopf + Statuszeile + scrollbare Seiten. pages: (key, icon, titel, untertitel)."""
        return Shell(self, brand_icon, brand, brand_sub, pages, on_page, on_theme)


class Shell:
    """Fenster-Gerüst nach Zephyr: links Navigation, rechts Kopf, Seiten und Statuszeile."""

    def __init__(self, ui: Zephyr, brand_icon, brand, brand_sub, pages, on_page, on_theme):
        self.ui, self.pages_spec, self.on_page = ui, pages, on_page
        t, root, px = ui.t, ui.root, ui.px
        for child in root.winfo_children():
            child.destroy()
        side = tk.Frame(root, bg=t["side"], width=px(SPACE["side"]))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(root, bg=t["line"], width=1).pack(side="left", fill="y")
        head = tk.Frame(side, bg=t["side"])
        head.pack(fill="x", padx=px(20), pady=(px(22), px(26)))
        tk.Label(head, text=ui.icon(brand_icon), font=ui.f["icon"], bg=t["accent"], fg=t["on_accent"],
                 padx=px(8), pady=px(6)).pack(side="left")
        names = tk.Frame(head, bg=t["side"])
        names.pack(side="left", padx=px(12))
        tk.Label(names, text=brand, font=ui.f["brand"], bg=t["side"], fg=t["text"]).pack(anchor="w")
        self.brand_sub = tk.Label(names, text=brand_sub, font=ui.f["small"], bg=t["side"], fg=t["dim"])
        self.brand_sub.pack(anchor="w")

        self.nav = {}
        for key, icon, title, _sub in pages:
            item = tk.Frame(side, bg=t["side"], cursor="hand2")
            item.pack(fill="x", padx=px(10), pady=1)
            bar = tk.Frame(item, bg=t["side"], width=px(3))
            bar.pack(side="left", fill="y")
            ic = tk.Label(item, text=ui.icon(icon), font=ui.f["icon_small"], bg=t["side"], fg=t["dim"],
                          padx=px(12), pady=px(10))
            ic.pack(side="left")
            tx = tk.Label(item, text=title, font=ui.f["nav"], bg=t["side"], fg=t["dim"], anchor="w")
            tx.pack(side="left", fill="x")
            self.nav[key] = (item, bar, ic, tx)
            for w in (item, ic, tx):
                w.bind("<ButtonRelease-1>", lambda e, k=key: self.show(k))
                w.bind("<Enter>", lambda e, k=key: self._paint(k, True))
                w.bind("<Leave>", lambda e, k=key: self._paint(k, False))
        self.foot = tk.Frame(side, bg=t["side"])
        self.foot.pack(side="bottom", fill="x", padx=px(14), pady=px(16))
        if on_theme:
            ui.button(self.foot, "Helles Design" if ui.dark else "Dunkles Design", on_theme, "ghost",
                      icon="sun" if ui.dark else "moon").pack(fill="x")

        main = tk.Frame(root, bg=t["bg"])
        main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(main, bg=t["bg"])
        header.pack(fill="x", padx=px(SPACE["window"]), pady=(px(24), px(16)))
        titles = tk.Frame(header, bg=t["bg"])
        titles.pack(side="left", fill="x", expand=True)
        self.title = tk.Label(titles, font=ui.f["title"], bg=t["bg"], fg=t["text"], anchor="w")
        self.title.pack(anchor="w")
        self.subtitle = tk.Label(titles, font=ui.f["body"], bg=t["bg"], fg=t["dim"], anchor="w")
        self.subtitle.pack(anchor="w")
        self.header_right = tk.Frame(header, bg=t["bg"])
        self.header_right.pack(side="right")

        status = tk.Frame(main, bg=t["card"], highlightthickness=1, highlightbackground=t["line"])
        status.pack(side="bottom", fill="x")
        self.status_dot = tk.Label(status, text="●", font=ui.f["small"], bg=t["card"], fg=t["ok"])
        self.status_dot.pack(side="left", padx=(px(18), px(6)), pady=px(8))
        self.status_label = tk.Label(status, text="Bereit", font=ui.f["small"], bg=t["card"], fg=t["dim"], anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.status_right = tk.Label(status, font=ui.f["small"], bg=t["card"], fg=t["dim"])
        self.status_right.pack(side="right", padx=px(18))

        holder = tk.Frame(main, bg=t["bg"])
        holder.pack(fill="both", expand=True)
        self.pages = {key: ui.scroll_page(holder) for key, *_ in pages}
        self.active = pages[0][0]
        root.bind_all("<MouseWheel>", self._wheel)
        root.bind_all("<Button-4>", lambda e: self._scroll(-1))
        root.bind_all("<Button-5>", lambda e: self._scroll(1))

    def content(self, key: str) -> tk.Frame:
        return self.pages[key][2]

    def show(self, key: str) -> None:
        self.active = key
        for k, (frame, _c, _b) in self.pages.items():
            frame.pack(fill="both", expand=True) if k == key else frame.pack_forget()
        for k in self.nav:
            self._paint(k, False)
        _, _, title, sub = next(p for p in self.pages_spec if p[0] == key)
        self.title.configure(text=title)
        self.subtitle.configure(text=sub)
        if self.on_page:
            self.on_page(key)

    def status(self, text: str, kind: str = "ok") -> None:
        """kind: ok (grün) · busy (gelb) · err (rot) · info (grau)."""
        t = self.ui.t
        self.status_label.configure(text=text)
        self.status_dot.configure(fg={"ok": t["ok"], "busy": t["warn"], "err": t["err"], "info": t["dim"]}[kind])

    def _paint(self, key, inside):
        t = self.ui.t
        item, bar, icon, text = self.nav[key]
        active = key == self.active
        bg = t["hover"] if inside or active else t["side"]
        for w in (item, icon, text):
            w.configure(bg=bg)
        bar.configure(bg=t["accent"] if active else bg)
        icon.configure(fg=t["accent"] if active else t["dim"])
        text.configure(fg=t["text"] if active or inside else t["dim"])

    def _wheel(self, event):
        if not isinstance(event.widget, tk.Text):
            self._scroll(int(-event.delta / 120))

    def _scroll(self, units):
        canvas = self.pages[self.active][1]
        if canvas.winfo_exists():
            canvas.yview_scroll(units, "units")


if __name__ == "__main__":
    print(f"Zephyr {VERSION} – Beispiel: python beispiel_app.py")
    sys.exit(0)

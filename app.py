"""Trafyle — ses, metin ve dosya dönüştürücü. Her şey bilgisayarda çalışır, dosyalar internete gönderilmez.

Copyright (C) 2026 Argun Karacabey

Bu program özgür yazılımdır: Free Software Foundation tarafından yayımlanan GNU Genel Kamu Lisansı'nın
3. sürümü ya da (tercihinize göre) daha sonraki bir sürümü koşullarıyla yeniden dağıtabilir ve/veya
değiştirebilirsiniz. Program yararlı olacağı umuduyla, ancak HİÇBİR GARANTİ OLMAKSIZIN dağıtılmaktadır.
Ayrıntılar için LICENSE dosyasına bakın.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Optional

import numpy as np

import ai
import converters
import engine
import exporters
import recorder
import tts
import updater
from engine import Segment

APP_NAME = "Trafyle"
APP_VERSION = "3.4.0"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"
INSTALLER = "Kur.bat" if IS_WINDOWS else "Kur.command"
OS_OWN = "Mac'in" if IS_MAC else "Windows'un" if IS_WINDOWS else "Bilgisayarın"

try:  # Sürükle-bırak isteğe bağlı
    from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD
    DND_OK = True
except Exception:  # noqa: BLE001
    DND_OK = False

try:  # Dinleme isteğe bağlı
    import sounddevice as sd
    AUDIO_OK = True
except Exception:  # noqa: BLE001
    AUDIO_OK = False

# ---------------------------------------------------------------- renkler (A · Gece Mavisi)
NAVY = "#14213D"
NAVY2 = "#1B2B4F"
NAVY3 = "#24365E"
NAVY_LINE = "#33476F"
NAVY_DASH = "#3E5585"
SIDE_TEXT = "#E7ECF7"
SIDE_MUTED = "#9FB0D3"
AMBER = "#F2A541"
AMBER_DARK = "#E0922B"
AMBER_TEXT = "#F7CD86"
GREEN = "#2E7D5B"
GREEN_TEXT = "#A8E3C5"
RED = "#8C2F39"
RED_TEXT = "#F2A5AE"
BG = "#F3F5FA"
CARD = "#FFFFFF"
LINE = "#E1E6F0"
LINE_STRONG = "#CBD3E3"
TEXT = "#1A2233"
MUTED = "#5B6680"
TS_BG = "#E8F0FD"
TS_FG = "#1D5BBF"
PLAY_BG = "#FFF3DC"
SPEAKER_COLORS = ["#B4490A", "#1D5BBF", "#2E7D5B", "#7A3E9D", "#A11D4A", "#0E6E7A", "#6B5B00", "#3B4A6B"]

MODEL_SHORT = {
    "tiny": "Çok hızlı",
    "base": "Hızlı",
    "small": "Dengeli",
    "medium": "Yüksek doğruluk",
    "large-v3-turbo": "En doğru",
}
SPEAKER_COUNTS = ["Otomatik", "2", "3", "4", "5", "6"]
FONT_MIN, FONT_MAX, FONT_DEFAULT = 11, 26, 15


def settings_path() -> str:
    return os.path.join(engine.app_dir(), "ayarlar.json")


def load_settings() -> dict:
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_settings(data: dict) -> None:
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def fmt_eta(sec: Optional[float]) -> str:
    if sec is None:
        return "hesaplanıyor"
    sec = int(sec)
    if sec < 60:
        return f"{sec} sn"
    if sec < 3600:
        return f"{sec // 60} dk {sec % 60:02d} sn"
    return f"{sec // 3600} sa {sec % 3600 // 60:02d} dk"


def fmt_duration(sec: float) -> str:
    sec = int(round(sec))
    if sec < 60:
        return f"{sec} sn"
    if sec < 3600:
        return f"{sec // 60} dk {sec % 60} sn"
    return f"{sec // 3600} sa {sec % 3600 // 60} dk"


def fmt_mmss(sec: float) -> str:
    sec = max(0, int(sec))
    if sec >= 3600:
        return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"
    return f"{sec // 60:02d}:{sec % 60:02d}"


def fmt_size(mb: int) -> str:
    return f"{mb / 1000:.1f} GB".replace(".", ",") if mb >= 1000 else f"{mb} MB"


def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


@dataclass
class Item:
    id: str
    path: str
    status: str = "pending"  # pending | running | done | error | cancelled
    progress: float = 0.0
    eta: Optional[float] = None
    note: str = ""            # kartta gösterilen kısa durum
    segments: list[Segment] = field(default_factory=list)
    speakers: list[str] = field(default_factory=list)
    result: Optional[engine.Result] = None
    peaks: Optional[np.ndarray] = None
    error: str = ""
    exported: bool = False

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def stem(self) -> str:
        return os.path.splitext(self.name)[0]


class Player:
    """Kaydı istenen saniyeden çalar; duraklatma ve konum bilgisi verir."""

    def __init__(self):
        self.playing = False
        self.paused_at: Optional[float] = None
        self._offset = 0.0
        self._t0 = 0.0

    def play(self, audio, start: float, sr: int = engine.SAMPLE_RATE) -> None:
        if not AUDIO_OK or audio is None:
            return
        self.stop()
        i = max(0, int(start * sr))
        if i >= len(audio):
            return
        sd.play(audio[i:], sr)
        self._offset = start
        self._t0 = time.monotonic()
        self.playing = True
        self.paused_at = None

    def stop(self) -> None:
        if AUDIO_OK and self.playing:
            try:
                sd.stop()
            except Exception:  # noqa: BLE001
                pass
        self.playing = False

    def pause(self) -> None:
        if self.playing:
            pos = self.position()
            self.stop()
            self.paused_at = pos

    def position(self) -> float:
        if self.playing:
            return self._offset + (time.monotonic() - self._t0)
        return self.paused_at or 0.0


class QueueCard:
    """Yan paneldeki tek bir dosya kartı."""

    def __init__(self, app: "App", parent: tk.Widget, item: Item):
        self.app = app
        self.item = item
        self.frame = tk.Frame(parent, bg=NAVY2, highlightthickness=2, highlightbackground=NAVY2,
                              highlightcolor=NAVY2, padx=10, pady=9, cursor="hand2")
        self.frame.pack(fill="x", pady=(0, 8))
        top = tk.Frame(self.frame, bg=NAVY2)
        top.pack(fill="x")
        self.icon = tk.Canvas(top, width=34, height=34, bg=NAVY2, highlightthickness=0)
        self.icon.pack(side="left")
        txt = tk.Frame(top, bg=NAVY2)
        txt.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self.name = tk.Label(txt, text=item.name, bg=NAVY2, fg=SIDE_TEXT, anchor="w",
                             font=app.f_side_bold)
        self.name.pack(fill="x")
        self.sub = tk.Label(txt, text="", bg=NAVY2, fg=SIDE_MUTED, anchor="w", font=app.f_side_small)
        self.sub.pack(fill="x")
        self.bar = tk.Canvas(self.frame, height=6, bg=NAVY2, highlightthickness=0)
        self.bar_visible = False
        self.widgets = [self.frame, top, self.icon, txt, self.name, self.sub, self.bar]
        for w in self.widgets:
            w.bind("<Button-1>", lambda e: app.select(item.id))
            for b in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
                w.bind(b, lambda e: app.card_menu(e, item.id))
        self.update(selected=False)

    def set_bg(self, color: str):
        for w in self.widgets:
            w.configure(bg=color)

    def update(self, selected: bool):
        it = self.item
        bg = NAVY3 if selected else NAVY2
        self.set_bg(bg)
        self.frame.configure(highlightbackground=AMBER if selected else bg, highlightcolor=AMBER if selected else bg)
        name = it.name if len(it.name) <= 30 else it.name[:28] + "…"
        self.name.configure(text=name)

        if it.status == "done":
            n_spk = len(it.speakers)
            sub = f"Tamamlandı · {fmt_duration(it.result.duration)}" + (f" · {n_spk} kişi" if n_spk else "")
            color, fill, glyph = GREEN_TEXT, GREEN, "✓"
        elif it.status == "running":
            sub = it.note or (f"%{int(it.progress * 100)} · kalan {fmt_eta(it.eta)}")
            color, fill, glyph = AMBER_TEXT, AMBER, "≋"
        elif it.status == "error":
            sub, color, fill, glyph = "Okunamadı · ayrıntı için seçin", RED_TEXT, RED, "!"
        elif it.status == "cancelled":
            sub, color, fill, glyph = "İptal edildi", SIDE_MUTED, NAVY_LINE, "×"
        else:
            sub, color, fill, glyph = "Bekliyor", SIDE_MUTED, NAVY_LINE, "…"
        self.sub.configure(text=sub, fg=color)

        c = self.icon
        c.delete("all")
        round_rect(c, 1, 1, 33, 33, 9, fill=fill, outline=fill)
        c.create_text(17, 17, text=glyph, fill=NAVY if it.status == "running" else "#FFFFFF",
                      font=self.app.f_icon)

        running = it.status == "running"
        if running and not self.bar_visible:
            self.bar.pack(fill="x", pady=(8, 0))
            self.bar_visible = True
        elif not running and self.bar_visible:
            self.bar.pack_forget()
            self.bar_visible = False
        if running:
            self.bar.update_idletasks()
            w = max(10, self.bar.winfo_width())
            self.bar.delete("all")
            round_rect(self.bar, 0, 0, w, 6, 3, fill=NAVY_LINE, outline=NAVY_LINE)
            pw = max(6, int(w * it.progress))
            round_rect(self.bar, 0, 0, pw, 6, 3, fill=AMBER, outline=AMBER)

    def destroy(self):
        self.frame.destroy()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()
        self.engine = engine.Engine()
        self.player = Player()
        self.items: dict[str, Item] = {}
        self.order: list[str] = []
        self.cards: dict[str, QueueCard] = {}
        self.selected: Optional[str] = None
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.cancel = threading.Event()
        self._counter = 0
        self._loading_editor = False
        self._play_index: list[tuple[float, int]] = []
        self._wave_ids: list[int] = []
        self._wave_played = -1
        self._prefix = ""

        root.title(APP_NAME)
        self._set_icon()
        self.ui_scale = 1.0
        if IS_WINDOWS:
            try:
                self.ui_scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
            except Exception:  # noqa: BLE001
                pass
        k = self.ui_scale
        root.geometry(self.settings.get("geometry", f"{int(1240 * k)}x{int(820 * k)}"))
        root.minsize(int(1040 * k), int(700 * k))
        root.configure(bg=BG)

        self._fonts()
        self._style()
        self._build()
        self._load_settings_into_ui()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        if IS_MAC:
            try:
                root.createcommand("tkAboutDialog", self.show_about)
            except Exception:  # noqa: BLE001
                pass
        mod = "Command" if IS_MAC else "Control"
        for key in ("plus", "equal", "KP_Add"):
            root.bind_all(f"<{mod}-{key}>", lambda e: self._font_step(1))
        for key in ("minus", "KP_Subtract"):
            root.bind_all(f"<{mod}-{key}>", lambda e: self._font_step(-1))
        root.bind_all(f"<{mod}-r>", lambda e: self.open_recorder())
        self.rec_dialog: Optional[RecordDialog] = None
        self._autostart_pending = False
        root.after(100, self._poll)
        root.after(3000, lambda: self.check_updates(manual=False))

    def _set_icon(self):
        """Pencere ve Dock simgesi (macOS'ta Tk, Dock simgesini de bununla değiştirir)."""
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        ico = os.path.join(base, "assets", "AppIcon.ico")
        if IS_WINDOWS and os.path.exists(ico):
            # Windows: .ico (içinde 16–256 px boyutlar) hem bu pencereye hem sonradan açılan pencerelere
            try:
                self.root.iconbitmap(ico)
                self.root.iconbitmap(default=ico)
            except Exception:  # noqa: BLE001
                pass
            import winplat
            # Görev çubuğu simgesi: pencere ekrana geldikten sonra doğrudan Windows'a ver
            self.root.after(50, lambda: winplat.set_window_icon(self.root, ico))
            self.root.after(800, lambda: winplat.set_window_icon(self.root, ico))
            return
        path = os.path.join(base, "assets", "logo.png")
        try:
            self._icon_img = tk.PhotoImage(file=path)
            self.root.iconphoto(True, self._icon_img)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ yazı tipleri ve stil

    def fs(self, n: int) -> int:
        """Yazı boyutu: Mac'te nokta; Windows'ta ekran ölçeğine göre piksel (Mac'teki görünümle aynı oran)."""
        if IS_WINDOWS:
            return -max(1, round(n * self.ui_scale))
        return n

    def _fonts(self):
        base = tkfont.nametofont("TkDefaultFont").actual()["family"]
        families = set(tkfont.families(self.root))
        mono = next((f for f in ("SF Mono", "Menlo", "Monaco", "DejaVu Sans Mono", "Consolas", "Courier New")
                     if f in families), "Courier")
        self.base_family, self.mono_family = base, mono
        self.font_size = int(self.settings.get("font_size", FONT_DEFAULT))
        self.font_size = max(FONT_MIN, min(FONT_MAX, self.font_size))
        self.f_title = tkfont.Font(family=base, size=self.fs(22), weight="bold")
        self.f_brand = tkfont.Font(family=base, size=self.fs(19), weight="bold")
        self.f_side = tkfont.Font(family=base, size=self.fs(13))
        self.f_side_bold = tkfont.Font(family=base, size=self.fs(13), weight="bold")
        self.f_side_small = tkfont.Font(family=base, size=self.fs(11))
        self.f_caps = tkfont.Font(family=base, size=self.fs(10), weight="bold")
        self.f_icon = tkfont.Font(family=base, size=self.fs(14), weight="bold")
        self.f_ui = tkfont.Font(family=base, size=self.fs(13))
        self.f_ui_bold = tkfont.Font(family=base, size=self.fs(13), weight="bold")
        self.f_small = tkfont.Font(family=base, size=self.fs(11))
        self.f_mono = tkfont.Font(family=mono, size=self.fs(12))
        self.f_text = tkfont.Font(family=base, size=self.fs(self.font_size))
        self.f_ts = tkfont.Font(family=mono, size=self.fs(max(9, self.font_size - 3)))
        self.f_spk = tkfont.Font(family=base, size=self.fs(self.font_size), weight="bold")

    def _style(self):
        s = ttk.Style(self.root)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass

        def flat(name, bg, fg, active, disabled_bg=None, disabled_fg=None, font=None, padding=(14, 9), border=None):
            s.configure(name, background=bg, foreground=fg, borderwidth=1 if border else 0,
                        bordercolor=border or bg, lightcolor=bg, darkcolor=bg, focusthickness=0,
                        focuscolor=bg, padding=padding, relief="flat", font=font or self.f_ui_bold)
            s.map(name,
                  background=[("disabled", disabled_bg or bg), ("pressed", active), ("active", active)],
                  foreground=[("disabled", disabled_fg or fg)],
                  lightcolor=[("active", active), ("pressed", active)],
                  darkcolor=[("active", active), ("pressed", active)])

        flat("Amber.TButton", AMBER, NAVY, AMBER_DARK, NAVY3, "#7F8FB3", padding=(8, 12))
        flat("Side.TButton", NAVY3, SIDE_TEXT, "#2E4374", NAVY2, "#6F7FA3", font=self.f_side, padding=(12, 8))
        flat("Navy.TButton", NAVY, "#FFFFFF", "#22325A", "#8D97AE", "#E4E8F0", padding=(14, 8))
        flat("Ghost.TButton", CARD, TEXT, "#EEF1F7", CARD, "#A3ABBB", border=LINE_STRONG, font=self.f_ui, padding=(12, 8))
        flat("Navy.TMenubutton", NAVY, "#FFFFFF", "#22325A", "#8D97AE", "#E4E8F0", padding=(14, 8))
        s.configure("Navy.TMenubutton", arrowcolor="#FFFFFF", arrowsize=10)

        flat("Seg.TButton", CARD, MUTED, "#EEF1F7", font=self.f_ui_bold, padding=(16, 7))
        flat("SegOn.TButton", NAVY, "#FFFFFF", NAVY, font=self.f_ui_bold, padding=(16, 7))
        s.configure("Light.TCombobox", fieldbackground=CARD, background=CARD, foreground=TEXT, arrowcolor=MUTED,
                    bordercolor=LINE_STRONG, lightcolor=CARD, darkcolor=CARD, selectbackground=CARD,
                    selectforeground=TEXT, padding=(8, 5))
        s.map("Light.TCombobox", fieldbackground=[("readonly", CARD)], foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", CARD)], selectforeground=[("readonly", TEXT)])
        s.configure("Light.Horizontal.TScale", background=AMBER, troughcolor=LINE, bordercolor=CARD,
                    lightcolor=AMBER, darkcolor=AMBER, sliderlength=18, sliderthickness=18)
        s.configure("Light.Horizontal.TProgressbar", background=AMBER, troughcolor=LINE, bordercolor=BG,
                    lightcolor=AMBER, darkcolor=AMBER, thickness=8)

        s.configure("Light.TCheckbutton", background=CARD, foreground=TEXT, font=self.f_ui, focusthickness=0,
                    indicatorbackground=CARD, indicatorforeground=NAVY, indicatormargin=(0, 0, 8, 0), padding=(0, 3))
        s.map("Light.TCheckbutton", background=[("active", CARD)], indicatorbackground=[("selected", CARD)])

        s.configure("Side.TCheckbutton", background=NAVY2, foreground=SIDE_TEXT, font=self.f_side,
                    indicatorbackground=NAVY3, indicatorforeground=AMBER, focusthickness=0,
                    indicatormargin=(0, 0, 8, 0), padding=(0, 3))
        s.map("Side.TCheckbutton", background=[("active", NAVY2)],
              indicatorbackground=[("selected", NAVY3), ("active", NAVY3)],
              foreground=[("disabled", "#6F7FA3")])

        s.configure("Side.TCombobox", fieldbackground=NAVY3, background=NAVY3, foreground=SIDE_TEXT,
                    arrowcolor=SIDE_TEXT, bordercolor=NAVY_LINE, lightcolor=NAVY3, darkcolor=NAVY3,
                    selectbackground=NAVY3, selectforeground=SIDE_TEXT, padding=(8, 5))
        s.map("Side.TCombobox", fieldbackground=[("readonly", NAVY3), ("disabled", NAVY2)],
              foreground=[("readonly", SIDE_TEXT), ("disabled", "#6F7FA3")],
              background=[("readonly", NAVY3), ("active", NAVY3)],
              selectbackground=[("readonly", NAVY3)], selectforeground=[("readonly", SIDE_TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", NAVY2)
        self.root.option_add("*TCombobox*Listbox.foreground", SIDE_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", AMBER)
        self.root.option_add("*TCombobox*Listbox.selectForeground", NAVY)
        self.root.option_add("*TCombobox*Listbox.font", self.f_side)

        rh = tkfont.Font(font=self.f_ui).metrics("linespace") + 14
        s.configure("Conv.Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, bordercolor=CARD,
                    lightcolor=CARD, darkcolor=CARD, rowheight=rh, font=self.f_ui, borderwidth=0)
        s.map("Conv.Treeview", background=[("selected", "#E8F0FD")], foreground=[("selected", TEXT)])
        s.configure("Conv.Treeview.Heading", background=BG, foreground=MUTED, font=self.f_caps, relief="flat",
                    bordercolor=LINE, lightcolor=BG, darkcolor=BG, padding=(8, 6))
        s.map("Conv.Treeview.Heading", background=[("active", BG)])

        for orient in ("Vertical",):
            s.configure(f"Light.{orient}.TScrollbar", background=LINE, troughcolor=CARD, bordercolor=CARD,
                        lightcolor=LINE, darkcolor=LINE, arrowcolor=MUTED, gripcount=0)
            s.configure(f"Dark.{orient}.TScrollbar", background=NAVY3, troughcolor=NAVY, bordercolor=NAVY,
                        lightcolor=NAVY3, darkcolor=NAVY3, arrowcolor=SIDE_MUTED, gripcount=0)

    # ------------------------------------------------------------------ arayüz

    def _build(self):
        self._build_sidebar()
        self._build_main()
        self._update_buttons()

    def _build_sidebar(self):
        side = tk.Frame(self.root, bg=NAVY, width=310)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.side = side
        inner = tk.Frame(side, bg=NAVY)
        inner.pack(fill="both", expand=True, padx=18, pady=(20, 16))

        # Marka
        brand = tk.Frame(inner, bg=NAVY)
        brand.pack(fill="x")
        size = min((44, 66, 88), key=lambda v: abs(v - 44 * self.ui_scale))
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        try:
            self._side_logo = tk.PhotoImage(file=os.path.join(base_dir, "assets", f"logo_side_{size}.png"))
            tk.Label(brand, image=self._side_logo, bg=NAVY, borderwidth=0).pack(side="left")
        except Exception:  # noqa: BLE001
            pass
        bt = tk.Frame(brand, bg=NAVY)
        bt.pack(side="left", padx=(12, 0))
        self._wordmark(bt, NAVY, SIDE_TEXT, AMBER, self.f_brand).pack(anchor="w")
        tk.Label(bt, text="Ses · metin · dosya", bg=NAVY, fg=SIDE_MUTED,
                 font=self.f_side_small).pack(anchor="w")

        # Dosya ekleme alanı
        self.drop = tk.Canvas(inner, height=84, bg=NAVY, highlightthickness=0, cursor="hand2")
        self.drop.pack(fill="x", pady=(16, 8))
        self.drop.bind("<Configure>", lambda e: self._draw_drop())
        self.drop.bind("<Button-1>", lambda e: self._add_dialog())
        self.rec_btn = ttk.Button(inner, text="●  Mikrofondan kaydet", style="Side.TButton", command=self.open_recorder)
        self.rec_btn.pack(fill="x", pady=(0, 14))

        # Alt kısım (önce paketlenir ki her zaman görünsün)
        bottom = tk.Frame(inner, bg=NAVY)
        bottom.pack(side="bottom", fill="x")
        self._build_settings(bottom)
        runrow = tk.Frame(bottom, bg=NAVY)
        runrow.pack(fill="x", pady=(12, 0))
        # Tek düğme: çalışırken "İptal et"e dönüşür
        self.start_btn = ttk.Button(runrow, text="Dönüştürmeyi başlat", style="Amber.TButton", command=self._start)
        self.start_btn.pack(fill="x")
        self.status_var = tk.StringVar(value="Hazır.")
        foot = tk.Frame(bottom, bg=NAVY)
        foot.pack(fill="x", pady=(8, 0))
        about = tk.Label(foot, text="Hakkında", bg=NAVY, fg=SIDE_MUTED, font=self.f_side_small, cursor="hand2")
        about.pack(side="right", anchor="n")
        about.bind("<Button-1>", lambda e: self.show_about())
        about.bind("<Enter>", lambda e: about.configure(fg=AMBER_TEXT))
        about.bind("<Leave>", lambda e: about.configure(fg=SIDE_MUTED))
        tk.Label(foot, textvariable=self.status_var, bg=NAVY, fg=SIDE_MUTED, font=self.f_side_small,
                 anchor="w", justify="left", wraplength=200).pack(side="left", fill="x", expand=True)
        self.update_lbl = tk.Label(bottom, text="", bg=AMBER, fg=NAVY, font=self.f_side_bold, cursor="hand2",
                                   padx=10, pady=6, anchor="w")
        self.update_lbl.bind("<Button-1>", lambda e: self._open_url(self._update_url or updater.RELEASES_URL))
        self._update_url = ""

        # Kuyruk
        qh = tk.Frame(inner, bg=NAVY)
        qh.pack(fill="x")
        self.queue_title = tk.Label(qh, text="KUYRUK", bg=NAVY, fg=SIDE_MUTED, font=self.f_caps)
        self.queue_title.pack(side="left")
        qwrap = tk.Frame(inner, bg=NAVY)
        qwrap.pack(fill="both", expand=True, pady=(8, 0))
        self.qcanvas = tk.Canvas(qwrap, bg=NAVY, highlightthickness=0)
        self.qscroll = ttk.Scrollbar(qwrap, orient="vertical", command=self.qcanvas.yview,
                                     style="Dark.Vertical.TScrollbar")
        self.qcanvas.configure(yscrollcommand=self.qscroll.set)
        self.qcanvas.pack(side="left", fill="both", expand=True)
        self.qinner = tk.Frame(self.qcanvas, bg=NAVY)
        self._qwin = self.qcanvas.create_window(0, 0, window=self.qinner, anchor="nw")
        self.qinner.bind("<Configure>", lambda e: self._queue_layout())
        self.qcanvas.bind("<Configure>", lambda e: (self.qcanvas.itemconfigure(self._qwin, width=e.width),
                                                    self._queue_layout()))
        self.queue_empty = tk.Label(self.qinner, text="Henüz dosya yok.", bg=NAVY, fg=SIDE_MUTED,
                                    font=self.f_side_small, anchor="w")
        self.queue_empty.pack(fill="x")
        for w in (self.qcanvas, self.qinner):
            w.bind("<MouseWheel>", self._queue_wheel)
            w.bind("<Button-4>", lambda e: self.qcanvas.yview_scroll(-1, "units"))
            w.bind("<Button-5>", lambda e: self.qcanvas.yview_scroll(1, "units"))

        if DND_OK:
            for w in (side, self.drop, self.qcanvas, self.qinner):
                try:
                    w.drop_target_register(DND_FILES)
                    w.dnd_bind("<<Drop>>", self._on_drop)
                except Exception:  # noqa: BLE001
                    pass

    def _build_settings(self, parent):
        box = tk.Frame(parent, bg=NAVY2, padx=14, pady=10)
        box.pack(fill="x", pady=(12, 0))
        tk.Label(box, text="AYARLAR", bg=NAVY2, fg=SIDE_MUTED, font=self.f_caps).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        box.columnconfigure(1, weight=1)

        def label(r, text):
            tk.Label(box, text=text, bg=NAVY2, fg=SIDE_MUTED, font=self.f_side).grid(row=r, column=0, sticky="w", pady=3)

        label(1, "Model")
        self.model_var = tk.StringVar()
        self.model_cb = ttk.Combobox(box, textvariable=self.model_var, state="readonly", style="Side.TCombobox",
                                     values=[MODEL_SHORT[k] for k, _, _ in engine.MODELS], width=17,
                                     font=self.f_side)
        self.model_cb.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=3)
        self.model_cb.bind("<<ComboboxSelected>>", lambda e: self._model_note_update())
        self.model_note = tk.Label(box, text="", bg=NAVY2, fg=SIDE_MUTED, font=self.f_side_small, anchor="e")
        self.model_note.grid(row=2, column=0, columnspan=2, sticky="e")

        label(3, "Dil")
        self.lang_var = tk.StringVar(value=engine.LANGUAGES[0][0])
        self.lang_cb = ttk.Combobox(box, textvariable=self.lang_var, state="readonly", style="Side.TCombobox",
                                    values=[n for n, _ in engine.LANGUAGES], width=17, font=self.f_side)
        self.lang_cb.grid(row=3, column=1, sticky="ew", padx=(10, 0), pady=3)

        self.vad_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="Sessiz bölümleri atla", variable=self.vad_var, style="Side.TCheckbutton").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.spk_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Konuşmacıları ayır", variable=self.spk_var, style="Side.TCheckbutton",
                        command=self._update_buttons).grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))
        label(6, "Kişi sayısı")
        self.spk_count_var = tk.StringVar(value=SPEAKER_COUNTS[0])
        self.spk_count_cb = ttk.Combobox(box, textvariable=self.spk_count_var, state="readonly",
                                         style="Side.TCombobox", values=SPEAKER_COUNTS, width=17, font=self.f_side)
        self.spk_count_cb.grid(row=6, column=1, sticky="ew", padx=(10, 0), pady=3)

        self.glossary_text = ""
        self.gloss_btn = ttk.Button(box, text="Özel isim ve terimler…", style="Side.TButton",
                                    command=self._edit_glossary)
        self.gloss_btn.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _draw_drop(self):
        c = self.drop
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20:
            return
        round_rect(c, 2, 2, w - 2, h - 2, 14, fill=NAVY2, outline=NAVY_DASH, dash=(5, 4), width=1.5)
        cx = w / 2
        c.create_line(cx, 14, cx, 30, fill=AMBER, width=2.4, capstyle="round")
        c.create_line(cx - 7, 21, cx, 14, cx + 7, 21, fill=AMBER, width=2.4, capstyle="round", joinstyle="round")
        c.create_text(cx, 47, text="Dosya ekle ya da sürükle" if DND_OK else "Dosya ekle",
                      fill=SIDE_TEXT, font=self.f_side_bold)
        c.create_text(cx, 66, text="m4a · mp3 · wav · mp4 · mov …", fill=SIDE_MUTED, font=self.f_side_small)

    def _build_main(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(side="left", fill="both", expand=True, padx=26, pady=(16, 18))
        self.main = outer

        # Mod seçici: Sesten metne / Metinden sese
        modebar = tk.Frame(outer, bg=BG)
        modebar.pack(fill="x", pady=(0, 12))
        seg = tk.Frame(modebar, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=3, pady=3)
        seg.pack(side="left")
        self.mode = "stt"
        self.mode_btns = {
            "stt": ttk.Button(seg, text="Sesten metne", style="SegOn.TButton", command=lambda: self.set_mode("stt")),
            "tts": ttk.Button(seg, text="Metinden sese", style="Seg.TButton", command=lambda: self.set_mode("tts")),
            "sum": ttk.Button(seg, text="Özetle", style="Seg.TButton", command=lambda: self.set_mode("sum")),
            "conv": ttk.Button(seg, text="Dönüştür", style="Seg.TButton", command=lambda: self.set_mode("conv")),
        }
        self.mode_btns["stt"].pack(side="left")
        self.mode_btns["tts"].pack(side="left", padx=(3, 0))
        self.mode_btns["sum"].pack(side="left", padx=(3, 0))
        self.mode_btns["conv"].pack(side="left", padx=(3, 0))

        self.stt_view = tk.Frame(outer, bg=BG)
        self.stt_view.pack(fill="both", expand=True)
        main = self.stt_view

        head = tk.Frame(main, bg=BG)
        head.pack(fill="x")
        tools = tk.Frame(head, bg=BG)
        tools.pack(side="right", anchor="center")
        self.title_var = tk.StringVar(value="Hoş geldiniz")
        self.sub_var = tk.StringVar(value="Soldan dosya ekleyin, ayarları seçin ve dönüştürmeyi başlatın.")
        tk.Label(head, textvariable=self.title_var, bg=BG, fg=TEXT, font=self.f_title, anchor="w").pack(
            side="left", fill="x", expand=True)
        tk.Label(main, textvariable=self.sub_var, bg=BG, fg=MUTED, font=self.f_ui, anchor="w").pack(fill="x")

        self.font_minus = ttk.Button(tools, text="A−", width=3, style="Ghost.TButton", command=lambda: self._font_step(-1))
        self.font_minus.pack(side="left")
        self.font_plus = ttk.Button(tools, text="A+", width=3, style="Ghost.TButton", command=lambda: self._font_step(1))
        self.font_plus.pack(side="left", padx=(4, 12))
        self.spk_btn = ttk.Button(tools, text="Konuşmacılar", width=0, style="Ghost.TButton", command=self._rename_speakers)
        self.spk_btn.pack(side="left")
        self.sum_btn = ttk.Button(tools, text="Özetle", width=0, style="Ghost.TButton", command=self._send_to_summary)
        self.sum_btn.pack(side="left", padx=(8, 0))
        self.speak_btn = ttk.Button(tools, text="Seslendir", width=0, style="Ghost.TButton", command=self._send_to_tts)
        self.speak_btn.pack(side="left", padx=(8, 0))
        self.copy_btn = ttk.Button(tools, text="Kopyala", width=0, style="Ghost.TButton", command=self._copy)
        self.copy_btn.pack(side="left", padx=8)
        self.export_btn = ttk.Menubutton(tools, text="Dışa aktar", width=0, style="Navy.TMenubutton")
        menu = tk.Menu(self.export_btn, tearoff=False)
        for key, label, _ in exporters.FORMATS:
            menu.add_command(label=label, command=lambda k=key: self._export(k))
        menu.add_separator()
        self.ts_var = tk.BooleanVar(value=False)
        menu.add_checkbutton(label="Zaman damgalarını ekle", variable=self.ts_var)
        self.export_btn["menu"] = menu
        self.export_btn.pack(side="left")

        # Çalar
        player = tk.Frame(main, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=16, pady=12)
        player.pack(fill="x", pady=(14, 14))
        self.play_c = tk.Canvas(player, width=46, height=46, bg=CARD, highlightthickness=0, cursor="hand2")
        self.play_c.pack(side="left")
        self.play_c.bind("<Button-1>", lambda e: self._toggle_play())
        self.time_var = tk.StringVar(value="00:00 / 00:00")
        tk.Label(player, textvariable=self.time_var, bg=CARD, fg=MUTED, font=self.f_mono).pack(side="right")
        self.wave = tk.Canvas(player, height=46, bg=CARD, highlightthickness=0, cursor="hand2")
        self.wave.pack(side="left", fill="x", expand=True, padx=16)
        self.wave.bind("<Configure>", lambda e: self._draw_wave())
        self.wave.bind("<Button-1>", self._on_wave_click)

        # Metin
        ed_card = tk.Frame(main, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        ed_card.pack(fill="both", expand=True)
        self.editor = tk.Text(ed_card, wrap="word", undo=True, relief="flat", padx=22, pady=16, height=6,
                              font=self.f_text, spacing1=3, spacing3=9, background=CARD, foreground=TEXT,
                              insertbackground=TEXT, highlightthickness=0, borderwidth=0,
                              selectbackground="#CFE0FB", selectforeground=TEXT)
        esb = ttk.Scrollbar(ed_card, orient="vertical", command=self.editor.yview, style="Light.Vertical.TScrollbar")
        self.editor.configure(yscrollcommand=esb.set)
        esb.pack(side="right", fill="y")
        self.editor.pack(side="left", fill="both", expand=True)
        self.editor.tag_configure("ts", font=self.f_ts, foreground=TS_FG, background=TS_BG)
        self.editor.tag_configure("playing", background=PLAY_BG)
        for i, color in enumerate(SPEAKER_COLORS):
            self.editor.tag_configure(f"spk{i}", font=self.f_spk, foreground=color)
        self.editor.tag_raise("playing")
        self.editor.tag_bind("ts", "<Button-1>", self._on_ts_click)
        self.editor.tag_bind("ts", "<Enter>", lambda e: self.editor.config(cursor="hand2"))
        self.editor.tag_bind("ts", "<Leave>", lambda e: self.editor.config(cursor="xterm"))
        self.editor.bind("<<Modified>>", self._on_editor_modified)
        self.editor.bind("<Escape>", lambda e: self._stop())
        for b in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.editor.bind(b, self._editor_menu)

        hint = ("Zamana tıklayın: kayıt oradan çalar   ·   Metne tıklayıp doğrudan düzeltin   ·   "
                "Sağ tık: konuşmacıyı değiştir   ·   Esc: durdur")
        if not AUDIO_OK:
            hint = "Bu bilgisayarda ses çalma kullanılamıyor; metni yine de düzeltebilirsiniz."
        tk.Label(main, text=hint, bg=BG, fg=MUTED, font=self.f_small, anchor="w").pack(fill="x", pady=(10, 0))

        self.tts_panel = TtsPanel(self, outer)
        self.conv_panel = ConvertPanel(self, outer)
        self.sum_panel = SummaryPanel(self, outer)
        self._draw_play_button()
        self._editor_placeholder("Soldan bir dosya ekleyin ve “Dönüştürmeyi başlat”a basın.\n\n"
                                 "Bitmiş bir dosyayı seçince metni burada görür, dinler ve düzeltirsiniz.")

    # ------------------------------------------------------------------ ayarlar

    def _model_key(self) -> str:
        label = self.model_var.get()
        for k, v in MODEL_SHORT.items():
            if v == label:
                return k
        return engine.DEFAULT_MODEL

    def _model_note_update(self):
        key = self._model_key()
        if engine.is_downloaded(key):
            self.model_note.configure(text="İndirildi", fg=GREEN_TEXT)
        else:
            self.model_note.configure(text=f"İlk kullanımda {fmt_size(engine.MODEL_SIZES[key])} indirilir",
                                      fg=AMBER_TEXT)

    def _lang_code(self) -> Optional[str]:
        return dict(engine.LANGUAGES).get(self.lang_var.get(), "tr")

    def _num_speakers(self) -> int:
        v = self.spk_count_var.get()
        return int(v) if v.isdigit() else 0

    def _load_settings_into_ui(self):
        key = self.settings.get("model", engine.DEFAULT_MODEL)
        if key not in MODEL_SHORT:
            key = engine.DEFAULT_MODEL
        self.model_var.set(MODEL_SHORT[key])
        self._model_note_update()
        lang = self.settings.get("language_label")
        if lang in dict(engine.LANGUAGES):
            self.lang_var.set(lang)
        self.vad_var.set(self.settings.get("vad", True))
        self.spk_var.set(self.settings.get("speakers", False))
        if self.settings.get("num_speakers") in SPEAKER_COUNTS:
            self.spk_count_var.set(self.settings["num_speakers"])
        self.ts_var.set(self.settings.get("timestamps", False))
        self.glossary_text = self.settings.get("glossary", "")
        self._update_glossary_button()
        self._update_buttons()

    def _collect_settings(self) -> dict:
        self.settings.update({
            "model": self._model_key(),
            "language_label": self.lang_var.get(),
            "vad": self.vad_var.get(),
            "speakers": self.spk_var.get(),
            "num_speakers": self.spk_count_var.get(),
            "timestamps": self.ts_var.get(),
            "glossary": self.glossary_text,
            "font_size": self.font_size,
            "tts_voice": self.tts_panel.voice_key(),
            "tts_speed": round(self.tts_panel.speed_var.get(), 2),
            "geometry": self.root.geometry(),
        })
        self.settings.update(self.conv_panel.collect_settings())
        return self.settings

    def _update_glossary_button(self):
        n = len([t for t in self.glossary_text.replace("\n", ",").split(",") if t.strip()])
        self.gloss_btn.configure(text=f"Özel isim ve terimler ({n})" if n else "Özel isim ve terimler…")

    def _edit_glossary(self):
        win = tk.Toplevel(self.root, bg=CARD, padx=20, pady=18)
        win.title("Özel isim ve terimler")
        win.transient(self.root)
        win.resizable(False, False)
        tk.Label(win, text="Kayıtta geçen özel isim ve terimler", bg=CARD, fg=TEXT, font=self.f_ui_bold).pack(anchor="w")
        tk.Label(win, text="Virgülle ya da alt alta yazın. Örn: Altınbaş, YÖKAK, Ayşe Yılmaz", bg=CARD, fg=MUTED,
                 font=self.f_small).pack(anchor="w", pady=(2, 8))
        txt = tk.Text(win, width=48, height=7, wrap="word", font=self.f_ui, relief="flat",
                      highlightthickness=1, highlightbackground=LINE_STRONG, highlightcolor=TS_FG, padx=8, pady=6)
        txt.pack()
        txt.insert("1.0", self.glossary_text)
        row = tk.Frame(win, bg=CARD)
        row.pack(fill="x", pady=(12, 0))

        def ok():
            self.glossary_text = txt.get("1.0", "end").strip()
            self._update_glossary_button()
            save_settings(self._collect_settings())
            win.destroy()

        ttk.Button(row, text="Kaydet", style="Navy.TButton", command=ok).pack(side="right")
        ttk.Button(row, text="Vazgeç", style="Ghost.TButton", command=win.destroy).pack(side="right", padx=8)
        txt.focus_set()
        win.grab_set()

    def _font_step(self, step: int):
        new = max(FONT_MIN, min(FONT_MAX, self.font_size + step))
        if new == self.font_size:
            return
        self.font_size = new
        self.f_text.configure(size=self.fs(new))
        self.f_spk.configure(size=self.fs(new))
        self.f_ts.configure(size=self.fs(max(9, new - 3)))
        self.status_var.set(f"Yazı boyutu: {new}")
        self._update_buttons()

    # ------------------------------------------------------------------ kuyruk

    def _queue_layout(self):
        self.qcanvas.configure(scrollregion=self.qcanvas.bbox("all"))
        need = self.qinner.winfo_reqheight() > self.qcanvas.winfo_height()
        if need and not self.qscroll.winfo_ismapped():
            self.qscroll.pack(side="right", fill="y")
        elif not need and self.qscroll.winfo_ismapped():
            self.qscroll.pack_forget()

    def _queue_wheel(self, e):
        if self.qinner.winfo_reqheight() > self.qcanvas.winfo_height():
            self.qcanvas.yview_scroll(int(-e.delta / (1 if IS_MAC else 120)), "units")

    def _update_queue_title(self):
        n = len(self.order)
        self.queue_title.configure(text=f"KUYRUK · {n} DOSYA" if n else "KUYRUK")
        self.root.after_idle(self._queue_layout)
        if n and self.queue_empty.winfo_ismapped():
            self.queue_empty.pack_forget()
        elif not n and not self.queue_empty.winfo_ismapped():
            self.queue_empty.pack(fill="x")

    def _add_dialog(self):
        exts = " ".join("*" + e for e in engine.AUDIO_EXTS)
        paths = filedialog.askopenfilenames(
            title="Ses veya video dosyası seç",
            initialdir=self.settings.get("last_dir") or os.path.expanduser("~"),
            filetypes=[("Ses ve video", exts), ("Tüm dosyalar", "*.*")])
        self._add_paths(paths)

    def _on_drop(self, event):
        self._add_paths(self.root.tk.splitlist(event.data))

    def _add_paths(self, paths):
        added: list[str] = []
        skipped = []
        convertible: list[str] = []
        known = {it.path for it in self.items.values()}
        for p in paths:
            if os.path.isdir(p):
                for name in sorted(os.listdir(p)):
                    fp = os.path.join(p, name)
                    if os.path.isfile(fp) and fp.lower().endswith(engine.AUDIO_EXTS) and fp not in known:
                        added.append(self._add_item(fp))
                        known.add(fp)
                continue
            if not os.path.isfile(p):
                continue
            if not p.lower().endswith(engine.AUDIO_EXTS):
                if converters.ops_for(p):
                    convertible.append(p)
                else:
                    skipped.append(os.path.basename(p))
                continue
            if p in known:
                continue
            added.append(self._add_item(p))
            known.add(p)
        if paths:
            self.settings["last_dir"] = os.path.dirname(paths[0])
        self._update_queue_title()
        if convertible and not added:
            # PDF, fotoğraf vb. bırakıldıysa Dönüştür ekranına geç
            self.set_mode("conv")
            self.conv_panel.add_paths(convertible)
        elif convertible:
            skipped += [os.path.basename(p) + " (Dönüştür ekranında açın)" for p in convertible]
        if skipped:
            messagebox.showwarning(APP_NAME, "Desteklenmeyen dosyalar eklenmedi:\n" + "\n".join(skipped[:10]))
        if added and self.selected is None:
            self.select(added[0])
        self._update_buttons()

    def _add_item(self, path: str) -> str:
        self._counter += 1
        iid = f"i{self._counter}"
        it = Item(iid, path)
        self.items[iid] = it
        self.order.append(iid)
        self.cards[iid] = QueueCard(self, self.qinner, it)
        for w in self.cards[iid].widgets:
            w.bind("<MouseWheel>", self._queue_wheel, add="+")
        return iid

    def _refresh_card(self, iid: str):
        card = self.cards.get(iid)
        if card:
            card.update(selected=(iid == self.selected))

    def card_menu(self, event, iid: str):
        self.select(iid)
        it = self.items[iid]
        m = tk.Menu(self.root, tearoff=False)
        busy = self._busy()
        m.add_command(label="Yeniden işle", command=self._retry_selected,
                      state="normal" if not busy and it.status in ("done", "error", "cancelled") else "disabled")
        m.add_command(label="Listeden çıkar", command=self._remove_selected,
                      state="normal" if it.status != "running" else "disabled")
        m.tk_popup(event.x_root, event.y_root)

    def _remove_selected(self):
        it = self.items.get(self.selected or "")
        if not it or it.status == "running":
            return
        if it.status == "done" and not it.exported:
            if not messagebox.askyesno(APP_NAME, f"“{it.name}” dışa aktarılmadı. Listeden çıkarılsın mı?"):
                return
        self.player.stop()
        self.cards.pop(it.id).destroy()
        idx = self.order.index(it.id)
        self.order.remove(it.id)
        del self.items[it.id]
        self.selected = None
        self._update_queue_title()
        if self.order:
            self.select(self.order[min(idx, len(self.order) - 1)])
        else:
            self._show_empty()
        self._update_buttons()

    def _retry_selected(self):
        it = self.items.get(self.selected or "")
        if not it or it.status == "running" or self._busy():
            return
        if it.status == "done" and not messagebox.askyesno(APP_NAME, "Mevcut metin ve düzeltmeleriniz silinecek. Devam edilsin mi?"):
            return
        self.player.stop()
        it.status, it.progress, it.segments, it.speakers = "pending", 0, [], []
        it.result, it.peaks, it.error, it.exported, it.note = None, None, "", False, ""
        self._refresh_card(it.id)
        self._show_item(it)
        self._start()

    # ------------------------------------------------------------------ seçim ve görünüm

    def select(self, iid: str):
        if iid not in self.items:
            return
        if iid == self.selected:
            return
        self._save_editor()
        self.player.stop()
        self.player.paused_at = None
        old = self.selected
        self.selected = iid
        if old:
            self._refresh_card(old)
        self._refresh_card(iid)
        self._show_item(self.items[iid])

    def _show_empty(self):
        self.title_var.set("Hoş geldiniz")
        self.sub_var.set("Soldan dosya ekleyin, ayarları seçin ve dönüştürmeyi başlatın.")
        self._editor_placeholder("Soldan bir dosya ekleyin ve “Dönüştürmeyi başlat”a basın.")
        self._draw_wave()
        self.time_var.set("00:00 / 00:00")

    def _update_header(self, it: Item):
        self.title_var.set(it.stem)
        if it.status == "done" and it.result:
            words = sum(len(s.text.split()) for s in it.segments)
            parts = [fmt_duration(it.result.duration), f"{words:,} kelime".replace(",", "."), f"{len(it.segments)} satır"]
            if it.speakers:
                parts.append(f"{len(it.speakers)} konuşmacı")
            self.sub_var.set(" · ".join(parts))
        elif it.status == "running":
            self.sub_var.set("Dönüştürülüyor… metin geldikçe aşağıda görünür.")
        elif it.status == "error":
            self.sub_var.set("Bu dosya işlenemedi.")
        elif it.status == "cancelled":
            self.sub_var.set("İşlem iptal edildi.")
        else:
            self.sub_var.set("Henüz işlenmedi.")

    def _show_item(self, it: Item):
        self._update_header(it)
        if it.status == "done":
            self._loading_editor = True
            self.editor.configure(state="normal", foreground=TEXT)
            self.editor.delete("1.0", "end")
            for i, seg in enumerate(it.segments):
                self._insert_line(seg, first=(i == 0))
            self.editor.edit_reset()
            self.editor.edit_modified(False)
            self._loading_editor = False
            self._retag()
            if not it.segments:
                self._editor_placeholder("Bu kayıtta konuşma bulunamadı.")
            self.time_var.set(f"00:00 / {fmt_mmss(it.result.duration)}")
        elif it.status == "running":
            self._editor_placeholder("")
            self.editor.configure(state="normal", foreground=TEXT)
            for i, seg in enumerate(it.segments):
                self._insert_line(seg, first=(i == 0))
            self._retag()
            self.editor.configure(state="disabled")
        elif it.status == "error":
            self._editor_placeholder(f"Bu dosya işlenemedi.\n\n{it.error}")
        elif it.status == "cancelled":
            self._editor_placeholder("İşlem iptal edildi. Tekrar denemek için “Dönüştürmeyi başlat”a basın.")
        else:
            self._editor_placeholder("Bu dosya henüz işlenmedi. “Dönüştürmeyi başlat”a basın.")
        if it.status != "done":
            self.time_var.set("00:00 / 00:00")
        self._draw_wave()
        self._draw_play_button()
        self._update_buttons()

    # ------------------------------------------------------------------ işleme

    def _busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _start(self):
        if self._busy():
            return
        pending = [self.items[i] for i in self.order if self.items[i].status in ("pending", "cancelled", "error")]
        if not pending:
            messagebox.showinfo(APP_NAME, "İşlenecek dosya yok. Önce dosya ekleyin.")
            return
        for it in pending:
            if it.status != "pending":
                it.status, it.error, it.progress = "pending", "", 0
                self._refresh_card(it.id)
        self._save_editor()
        save_settings(self._collect_settings())
        opts = dict(model_key=self._model_key(), language=self._lang_code(), glossary=self.glossary_text,
                    vad=self.vad_var.get(), speakers=self.spk_var.get(), num_speakers=self._num_speakers())
        self.cancel.clear()
        self.worker = threading.Thread(target=self._work, args=([it.id for it in pending], opts), daemon=True)
        self.worker.start()
        self._update_buttons()

    def _work(self, ids: list[str], opts: dict):
        """Arka plan iş parçacığı. Arayüze yalnızca kuyruk üzerinden haber verir."""
        total = len(ids)
        for n, iid in enumerate(ids, 1):
            if self.cancel.is_set():
                break
            self.events.put(("start", iid, n, total))
            try:
                res = self.engine.transcribe(
                    self.items[iid].path,
                    on_status=lambda s, iid=iid: self.events.put(("status", iid, s)),
                    on_progress=lambda f, eta, seg, iid=iid: self.events.put(("progress", iid, f, eta, seg)),
                    cancel=self.cancel,
                    **opts,
                )
                self.events.put(("done", iid, res))
            except engine.Cancelled:
                self.events.put(("cancelled", iid))
                break
            except Exception as e:  # noqa: BLE001
                self.events.put(("error", iid, str(e)))
        self.events.put(("idle",))

    def _cancel(self):
        if self._busy():
            self.cancel.set()
            self.status_var.set("İptal ediliyor…")
            self._update_buttons()

    def _poll(self):
        try:
            for _ in range(500):
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        if self.player.playing and self.mode == "stt":
            self._update_play_position()
        self.root.after(100, self._poll)

    def _handle(self, ev: tuple):
        kind = ev[0]
        if kind == "idle":
            self.worker = None
            self._model_note_update()
            self._update_buttons()
            if self._autostart_pending and not self.cancel.is_set():
                self._autostart_pending = False
                if any(self.items[i].status == "pending" for i in self.order):
                    self.root.after(200, self._start)
                    return
            if not self.status_var.get().startswith(("Hata", "İptal")):
                self.status_var.set("Tüm dosyalar işlendi.")
            return
        iid = ev[1]
        it = self.items.get(iid)
        if it is None:
            return
        if kind == "start":
            _, _, n, total = ev
            it.status, it.progress, it.segments, it.note = "running", 0.0, [], "Başlıyor…"
            self._prefix = f"{n}/{total} · " if total > 1 else ""
            self.status_var.set(f"{self._prefix}{it.name} işleniyor")
            if self.selected is None:
                self.select(iid)
            elif self.selected == iid:
                self._show_item(it)
        elif kind == "status":
            it.note = ev[2]
            if self.selected == iid and ev[2].startswith("Konuşmacılar"):
                self.sub_var.set("Konuşmacılar ayrılıyor…")
        elif kind == "progress":
            _, _, frac, eta, seg = ev
            it.progress, it.eta, it.note = frac, eta, ""
            if seg is not None:
                it.segments.append(seg)
                if self.selected == iid:
                    self._append_editor_line(seg)
        elif kind == "done":
            res: engine.Result = ev[2]
            it.status, it.result, it.segments, it.progress = "done", res, list(res.segments), 1.0
            it.speakers = list(res.speakers)
            it.peaks = self._compute_peaks(res.audio)
            self.status_var.set(f"{it.name}: tamamlandı")
            if self.selected == iid:
                self._show_item(it)
        elif kind == "cancelled":
            it.status, it.segments, it.note = "cancelled", [], ""
            self.status_var.set("İptal edildi.")
            if self.selected == iid:
                self._show_item(it)
        elif kind == "error":
            it.status, it.error, it.note = "error", ev[2], ""
            self.status_var.set(f"Hata: {it.name}")
            if self.selected == iid:
                self._show_item(it)
        self._refresh_card(iid)
        self._update_buttons()

    # ------------------------------------------------------------------ düzeltme ekranı

    def _editor_placeholder(self, text: str):
        self._loading_editor = True
        self.editor.configure(state="normal")
        self.editor.delete("1.0", "end")
        if text:
            self.editor.insert("1.0", text)
        self.editor.configure(state="disabled", foreground=MUTED)
        self.editor.edit_modified(False)
        self._loading_editor = False

    def _insert_line(self, seg: Segment, first: bool):
        ts, spk, text = exporters.editor_line(seg)
        if not first:
            self.editor.insert("end", "\n")
        self.editor.insert("end", ts)
        self.editor.insert("end", " " + spk + text)

    def _append_editor_line(self, seg: Segment):
        self.editor.configure(state="normal", foreground=TEXT)
        first = self.editor.get("1.0", "end").strip() == ""
        self._insert_line(seg, first)
        last = int(self.editor.index("end-1c").split(".")[0])
        self._tag_line(last, [])
        self.editor.see("end")
        self.editor.configure(state="disabled")

    def _on_editor_modified(self, _event=None):
        if self._loading_editor:
            self.editor.edit_modified(False)
            return
        if self.editor.edit_modified():
            self.root.after_idle(self._retag)
            it = self.items.get(self.selected or "")
            if it:
                it.exported = False
            self.editor.edit_modified(False)

    def _speaker_tag(self, name: str, speakers: list[str]) -> str:
        i = speakers.index(name) if name in speakers else 0
        return f"spk{i % len(SPEAKER_COLORS)}"

    def _tag_line(self, ln: int, speakers: list[str]):
        line = self.editor.get(f"{ln}.0", f"{ln}.end")
        m = exporters.LINE_RE.match(line)
        if not m:
            return
        close = line.find("]")
        self.editor.tag_add("ts", f"{ln}.0", f"{ln}.{close + 1}")
        body_start = close + 1 + (1 if line[close + 1:close + 2] == " " else 0)
        spk, _ = exporters.split_speaker(line[body_start:], speakers)
        if spk:
            self.editor.tag_add(self._speaker_tag(spk, speakers), f"{ln}.{body_start}",
                                f"{ln}.{body_start + len(spk) + 1}")

    def _retag(self):
        it = self.items.get(self.selected or "")
        speakers = it.speakers if it else []
        self.editor.tag_remove("ts", "1.0", "end")
        for i in range(len(SPEAKER_COLORS)):
            self.editor.tag_remove(f"spk{i}", "1.0", "end")
        last = int(self.editor.index("end-1c").split(".")[0])
        for ln in range(1, last + 1):
            self._tag_line(ln, speakers)

    def _save_editor(self):
        """Düzeltme ekranındaki metni kayda geri yazar."""
        it = self.items.get(self.selected or "")
        if not it or it.status != "done" or not it.result:
            return
        it.segments = exporters.parse_editor_text(self.editor.get("1.0", "end"), it.result.duration,
                                                  it.result.segments, it.speakers)

    def _current_done(self) -> Optional[Item]:
        it = self.items.get(self.selected or "")
        return it if it and it.status == "done" and it.result else None

    # ------------------------------------------------------------------ konuşmacılar

    def _set_line_speaker(self, ln: int, name: str):
        it = self._current_done()
        if not it:
            return
        line = self.editor.get(f"{ln}.0", f"{ln}.end")
        m = exporters.LINE_RE.match(line)
        if not m:
            return
        close = line.find("]")
        body = line[close + 1:].lstrip()
        _, rest = exporters.split_speaker(body, it.speakers)
        new = f"{line[:close + 1]} {name + ': ' if name else ''}{rest}"
        self.editor.delete(f"{ln}.0", f"{ln}.end")
        self.editor.insert(f"{ln}.0", new)
        self._retag()

    def _editor_menu(self, event):
        it = self._current_done()
        if not it:
            return
        idx = self.editor.index(f"@{event.x},{event.y}")
        ln = int(idx.split(".")[0])
        if not exporters.LINE_RE.match(self.editor.get(f"{ln}.0", f"{ln}.end")):
            return
        m = tk.Menu(self.root, tearoff=False)
        m.add_command(label="Buradan çal", command=lambda: self._play_from(self._line_start(ln) or 0.0),
                      state="normal" if AUDIO_OK else "disabled")
        m.add_separator()
        sub = tk.Menu(m, tearoff=False)
        for name in it.speakers:
            sub.add_command(label=name, command=lambda n=name: self._set_line_speaker(ln, n))
        if it.speakers:
            sub.add_separator()
        sub.add_command(label="Yeni konuşmacı…", command=lambda: self._new_speaker_for_line(ln))
        sub.add_command(label="Konuşmacıyı kaldır", command=lambda: self._set_line_speaker(ln, ""))
        m.add_cascade(label="Bu satırın konuşmacısı", menu=sub)
        m.add_command(label="Konuşmacıları adlandır…", command=self._rename_speakers)
        m.tk_popup(event.x_root, event.y_root)
        return "break"

    def _valid_speaker(self, name: str, existing: list[str]) -> Optional[str]:
        name = " ".join(name.split())
        if not name:
            return None
        if ":" in name or "[" in name:
            messagebox.showwarning(APP_NAME, "Konuşmacı adında “:” ya da “[” kullanılamaz.")
            return None
        if len(name) > 40:
            name = name[:40]
        return name

    def _new_speaker_for_line(self, ln: int):
        it = self._current_done()
        if not it:
            return
        name = simpledialog.askstring(APP_NAME, "Yeni konuşmacının adı:", parent=self.root,
                                      initialvalue=engine.speaker_name(len(it.speakers) + 1))
        name = self._valid_speaker(name or "", it.speakers)
        if not name:
            return
        if name not in it.speakers:
            it.speakers.append(name)
        self._set_line_speaker(ln, name)
        self._update_header(it)

    def _rename_speakers(self):
        it = self._current_done()
        if not it:
            return
        self._save_editor()
        if not it.speakers:
            messagebox.showinfo(APP_NAME, "Bu metinde konuşmacı yok.\n\nKonuşmacıları otomatik ayırmak için "
                                          "“Konuşmacıları ayır”ı açıp dosyayı yeniden işleyin, ya da bir satıra "
                                          "sağ tıklayıp “Yeni konuşmacı…” ile elle ekleyin.")
            return
        win = tk.Toplevel(self.root, bg=CARD, padx=20, pady=18)
        win.title("Konuşmacıları adlandır")
        win.transient(self.root)
        win.resizable(False, False)
        tk.Label(win, text="Konuşmacıları adlandırın", bg=CARD, fg=TEXT, font=self.f_ui_bold).grid(
            row=0, column=0, columnspan=3, sticky="w")
        tk.Label(win, text="Yeni ad metindeki bütün satırlara uygulanır.", bg=CARD, fg=MUTED,
                 font=self.f_small).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 10))
        counts = {s: sum(1 for seg in it.segments if seg.speaker == s) for s in it.speakers}
        entries = []
        for r, name in enumerate(it.speakers, start=2):
            dot = tk.Canvas(win, width=14, height=14, bg=CARD, highlightthickness=0)
            dot.create_oval(2, 2, 12, 12, fill=SPEAKER_COLORS[(r - 2) % len(SPEAKER_COLORS)], outline="")
            dot.grid(row=r, column=0, padx=(0, 8))
            var = tk.StringVar(value=name)
            e = tk.Entry(win, textvariable=var, width=28, font=self.f_ui, relief="flat",
                         highlightthickness=1, highlightbackground=LINE_STRONG, highlightcolor=TS_FG)
            e.grid(row=r, column=1, pady=4, ipady=4)
            tk.Label(win, text=f"{counts.get(name, 0)} satır", bg=CARD, fg=MUTED, font=self.f_small).grid(
                row=r, column=2, padx=(10, 0))
            entries.append((name, var))
        row = tk.Frame(win, bg=CARD)
        row.grid(row=len(entries) + 2, column=0, columnspan=3, sticky="ew", pady=(14, 0))

        def ok():
            new_names = []
            for old, var in entries:
                n = self._valid_speaker(var.get(), [])
                if not n:
                    return
                new_names.append(n)
            if len(set(new_names)) != len(new_names):
                # Aynı ada verilen konuşmacılar birleştirilir
                if not messagebox.askyesno(APP_NAME, "Bazı konuşmacılara aynı adı verdiniz; bunlar birleştirilecek. "
                                                     "Devam edilsin mi?", parent=win):
                    return
            mapping = {old: new for (old, _), new in zip(entries, new_names)}
            for seg in it.segments:
                if seg.speaker in mapping:
                    seg.speaker = mapping[seg.speaker]
            merged = []
            for n in new_names:
                if n not in merged:
                    merged.append(n)
            it.speakers = merged
            it.exported = False
            win.destroy()
            self._show_item(it)

        ttk.Button(row, text="Uygula", style="Navy.TButton", command=ok).pack(side="right")
        ttk.Button(row, text="Vazgeç", style="Ghost.TButton", command=win.destroy).pack(side="right", padx=8)
        win.grab_set()

    # ------------------------------------------------------------------ ses dalgası ve dinleme

    @staticmethod
    def _compute_peaks(audio: Optional[np.ndarray], n: int = 600) -> Optional[np.ndarray]:
        if audio is None or len(audio) == 0:
            return None
        chunk = max(1, len(audio) // n)
        trimmed = audio[: chunk * n] if len(audio) >= chunk * n else np.pad(audio, (0, chunk * n - len(audio)))
        peaks = np.abs(trimmed.reshape(n, chunk).astype(np.float32)).max(axis=1)
        top = np.percentile(peaks, 98) or 1.0
        return np.clip(peaks / top, 0.04, 1.0)

    def _draw_wave(self):
        c = self.wave
        c.delete("all")
        self._wave_ids = []
        self._wave_played = -1
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20:
            return
        it = self.items.get(self.selected or "")
        if not it or it.peaks is None:
            c.create_line(0, h / 2, w, h / 2, fill=LINE_STRONG, width=2, dash=(3, 4))
            msg = "Döküm bitince ses dalgası burada görünür" if it else ""
            if msg:
                t = c.create_text(w / 2, h / 2 - 1, text=msg, fill=MUTED, font=self.f_small)
                x1, y1, x2, y2 = c.bbox(t)
                c.tag_lower(c.create_rectangle(x1 - 10, y1, x2 + 10, y2, fill=CARD, width=0), t)
            return
        step = 6
        n = max(1, w // step)
        idx = (np.arange(n) * len(it.peaks) / n).astype(int)
        vals = it.peaks[idx]
        for i, v in enumerate(vals):
            bh = max(3, v * (h - 4))
            x = i * step + 2
            self._wave_ids.append(c.create_rectangle(x, (h - bh) / 2, x + 3, (h + bh) / 2, fill=LINE_STRONG, width=0))
        self._update_wave_progress(self.player.position() / it.result.duration if it.result else 0)

    def _update_wave_progress(self, frac: float):
        if not self._wave_ids:
            return
        k = int(max(0.0, min(1.0, frac)) * len(self._wave_ids))
        if k == self._wave_played:
            return
        lo, hi = sorted((max(self._wave_played, 0), k))
        for i in range(lo, hi + 1 if hi < len(self._wave_ids) else hi):
            if i < len(self._wave_ids):
                self.wave.itemconfigure(self._wave_ids[i], fill=AMBER if i < k else LINE_STRONG)
        self._wave_played = k

    def _on_wave_click(self, e):
        it = self._current_done()
        if not it or not AUDIO_OK:
            return
        frac = max(0.0, min(1.0, e.x / max(1, self.wave.winfo_width())))
        self._play_from(frac * it.result.duration, rewind=False)

    def _draw_play_button(self):
        c = self.play_c
        c.delete("all")
        enabled = self._current_done() is not None and AUDIO_OK
        fill = AMBER if enabled else LINE
        c.create_oval(1, 1, 45, 45, fill=fill, outline=fill)
        col = NAVY if enabled else "#A3ABBB"
        if self.player.playing:
            c.create_rectangle(17, 15, 21, 31, fill=col, width=0)
            c.create_rectangle(25, 15, 29, 31, fill=col, width=0)
        else:
            c.create_polygon(19, 14, 19, 32, 33, 23, fill=col, outline=col)

    def _toggle_play(self):
        it = self._current_done()
        if not it or not AUDIO_OK:
            return
        if self.player.playing:
            self.player.pause()
            self._draw_play_button()
            return
        start = self.player.paused_at
        if start is None:
            start = self._cursor_start()
        self._play_from(start, rewind=False)

    def _line_start(self, line_no: int) -> Optional[float]:
        line = self.editor.get(f"{line_no}.0", f"{line_no}.end")
        m = exporters.LINE_RE.match(line)
        if not m:
            return None
        h, mi, s, frac, _ = m.groups()
        return int(h) * 3600 + int(mi) * 60 + int(s) + (int(frac) / (10 ** len(frac)) if frac else 0)

    def _cursor_start(self) -> float:
        line_no = int(self.editor.index("insert").split(".")[0])
        while line_no >= 1:
            st = self._line_start(line_no)
            if st is not None:
                return st
            line_no -= 1
        return 0.0

    def _on_ts_click(self, event):
        idx = self.editor.index(f"@{event.x},{event.y}")
        start = self._line_start(int(idx.split(".")[0]))
        if start is not None:
            self._play_from(start)
        return "break"

    def _play_from(self, start: float, rewind: bool = True):
        it = self._current_done()
        if not it or not AUDIO_OK:
            return
        self._play_index = []
        last = int(self.editor.index("end-1c").split(".")[0])
        for ln in range(1, last + 1):
            st = self._line_start(ln)
            if st is not None:
                self._play_index.append((st, ln))
        try:
            self.player.play(it.result.audio, max(0.0, start - (0.3 if rewind else 0.0)))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Ses çalınamadı: {e}")
        self._draw_play_button()
        self._update_buttons()

    def _stop(self):
        self.player.stop()
        self.player.paused_at = None
        self.editor.tag_remove("playing", "1.0", "end")
        self._draw_play_button()
        self._update_wave_progress(0)
        it = self._current_done()
        if it:
            self.time_var.set(f"00:00 / {fmt_mmss(it.result.duration)}")

    def _update_play_position(self):
        it = self._current_done()
        if not it:
            return
        pos = self.player.position()
        dur = it.result.duration
        if pos >= dur:
            self._stop()
            return
        self.time_var.set(f"{fmt_mmss(pos)} / {fmt_mmss(dur)}")
        self._update_wave_progress(pos / dur)
        line = None
        for st, ln in self._play_index:
            if st <= pos:
                line = ln
            else:
                break
        self.editor.tag_remove("playing", "1.0", "end")
        if line:
            self.editor.tag_add("playing", f"{line}.0", f"{line}.end+1c")
            self.editor.see(f"{line}.0")

    # ------------------------------------------------------------------ dışa aktarma

    def _export(self, fmt: str):
        it = self._current_done()
        if not it:
            messagebox.showinfo(APP_NAME, "Dışa aktarmak için tamamlanmış bir dosya seçin.")
            return
        self._save_editor()
        if not it.segments:
            messagebox.showinfo(APP_NAME, "Dışa aktarılacak metin yok.")
            return
        _, label, ext = next(f for f in exporters.FORMATS if f[0] == fmt)
        path = filedialog.asksaveasfilename(
            title="Dışa aktar", defaultextension=ext, initialfile=it.stem + ext,
            initialdir=self.settings.get("export_dir") or os.path.dirname(it.path),
            filetypes=[(label, "*" + ext)])
        if not path:
            return
        used = [s for s in it.speakers if any(seg.speaker == s for seg in it.segments)]
        meta = {"duration": it.result.duration, "model": it.result.model, "speakers": used}
        try:
            exporters.export(fmt, path, it.segments, it.stem, meta, self.ts_var.get())
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Dışa aktarılamadı:\n{e}")
            return
        it.exported = True
        self.settings["export_dir"] = os.path.dirname(path)
        self.status_var.set(f"Kaydedildi: {os.path.basename(path)}")

    def _copy(self):
        it = self._current_done()
        if not it:
            return
        self._save_editor()
        self.root.clipboard_clear()
        self.root.clipboard_append(exporters.to_txt(it.segments, self.ts_var.get()))
        self.status_var.set("Metin panoya kopyalandı.")

    # ------------------------------------------------------------------ mod geçişi

    def set_mode(self, mode: str):
        if mode == self.mode:
            return
        self.player.stop()
        self.player.paused_at = None
        if self.mode == "stt":
            self._save_editor()
            self._stop()
        self.mode = mode
        for k, b in self.mode_btns.items():
            b.configure(style="SegOn.TButton" if k == mode else "Seg.TButton")
        views = {"stt": self.stt_view, "tts": self.tts_panel.frame, "conv": self.conv_panel.frame,
                 "sum": self.sum_panel.frame}
        for k, v in views.items():
            if k != mode:
                v.pack_forget()
        views[mode].pack(fill="both", expand=True)
        if mode == "stt":
            self._draw_play_button()
        self.tts_panel.refresh()
        self.conv_panel.refresh()

    def _transcript_text(self, it) -> str:
        if any(seg.speaker for seg in it.segments):
            lines, prev = [], None
            for seg in it.segments:
                if seg.speaker and seg.speaker == prev and lines:
                    lines[-1] += " " + seg.text
                else:
                    lines.append(f"{seg.speaker}: {seg.text}" if seg.speaker else seg.text)
                prev = seg.speaker
            text = "\n".join(lines)
        else:
            text = "\n\n".join(p for _, _, p in exporters.paragraphs(it.segments))
        return text

    def _send_to_tts(self):
        """Seçili dökümü (konuşmacı adlarıyla) seslendirme ekranına aktarır."""
        it = self._current_done()
        if not it:
            return
        self._save_editor()
        text = self._transcript_text(it)
        self.set_mode("tts")
        self.tts_panel.set_text(text, it.stem)

    def _send_to_summary(self):
        """Seçili dökümü (konuşmacı adlarıyla) Özetle ekranına aktarır."""
        it = self._current_done()
        if not it:
            return
        self._save_editor()
        self.set_mode("sum")
        self.sum_panel.set_text(self._transcript_text(it), it.stem)

    # ------------------------------------------------------------------ genel

    def _update_buttons(self):
        busy = self._busy()
        done = self._current_done() is not None
        has_pending = any(self.items[i].status in ("pending", "cancelled", "error") for i in self.order)
        if busy:
            self.start_btn.configure(text="İptal et", style="Side.TButton", command=self._cancel,
                                     state="disabled" if self.cancel.is_set() else "normal")
        else:
            self.start_btn.configure(text="Dönüştürmeyi başlat", style="Amber.TButton", command=self._start,
                                     state="normal" if has_pending else "disabled")
        for w in (self.model_cb, self.lang_cb):
            w.configure(state="disabled" if busy else "readonly")
        self.spk_count_cb.configure(state="readonly" if self.spk_var.get() and not busy else "disabled")
        for w in (self.export_btn, self.copy_btn, self.spk_btn, self.speak_btn, self.sum_btn):
            w.configure(state="normal" if done else "disabled")
        self.rec_btn.configure(state="normal" if recorder.AVAILABLE else "disabled")
        self.font_minus.configure(state="normal" if self.font_size > FONT_MIN else "disabled")
        self.font_plus.configure(state="normal" if self.font_size < FONT_MAX else "disabled")
        self._draw_play_button()

    # ------------------------------------------------------------------ ses kaydı

    def open_recorder(self):
        d = self.rec_dialog
        if d is not None and d.win.winfo_exists():
            d.win.deiconify()
            d.win.lift()
            d.win.focus_force()
            return
        if self.mode != "stt":
            self.set_mode("stt")
        self.rec_dialog = RecordDialog(self)

    def on_recording_saved(self, path: str, seconds: float, autostart: bool):
        self.rec_dialog = None
        if self.mode != "stt":
            self.set_mode("stt")
        before = set(self.order)
        self._add_paths([path])
        new = [i for i in self.order if i not in before]
        if new:
            self.select(new[0])
        name = os.path.basename(path)
        if not autostart:
            self.status_var.set(f"Kayıt saklandı: {name}")
        elif self._busy():
            self._autostart_pending = True
            self.status_var.set(f"Kayıt saklandı: {name} · sıradaki işten sonra yazıya dökülecek")
        else:
            self.status_var.set(f"Kayıt saklandı: {name}")
            self._start()
        save_settings(self._collect_settings())

    # ------------------------------------------------------------------ hakkında

    def _asset(self, name: str) -> str:
        return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets", name)

    def _wordmark(self, parent, bg, fg1, fg2, font) -> tk.Canvas:
        """İki renkli “Trafyle” yazısı (Tra + fyle) aralıksız."""
        a, b = APP_NAME[:3], APP_NAME[3:]
        w1, w2 = font.measure(a), font.measure(b)
        h = font.metrics("linespace")
        c = tk.Canvas(parent, width=w1 + w2 + 2, height=h, bg=bg, highlightthickness=0, borderwidth=0)
        c.create_text(0, h // 2, text=a, anchor="w", fill=fg1, font=font)
        c.create_text(w1, h // 2, text=b, anchor="w", fill=fg2, font=font)
        return c

    def show_about(self):
        win = tk.Toplevel(self.root, bg=CARD, padx=34, pady=26)
        win.title(f"{APP_NAME} hakkında")
        win.resizable(False, False)
        win.transient(self.root)
        try:
            self._about_logo = tk.PhotoImage(file=self._asset("logo_side_88.png"))
            tk.Label(win, image=self._about_logo, bg=CARD).pack()
        except Exception:  # noqa: BLE001
            pass
        self._wordmark(win, CARD, NAVY, AMBER_DARK, self.f_title).pack(pady=(10, 0))
        tk.Label(win, text=f"Sürüm {APP_VERSION}", bg=CARD, fg=MUTED, font=self.f_ui).pack()
        tk.Label(win, text="Ses, metin ve dosya dönüştürücü", bg=CARD, fg=TEXT, font=self.f_ui_bold).pack(pady=(12, 2))
        tk.Label(win, text="Her şey bilgisayarınızda çalışır; dosyalarınız internete gönderilmez.",
                 bg=CARD, fg=MUTED, font=self.f_small).pack()
        tk.Label(win, text=f"© 2026 {updater.COPYRIGHT} · Açık kaynak, GPL-3.0 lisansıyla ücretsiz",
                 bg=CARD, fg=MUTED, font=self.f_small).pack(pady=(14, 0))
        link = tk.Label(win, text="github.com/" + updater.GITHUB_REPO, bg=CARD, fg=TS_FG, font=self.f_small,
                        cursor="hand2")
        link.pack()
        link.bind("<Button-1>", lambda e: self._open_url(updater.PROJECT_URL))
        upd = tk.Frame(win, bg=CARD)
        upd.pack(pady=(12, 0))
        auto = tk.BooleanVar(value=bool(self.settings.get("update_check", True)))

        def set_auto():
            self.settings["update_check"] = bool(auto.get())
            save_settings(self._collect_settings())
        ttk.Checkbutton(upd, text="Yeni sürümleri otomatik denetle", variable=auto, command=set_auto,
                        style="Light.TCheckbutton").pack(side="left")
        self._about_upd = tk.Label(win, text="", bg=CARD, fg=MUTED, font=self.f_small)
        self._about_upd.pack()
        row = tk.Frame(win, bg=CARD)
        row.pack(pady=(14, 0))
        ttk.Button(row, text="Güncellemeleri denetle", width=0, style="Ghost.TButton",
                   command=lambda: self.check_updates(manual=True)).pack(side="left")
        ttk.Button(row, text="Üçüncü taraf lisansları", width=0, style="Ghost.TButton",
                   command=self.show_licenses).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Kapat", width=0, style="Navy.TButton", command=win.destroy).pack(side="left", padx=(8, 0))
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        self._about_win = win

    # ------------------------------------------------------------------ güncellemeler

    def _open_url(self, url: str):
        import webbrowser
        webbrowser.open(url)

    def check_updates(self, manual: bool = False):
        """GitHub'da daha yeni bir sürüm var mı? (Yalnızca sürüm numarası sorulur; hiçbir veri gönderilmez.)"""
        if not manual:
            if not self.settings.get("update_check", True):
                return
            if time.time() - float(self.settings.get("update_last", 0)) < updater.CHECK_INTERVAL:
                latest = self.settings.get("update_latest")
                if latest and updater.is_newer(latest, APP_VERSION):
                    self._show_update(latest, self.settings.get("update_url", ""))
                return
        lbl = getattr(self, "_about_upd", None)
        if manual and lbl is not None and lbl.winfo_exists():
            lbl.configure(text="Denetleniyor…", fg=MUTED)
        result: dict = {}

        def work():
            result["r"] = updater.latest_release()

        t = threading.Thread(target=work, daemon=True)
        t.start()

        def wait():
            if t.is_alive():
                self.root.after(200, wait)
                return
            r = result.get("r")
            lbl = getattr(self, "_about_upd", None)
            show = manual and lbl is not None and lbl.winfo_exists()
            if r is None:
                if show:
                    lbl.configure(text="Sürüm bilgisi alınamadı (internet bağlantısı yok ya da henüz yayınlanmış "
                                       "sürüm yok).", fg=MUTED)
                return
            self.settings["update_last"] = time.time()
            self.settings["update_latest"] = r["version"]
            self.settings["update_url"] = r["url"]
            if updater.is_newer(r["version"], APP_VERSION):
                self._show_update(r["version"], r["url"])
                if show:
                    lbl.configure(text=f"Yeni sürüm var: {r['version']} — sol alttaki bağlantıdan indirin.", fg=GREEN)
            elif show:
                lbl.configure(text=f"Trafyle güncel (sürüm {APP_VERSION}).", fg=GREEN)

        wait()

    def _show_update(self, version: str, url: str):
        self._update_url = url or updater.RELEASES_URL
        self.update_lbl.configure(text=f"↓  Yeni sürüm: {version} · İndir")
        if not self.update_lbl.winfo_ismapped():
            self.update_lbl.pack(fill="x", pady=(8, 0))

    def show_licenses(self):
        try:
            with open(self._asset("LISANSLAR.txt"), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = "Lisans dosyası bulunamadı."
        win = tk.Toplevel(self.root, bg=CARD)
        win.title("Üçüncü taraf lisansları")
        win.geometry(f"{int(760 * self.ui_scale)}x{int(560 * self.ui_scale)}")
        box = tk.Frame(win, bg=CARD)
        box.pack(fill="both", expand=True, padx=2, pady=2)
        t = tk.Text(box, wrap="word", font=self.f_mono, bg=CARD, fg=TEXT, relief="flat", padx=18, pady=14,
                    highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(box, orient="vertical", command=t.yview, style="Light.Vertical.TScrollbar")
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        t.insert("1.0", text)
        t.configure(state="disabled")
        win.bind("<Escape>", lambda e: win.destroy())
        self._lic_win = win

    def _on_close(self):
        d = self.rec_dialog
        if d is not None and d.win.winfo_exists() and d.busy():
            if not messagebox.askyesno(APP_NAME, "Ses kaydı sürüyor. Kayıt durdurulup saklanacak "
                                                 "(WAV olarak). Çıkılsın mı?"):
                return
            d.finish(then_close_app=True)
        if (self._busy() or self.conv_panel.busy()) and not messagebox.askyesno(
                APP_NAME, "Dönüştürme sürüyor. Çıkmak istiyor musunuz?"):
            return
        self._save_editor()
        unsaved = [it.name for it in self.items.values() if it.status == "done" and not it.exported]
        if unsaved and not messagebox.askyesno(
                APP_NAME, "Dışa aktarılmamış metinler var:\n" + "\n".join(unsaved[:8]) + "\n\nYine de çıkılsın mı?"):
            return
        self.cancel.set()
        self.tts_panel.cancel.set()
        self.conv_panel.cancel.set()
        self.player.stop()
        save_settings(self._collect_settings())
        self.root.destroy()


class RecordDialog:
    """Mikrofondan ses kaydı penceresi. Kayıt bitince dosya yazıya dökme kuyruğuna eklenir."""

    def __init__(self, app: "App"):
        self.app = app
        st = app.settings
        self.rec: Optional[recorder.Recorder] = None
        self.state = "idle"          # idle · recording · paused · saving
        self.base_path = ""
        self._silent_warned = False
        k = app.ui_scale

        w = self.win = tk.Toplevel(app.root, bg=CARD, padx=int(28 * k), pady=int(22 * k))
        w.title("Ses kaydı")
        w.resizable(False, False)
        w.transient(app.root)
        w.protocol("WM_DELETE_WINDOW", self.close)

        tk.Label(w, text="Ses kaydı", bg=CARD, fg=TEXT, font=app.f_title, anchor="w").pack(fill="x")
        tk.Label(w, text="Kayıt bilgisayarınıza kaydedilir; bitince yazıya dökülür.",
                 bg=CARD, fg=MUTED, font=app.f_small, anchor="w").pack(fill="x", pady=(2, 14))

        row = tk.Frame(w, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Mikrofon", bg=CARD, fg=MUTED, font=app.f_ui).pack(side="left")
        self.devices = recorder.input_devices()
        names = [n for _, n in self.devices]
        self.dev_var = tk.StringVar()
        saved = st.get("rec_device")
        default = recorder.default_input()
        pick = next((n for i, n in self.devices if n == saved), None) or \
            next((n for i, n in self.devices if i == default), None) or (names[0] if names else "")
        self.dev_var.set(pick)
        self.dev_cb = ttk.Combobox(row, textvariable=self.dev_var, values=names, state="readonly",
                                   style="Light.TCombobox", width=30, font=app.f_ui)
        self.dev_cb.pack(side="left", padx=(10, 0), fill="x", expand=True)

        self.clock = tk.Label(w, text="00:00:00", bg=CARD, fg=NAVY,
                              font=tkfont.Font(family=app.mono_family, size=app.fs(40), weight="bold"))
        self.clock.pack(pady=(18, 6))
        self.meter = tk.Canvas(w, height=int(14 * k), bg=CARD, highlightthickness=0)
        self.meter.pack(fill="x")
        self.msg = tk.Label(w, text="", bg=CARD, fg=MUTED, font=app.f_small, anchor="w", justify="left",
                            wraplength=int(420 * k))
        self.msg.pack(fill="x", pady=(8, 0))

        btns = tk.Frame(w, bg=CARD)
        btns.pack(fill="x", pady=(16, 0))
        self.main_btn = ttk.Button(btns, text="●  Kaydı başlat", style="Amber.TButton", command=self.toggle)
        self.main_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="■  Bitir", style="Navy.TButton", command=self.finish)
        self.discard_btn = ttk.Button(btns, text="Vazgeç", width=0, style="Ghost.TButton", command=self.discard)

        self.auto_var = tk.BooleanVar(value=bool(st.get("rec_autostart", True)))
        ttk.Checkbutton(w, text="Bitince hemen yazıya dök", variable=self.auto_var,
                        style="Light.TCheckbutton").pack(anchor="w", pady=(14, 0))
        foot = tk.Frame(w, bg=CARD)
        foot.pack(fill="x", pady=(6, 0))
        self.folder = st.get("rec_dir") or recorder.default_folder()
        self.folder_lbl = tk.Label(foot, text="", bg=CARD, fg=MUTED, font=app.f_small, anchor="w")
        self.folder_lbl.pack(side="left")
        ch = tk.Label(foot, text="Değiştir…", bg=CARD, fg=TS_FG, font=app.f_small, cursor="hand2")
        ch.pack(side="left", padx=(8, 0))
        ch.bind("<Button-1>", lambda e: self.pick_folder())
        self._show_folder()

        if not recorder.AVAILABLE or not self.devices:
            self.main_btn.configure(state="disabled")
            self.msg.configure(text="Bu bilgisayarda kayıt yapılabilecek bir mikrofon bulunamadı.", fg=RED)
        w.bind("<space>", lambda e: self.toggle())
        w.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - w.winfo_width()) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - w.winfo_height()) // 3
        w.geometry(f"+{max(0, x)}+{max(0, y)}")
        self._draw_meter()
        self._tick()

    # --- yardımcılar
    def _show_folder(self):
        home = os.path.expanduser("~")
        p = "~" + self.folder[len(home):] if self.folder.startswith(home) else self.folder
        self.folder_lbl.configure(text="Kayıtlar: " + (p if len(p) < 44 else "…" + p[-42:]))

    def pick_folder(self):
        if self.state != "idle":
            return
        d = filedialog.askdirectory(parent=self.win, title="Kayıtların saklanacağı klasör",
                                    initialdir=self.folder if os.path.isdir(self.folder) else os.path.expanduser("~"))
        if d:
            self.folder = d
            self.app.settings["rec_dir"] = d
            self._show_folder()

    def _device_index(self) -> Optional[int]:
        return next((i for i, n in self.devices if n == self.dev_var.get()), None)

    def _draw_meter(self):
        c = self.meter
        c.delete("all")
        w, h = max(c.winfo_width(), 10), max(c.winfo_height(), 6)
        round_rect(c, 0, 0, w, h, h // 2, fill=LINE, outline=LINE)
        if self.rec is not None and self.state == "recording":
            lvl, peak = self.rec.level, self.rec.peak
            fill = GREEN if lvl < 0.85 else RED
            if lvl > 0.02:
                round_rect(c, 0, 0, max(h, w * lvl), h, h // 2, fill=fill, outline=fill)
            px = w * peak
            c.create_line(px, 0, px, h, fill=NAVY, width=2)

    def _set_buttons(self):
        s = self.state
        if s == "idle":
            self.main_btn.configure(text="●  Kaydı başlat", style="Amber.TButton", state="normal")
            self.stop_btn.pack_forget()
            self.discard_btn.pack_forget()
            self.dev_cb.configure(state="readonly")
        elif s in ("recording", "paused"):
            self.main_btn.configure(text="❚❚  Duraklat" if s == "recording" else "▶  Devam et",
                                    style="Ghost.TButton", state="normal")
            if not self.stop_btn.winfo_ismapped():
                self.stop_btn.pack(side="left", padx=(8, 0))
                self.discard_btn.pack(side="right")
            self.dev_cb.configure(state="disabled")
        else:  # saving
            for b in (self.main_btn, self.stop_btn, self.discard_btn):
                b.configure(state="disabled")

    def _tick(self):
        if not self.win.winfo_exists():
            return
        if self.rec is not None and self.state in ("recording", "paused"):
            self.clock.configure(text=recorder.fmt_clock(self.rec.seconds),
                                 fg=NAVY if self.state == "recording" else MUTED)
            if self.rec.error:
                self.msg.configure(text=self.rec.error, fg=RED)
            elif (self.state == "recording" and not self._silent_warned and self.rec.seconds > 3
                  and self.rec.max_abs == 0):
                self._silent_warned = True
                self.msg.configure(text=recorder.permission_help(), fg=RED)
            elif self.state == "recording" and self.rec.max_abs > 0 and self._silent_warned:
                self._silent_warned = False
                self.msg.configure(text="Kaydediliyor…", fg=MUTED)
        self._draw_meter()
        self.win.after(60, self._tick)

    # --- işlemler
    def toggle(self):
        if self.state == "idle":
            self.start()
        elif self.state == "recording":
            self.rec.pause()
            self.state = "paused"
            self.msg.configure(text="Duraklatıldı. Devam etmek için “Devam et”e basın.", fg=MUTED)
        elif self.state == "paused":
            self.rec.resume()
            self.state = "recording"
            self.msg.configure(text="Kaydediliyor…", fg=MUTED)
        self._set_buttons()

    def start(self):
        try:
            os.makedirs(self.folder, exist_ok=True)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Kayıt klasörü oluşturulamadı:\n{e}", parent=self.win)
            return
        self.base_path = recorder.new_name(self.folder)
        self.rec = recorder.Recorder(self.base_path + ".wav", self._device_index())
        try:
            self.rec.start()
        except Exception as e:  # noqa: BLE001
            self.rec = None
            messagebox.showerror(APP_NAME, f"Kayıt başlatılamadı:\n{e}\n\n{recorder.permission_help()}",
                                 parent=self.win)
            return
        self.app.settings["rec_device"] = self.dev_var.get()
        self.state = "recording"
        self._silent_warned = False
        self.msg.configure(text="Kaydediliyor… (Boşluk tuşu: duraklat / devam)", fg=MUTED)
        self._set_buttons()
        self.app.status_var.set("Ses kaydediliyor…")

    def finish(self, then_close_app: bool = False):
        if self.rec is None or self.state not in ("recording", "paused"):
            return
        self.state = "saving"
        self._set_buttons()
        dur = self.rec.stop()
        if dur < 0.5:
            self.rec.discard()
            self.rec = None
            self.state = "idle"
            self._set_buttons()
            self.msg.configure(text="Kayıt çok kısa olduğu için saklanmadı.", fg=MUTED)
            return
        self.msg.configure(text="Kayıt kaydediliyor…", fg=MUTED)
        wav, m4a = self.rec.wav_path, self.base_path + ".m4a"
        auto = bool(self.auto_var.get())
        self.app.settings["rec_autostart"] = auto
        if then_close_app:      # uygulama kapanırken: beklemeden WAV olarak bırak
            return
        result: dict = {}

        def work():
            result["path"] = recorder.finalize(wav, m4a)

        t = threading.Thread(target=work, daemon=True)
        t.start()

        def wait():
            if t.is_alive():
                self.win.after(100, wait)
                return
            path = result.get("path", wav)
            self.rec = None
            self.state = "idle"
            self.app.on_recording_saved(path, dur, auto)
            self.win.destroy()

        wait()

    def discard(self):
        if self.rec is None:
            return
        if not messagebox.askyesno(APP_NAME, "Bu kayıt silinsin mi?", parent=self.win):
            return
        self.rec.discard()
        self.rec = None
        self.state = "idle"
        self.clock.configure(text="00:00:00", fg=NAVY)
        self.msg.configure(text="Kayıt silindi.", fg=MUTED)
        self._set_buttons()
        self.app.status_var.set("Hazır.")

    def busy(self) -> bool:
        return self.state in ("recording", "paused", "saving")

    def close(self):
        if self.state in ("recording", "paused"):
            ans = messagebox.askyesnocancel(
                APP_NAME, "Kayıt sürüyor.\n\nEvet: kaydı bitir ve sakla\nHayır: kaydı sil\nİptal: kayda devam et",
                parent=self.win)
            if ans is None:
                return
            if ans:
                self.finish()
                return
            self.rec.discard()
            self.rec = None
            self.state = "idle"
        if self.state == "saving":
            return
        self.win.destroy()


class TtsPanel:
    """Metinden sese ekranı."""

    def __init__(self, app: "App", parent: tk.Widget):
        self.app = app
        self.synth = tts.Synth()
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.cancel = threading.Event()
        self.audio: Optional[np.ndarray] = None   # int16
        self.sr = 22050
        self.peaks: Optional[np.ndarray] = None
        self.wave_ids: list[int] = []
        self.played = -1
        self.title = "seslendirme"
        self.speaker_vars: dict[str, tk.StringVar] = {}
        self._detect_job = None
        self._loading = False

        f = self.frame = tk.Frame(parent, bg=BG)
        self.voices = tts.all_voices()
        labels = [lbl for _, lbl in self.voices]

        head = tk.Frame(f, bg=BG)
        head.pack(fill="x")
        tools = tk.Frame(head, bg=BG)
        tools.pack(side="right")
        ttk.Button(tools, text="Okunuşu göster", width=0, style="Ghost.TButton", command=self.show_reading).pack(side="left")
        ttk.Button(tools, text="Telaffuz sözlüğü…", width=0, style="Ghost.TButton",
                   command=self.edit_lexicon).pack(side="left", padx=(8, 0))
        ttk.Button(tools, text="Dosyadan aç…", width=0, style="Ghost.TButton", command=self.open_file).pack(side="left", padx=(8, 0))
        ttk.Button(tools, text="Temizle", width=0, style="Ghost.TButton", command=self.clear).pack(side="left", padx=(8, 0))
        tk.Label(head, text="Metinden sese", bg=BG, fg=TEXT, font=app.f_title, anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(f, text="Metni yazın, yapıştırın ya da dosyadan açın. Seslendirme bilgisayarınızda yapılır.",
                 bg=BG, fg=MUTED, font=app.f_ui, anchor="w").pack(fill="x")

        # Ayarlar
        opt = tk.Frame(f, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=16, pady=12)
        opt.pack(fill="x", pady=(14, 12))
        row = tk.Frame(opt, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Ses", bg=CARD, fg=MUTED, font=app.f_ui).pack(side="left")
        self.voice_var = tk.StringVar(value=labels[0] if labels else "")
        key = app.settings.get("tts_voice")
        if key in dict(self.voices):
            self.voice_var.set(dict(self.voices)[key])
        self.voice_cb = ttk.Combobox(row, textvariable=self.voice_var, values=labels, state="readonly",
                                     style="Light.TCombobox", width=22, font=app.f_ui,
                                     postcommand=self._reload_voices)
        self.voice_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.voice_cb.pack(side="left", padx=(8, 22))
        tk.Label(row, text="Hız", bg=CARD, fg=MUTED, font=app.f_ui).pack(side="left")
        self.speed_var = tk.DoubleVar(value=float(app.settings.get("tts_speed", 1.0)))
        self.speed_lbl = tk.Label(row, text="", bg=CARD, fg=TEXT, font=app.f_ui_bold, width=5)
        ttk.Scale(row, from_=0.7, to=1.5, variable=self.speed_var, length=180, style="Light.Horizontal.TScale",
                  command=lambda v: self._speed_label()).pack(side="left", padx=(8, 6))
        self.speed_lbl.pack(side="left")
        self._speed_label()
        row2 = tk.Frame(opt, bg=CARD)
        row2.pack(fill="x", pady=(6, 0))
        self.note = tk.Label(row2, text="", bg=CARD, fg=MUTED, font=app.f_small, anchor="w")
        self.note.pack(side="left")
        self.howto_btn = ttk.Button(row2, text="Türkçe ses ekle…", width=0, style="Ghost.TButton",
                                    command=self.show_howto)
        self.spk_frame = tk.Frame(opt, bg=CARD)

        # Metin
        ed = tk.Frame(f, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        ed.pack(fill="both", expand=True)
        self.text = tk.Text(ed, wrap="word", undo=True, relief="flat", padx=22, pady=16, font=app.f_text, height=6,
                            spacing1=3, spacing3=9, background=CARD, foreground=TEXT, insertbackground=TEXT,
                            highlightthickness=0, borderwidth=0, selectbackground="#CFE0FB", selectforeground=TEXT)
        sb = ttk.Scrollbar(ed, orient="vertical", command=self.text.yview, style="Light.Vertical.TScrollbar")
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        for i, color in enumerate(SPEAKER_COLORS):
            self.text.tag_configure(f"spk{i}", font=app.f_spk, foreground=color)
        self.text.bind("<<Modified>>", self._on_modified)

        # Çalıştırma
        act = tk.Frame(f, bg=BG)
        act.pack(fill="x", pady=(12, 0))
        self.go_btn = ttk.Button(act, text="Sese çevir", style="Amber.TButton", command=self.start)
        self.go_btn.pack(side="left")
        prog = tk.Frame(act, bg=BG)
        prog.pack(side="left", fill="x", expand=True, padx=(16, 0))
        self.status = tk.Label(prog, text="", bg=BG, fg=MUTED, font=app.f_small, anchor="w")
        self.status.pack(fill="x")
        self.pbar = ttk.Progressbar(prog, mode="determinate", maximum=1000, style="Light.Horizontal.TProgressbar")

        # Çalar
        pl = tk.Frame(f, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=16, pady=12)
        pl.pack(fill="x", pady=(12, 0))
        self.play_c = tk.Canvas(pl, width=46, height=46, bg=CARD, highlightthickness=0, cursor="hand2")
        self.play_c.pack(side="left")
        self.play_c.bind("<Button-1>", lambda e: self.toggle_play())
        self.save_btn = ttk.Menubutton(pl, text="Kaydet", width=0, style="Navy.TMenubutton")
        m = tk.Menu(self.save_btn, tearoff=False)
        m.add_command(label="M4A (.m4a)", command=lambda: self.save(".m4a"))
        m.add_command(label="WAV (.wav)", command=lambda: self.save(".wav"))
        self.save_btn["menu"] = m
        self.save_btn.pack(side="right")
        self.time_var = tk.StringVar(value="00:00 / 00:00")
        tk.Label(pl, textvariable=self.time_var, bg=CARD, fg=MUTED, font=app.f_mono).pack(side="right", padx=(0, 14))
        self.wave = tk.Canvas(pl, height=46, bg=CARD, highlightthickness=0, cursor="hand2")
        self.wave.pack(side="left", fill="x", expand=True, padx=16)
        self.wave.bind("<Configure>", lambda e: self.draw_wave())
        self.wave.bind("<Button-1>", self._wave_click)

        self._placeholder(True)
        app.root.after(100, self._poll)
        self.refresh()

    # --- yardımcılar
    def voice_key(self) -> str:
        for k, lbl in self.voices:
            if lbl == self.voice_var.get():
                return k
        return self.voices[0][0] if self.voices else ""

    def _reload_voices(self):
        """Ses listesini tazeler (kullanıcı bilgisayara yeni bir Türkçe ses yüklemiş olabilir)."""
        current = self.voice_key()
        self.voices = tts.all_voices()
        self.voice_cb.configure(values=[lbl for _, lbl in self.voices])
        self.voice_var.set(dict(self.voices).get(current, self.voices[0][1] if self.voices else ""))

    # --- telaffuz
    def lexicon(self) -> tuple[dict, bool]:
        import trnorm
        return (trnorm.parse_lexicon(self.app.settings.get("tts_lexicon", "")),
                bool(self.app.settings.get("tts_default_lexicon", True)))

    def edit_lexicon(self):
        import trnorm
        app = self.app
        k = app.ui_scale
        win = tk.Toplevel(app.root, bg=CARD, padx=int(24 * k), pady=int(20 * k))
        win.title("Telaffuz sözlüğü")
        win.transient(app.root)
        tk.Label(win, text="Telaffuz sözlüğü", bg=CARD, fg=TEXT, font=app.f_title, anchor="w").pack(fill="x")
        tk.Label(win, text="Yanlış okunan kelimeleri, okunmasını istediğiniz gibi yazın. Her satıra bir kelime:\n"
                           "yazılış = okunuş      (örnek:  KDV = ka de ve   ·   Altınbaş = altınbaş)\n"
                           "Ekler korunur: “WhatsApp'tan” → “vatsaptan”. Tüm seslere uygulanır.",
                 bg=CARD, fg=MUTED, font=app.f_small, justify="left", anchor="w").pack(fill="x", pady=(4, 10))
        box = tk.Frame(win, bg=CARD, highlightthickness=1, highlightbackground=LINE_STRONG)
        box.pack(fill="both", expand=True)
        txt = tk.Text(box, width=56, height=12, font=app.f_mono, relief="flat", padx=10, pady=8,
                      bg=CARD, fg=TEXT, insertbackground=TEXT, highlightthickness=0, undo=True)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", app.settings.get("tts_lexicon", ""))
        use_def = tk.BooleanVar(value=bool(app.settings.get("tts_default_lexicon", True)))
        ttk.Checkbutton(win, text="Hazır yabancı kelime okunuşlarını da kullan", variable=use_def,
                        style="Light.TCheckbutton").pack(anchor="w", pady=(10, 0))
        sample = ", ".join(f"{a} → {b}" for a, b in list(trnorm.DEFAULT_LEXICON.items())[:8])
        tk.Label(win, text=f"({sample} …)", bg=CARD, fg=MUTED, font=app.f_small, anchor="w",
                 wraplength=int(520 * k), justify="left").pack(fill="x")
        row = tk.Frame(win, bg=CARD)
        row.pack(fill="x", pady=(14, 0))

        def save():
            app.settings["tts_lexicon"] = txt.get("1.0", "end").strip()
            app.settings["tts_default_lexicon"] = bool(use_def.get())
            save_settings(app._collect_settings())
            n = len(trnorm.parse_lexicon(app.settings["tts_lexicon"]))
            self.status.configure(text=f"Telaffuz sözlüğü kaydedildi ({n} kelime).")
            win.destroy()

        ttk.Button(row, text="Kaydet", style="Navy.TButton", command=save).pack(side="right")
        ttk.Button(row, text="Vazgeç", style="Ghost.TButton", command=win.destroy).pack(side="right", padx=8)
        txt.focus_set()
        self._lex_win = win

    def show_reading(self):
        """Metnin seslendirmede nasıl okunacağını gösterir (sayılar, kısaltmalar, sözlük uygulanmış hâli)."""
        text = self.get_text()
        if not text:
            messagebox.showinfo(APP_NAME, "Önce seslendirilecek metni yazın.")
            return
        lex, use_def = self.lexicon()
        lines = []
        for ln in text.splitlines():
            m = tts._SPK_RE.match(ln.strip())
            if m and m.group(1).strip() in self.speaker_vars:
                lines.append(f"{m.group(1).strip()}: {tts.normalize(m.group(2), lex, use_def)}")
            else:
                lines.append(tts.normalize(ln, lex, use_def) if ln.strip() else "")
        app = self.app
        win = tk.Toplevel(app.root, bg=CARD)
        win.title("Okunuş")
        win.geometry(f"{int(720 * app.ui_scale)}x{int(480 * app.ui_scale)}")
        tk.Label(win, text="Seslendirmede okunacak metin (sayılar, kısaltmalar ve sözlüğünüz uygulanmış hâli). "
                           "Yanlış görünen bir kelimeyi Telaffuz sözlüğüne ekleyebilirsiniz.",
                 bg=CARD, fg=MUTED, font=app.f_small, anchor="w", justify="left",
                 wraplength=int(680 * app.ui_scale)).pack(fill="x", padx=18, pady=(14, 6))
        box = tk.Frame(win, bg=CARD)
        box.pack(fill="both", expand=True, padx=2, pady=2)
        t = tk.Text(box, wrap="word", font=app.f_text, bg=CARD, fg=TEXT, relief="flat", padx=18, pady=10,
                    highlightthickness=0, borderwidth=0, spacing3=6)
        sb = ttk.Scrollbar(box, orient="vertical", command=t.yview, style="Light.Vertical.TScrollbar")
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        t.insert("1.0", "\n".join(lines))
        t.configure(state="disabled")
        ttk.Button(win, text="Telaffuz sözlüğü…", style="Ghost.TButton", width=0,
                   command=lambda: (win.destroy(), self.edit_lexicon())).pack(side="left", padx=18, pady=(4, 14))
        ttk.Button(win, text="Kapat", style="Navy.TButton", width=0, command=win.destroy).pack(side="right", padx=18, pady=(4, 14))
        self._read_win = win

    def show_howto(self):
        if IS_WINDOWS:
            import winplat
            messagebox.showinfo(APP_NAME, winplat.SPEECH_HOWTO)
            return
        messagebox.showinfo(
            APP_NAME,
            "Yelda, Apple'ın ücretsiz Türkçe kadın sesidir. Eklemek için:\n\n"
            "1. Sistem Ayarları › Erişilebilirlik › Seslendirilen İçerik'i açın.\n"
            "2. “Sistem sesi”nin yanındaki menüden “Sesleri Yönet…”i seçin.\n"
            "3. Listeden Türkçe'yi bulun, Yelda'nın yanındaki indirme simgesine tıklayın "
            "(“Gelişmiş” ya da “Premium” sürüm daha doğal konuşur).\n"
            "4. İndirme bitince bu ekrandaki Ses listesini açın; Yelda listede görünür.\n\n"
            "Mac sesleri internete bağlanmadan, bilgisayarınızda çalışır.")

    def _speed_label(self):
        self.speed_lbl.configure(text=f"{self.speed_var.get():.1f}×".replace(".", ","))

    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _placeholder(self, on: bool):
        self._loading = True
        if on:
            self.text.delete("1.0", "end")
            self.text.insert("1.0", "Seslendirmek istediğiniz metni buraya yazın ya da yapıştırın.\n\n"
                                    "Konuşmalı metinlerde satırları “Ad: metin” biçiminde yazarsanız "
                                    "her konuşmacıya ayrı ses verebilirsiniz.")
            self.text.configure(foreground=MUTED)
            self.text.bind("<FocusIn>", lambda e: self._placeholder(False) if self._is_placeholder else None)
            self._is_placeholder = True
        else:
            self.text.delete("1.0", "end")
            self.text.configure(foreground=TEXT)
            self._is_placeholder = False
        self.text.edit_modified(False)
        self._loading = False

    def get_text(self) -> str:
        return "" if self._is_placeholder else self.text.get("1.0", "end").strip()

    def set_text(self, text: str, title: str = "seslendirme"):
        self._placeholder(False)
        self._loading = True
        self.text.insert("1.0", text)
        self.text.edit_modified(False)
        self._loading = False
        self.title = title
        self.clear_audio()
        self._detect()

    def clear(self):
        if self.busy():
            return
        self._placeholder(True)
        self.title = "seslendirme"
        self.clear_audio()
        self._detect()

    def clear_audio(self):
        self.app.player.stop()
        self.app.player.paused_at = None
        self.audio, self.peaks = None, None
        self.time_var.set("00:00 / 00:00")
        self.draw_wave()
        self.refresh()

    def open_file(self):
        path = filedialog.askopenfilename(title="Metin dosyası seç",
                                          filetypes=[("Metin ve Word", "*.txt *.md *.docx"), ("Tüm dosyalar", "*.*")])
        if not path:
            return
        try:
            self.set_text(tts.read_text_file(path), os.path.splitext(os.path.basename(path))[0])
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Dosya açılamadı:\n{e}")

    def _on_modified(self, _e=None):
        if self._loading:
            self.text.edit_modified(False)
            return
        if self.text.edit_modified():
            self.text.edit_modified(False)
            if self._detect_job:
                self.app.root.after_cancel(self._detect_job)
            self._detect_job = self.app.root.after(600, self._detect)

    def _detect(self):
        """Metindeki konuşmacıları bulur ve her birine ses seçimi gösterir."""
        self._detect_job = None
        names = tts.detect_speakers(self.get_text())
        old = {n: v.get() for n, v in self.speaker_vars.items()}
        for w in self.spk_frame.winfo_children():
            w.destroy()
        self.speaker_vars = {}
        for i in range(len(SPEAKER_COLORS)):
            self.text.tag_remove(f"spk{i}", "1.0", "end")
        if not names:
            self.spk_frame.pack_forget()
            return
        self.spk_frame.pack(fill="x", pady=(10, 0))
        tk.Label(self.spk_frame, text="Konuşmacı sesleri", bg=CARD, fg=MUTED, font=self.app.f_ui).grid(
            row=0, column=0, sticky="w", padx=(0, 12))
        labels = [lbl for _, lbl in self.voices]
        defaults = [lbl for _, lbl in tts.distinct_voices(self.voices)]
        for i, n in enumerate(names[:6]):
            var = tk.StringVar(value=old.get(n, defaults[i % len(defaults)] if defaults else ""))
            self.speaker_vars[n] = var
            cell = tk.Frame(self.spk_frame, bg=CARD)
            cell.grid(row=i // 2, column=1 + i % 2, sticky="w", padx=(0, 14), pady=2)
            tk.Label(cell, text=n, bg=CARD, fg=SPEAKER_COLORS[i % len(SPEAKER_COLORS)], font=self.app.f_ui_bold).pack(side="left")
            ttk.Combobox(cell, textvariable=var, values=labels, state="readonly", width=17,
                         style="Light.TCombobox", font=self.app.f_ui).pack(side="left", padx=(6, 0))
        last = int(self.text.index("end-1c").split(".")[0])
        for ln in range(1, last + 1):
            line = self.text.get(f"{ln}.0", f"{ln}.end")
            for i, n in enumerate(self.speaker_vars):
                if line.startswith(n + ":"):
                    self.text.tag_add(f"spk{i % len(SPEAKER_COLORS)}", f"{ln}.0", f"{ln}.{len(n) + 1}")
                    break

    # --- seslendirme
    def start(self):
        if self.busy():
            self.cancel.set()
            self.status.configure(text="İptal ediliyor…")
            return
        text = self.get_text()
        if not self.voice_key():
            self.show_howto()
            return
        if not text:
            messagebox.showinfo(APP_NAME, "Önce seslendirilecek metni yazın.")
            return
        mapping = {}
        for n, var in self.speaker_vars.items():
            mapping[n] = next((k for k, lbl in self.voices if lbl == var.get()), self.voice_key())
        lex, use_def = self.lexicon()
        parts = tts.script(text, self.voice_key(), mapping, lex, use_def)
        if not parts:
            messagebox.showinfo(APP_NAME, "Seslendirilecek metin bulunamadı.")
            return
        self.clear_audio()
        self.cancel.clear()
        speed = float(self.speed_var.get())
        self.pbar.pack(fill="x", pady=(4, 0))
        self.pbar.configure(value=0)
        self.status.configure(text="Hazırlanıyor…")

        def work():
            try:
                audio, sr = self.synth.synthesize(
                    parts, speed,
                    on_status=lambda m: self.events.put(("status", m)),
                    on_progress=lambda f: self.events.put(("progress", f)),
                    cancel=self.cancel)
                self.events.put(("done", audio, sr))
            except engine.Cancelled:
                self.events.put(("cancelled",))
            except Exception as e:  # noqa: BLE001
                self.events.put(("error", str(e)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.refresh()

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "status":
                    self.status.configure(text=ev[1])
                elif kind == "progress":
                    self.pbar.configure(value=int(ev[1] * 1000))
                    self.status.configure(text=f"Seslendiriliyor… %{int(ev[1] * 100)}")
                elif kind == "done":
                    audio, sr = ev[1], ev[2]
                    self.audio = (audio * 32767).astype(np.int16)
                    self.sr = sr
                    self.peaks = App._compute_peaks(self.audio)
                    dur = len(self.audio) / sr
                    self.time_var.set(f"00:00 / {fmt_mmss(dur)}")
                    self.status.configure(text=f"Hazır · {fmt_duration(dur)} ses. Dinleyebilir ya da kaydedebilirsiniz.")
                    self.pbar.pack_forget()
                    self.worker = None
                    self.draw_wave()
                elif kind == "cancelled":
                    self.status.configure(text="İptal edildi.")
                    self.pbar.pack_forget()
                    self.worker = None
                elif kind == "error":
                    self.status.configure(text="Seslendirilemedi.")
                    self.pbar.pack_forget()
                    self.worker = None
                    messagebox.showerror(APP_NAME, ev[1])
                self.refresh()
        except queue.Empty:
            pass
        if self.app.mode == "tts" and self.app.player.playing and self.audio is not None:
            dur = len(self.audio) / self.sr
            pos = self.app.player.position()
            if pos >= dur:
                self.app.player.stop()
                self.app.player.paused_at = None
                self._wave_progress(0)
                self.time_var.set(f"00:00 / {fmt_mmss(dur)}")
                self.refresh()
            else:
                self._wave_progress(pos / dur)
                self.time_var.set(f"{fmt_mmss(pos)} / {fmt_mmss(dur)}")
        self.app.root.after(100, self._poll)

    def refresh(self):
        busy = self.busy()
        has_audio = self.audio is not None
        self.go_btn.configure(text="İptal et" if busy else "Sese çevir",
                              style="Side.TButton" if busy else "Amber.TButton", state="normal")
        self.save_btn.configure(state="normal" if has_audio and not busy else "disabled")
        self.voice_cb.configure(state="disabled" if busy else "readonly")
        key = self.voice_key()
        if not key:
            self.note.configure(text="Bu bilgisayarda Türkçe ses yüklü değil; “Türkçe ses ekle…” adımlarını izleyin.",
                                fg="#9A5B00")
            self.go_btn.configure(state="disabled")
        elif tts.is_system(key):
            self.note.configure(text=f"{OS_OWN} kendi sesi · indirme gerekmez, bilgisayarınızda çalışır", fg=GREEN)
        elif tts.voice_ready(key):
            self.note.configure(text="Ses indirildi · bilgisayarınızda çalışır", fg=GREEN)
        else:
            self.note.configure(text=f"Bu ses ilk kullanımda indirilir (~{tts.VOICE_SIZE_MB} MB, bir kerelik)", fg="#9A5B00")
        # Mac'te Türkçe sistem sesi yoksa nasıl ekleneceğini göster
        no_system = (IS_MAC or IS_WINDOWS) and not any(tts.is_system(k) for k, _ in self.voices)
        if no_system and not self.howto_btn.winfo_ismapped():
            self.howto_btn.pack(side="left", padx=(12, 0))
        elif not no_system and self.howto_btn.winfo_ismapped():
            self.howto_btn.pack_forget()
        self._draw_play()

    # --- dinleme
    def _draw_play(self):
        c = self.play_c
        c.delete("all")
        enabled = self.audio is not None and AUDIO_OK
        fill = AMBER if enabled else LINE
        c.create_oval(1, 1, 45, 45, fill=fill, outline=fill)
        col = NAVY if enabled else "#A3ABBB"
        if self.app.player.playing and self.app.mode == "tts":
            c.create_rectangle(17, 15, 21, 31, fill=col, width=0)
            c.create_rectangle(25, 15, 29, 31, fill=col, width=0)
        else:
            c.create_polygon(19, 14, 19, 32, 33, 23, fill=col, outline=col)

    def toggle_play(self):
        if self.audio is None or not AUDIO_OK:
            return
        p = self.app.player
        if p.playing:
            p.pause()
        else:
            p.play(self.audio, p.paused_at or 0.0, self.sr)
        self._draw_play()

    def _wave_click(self, e):
        if self.audio is None or not AUDIO_OK:
            return
        frac = max(0.0, min(1.0, e.x / max(1, self.wave.winfo_width())))
        self.app.player.play(self.audio, frac * len(self.audio) / self.sr, self.sr)
        self._draw_play()

    def draw_wave(self):
        c = self.wave
        c.delete("all")
        self.wave_ids, self.played = [], -1
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20:
            return
        if self.peaks is None:
            c.create_line(0, h / 2, w, h / 2, fill=LINE_STRONG, width=2, dash=(3, 4))
            t = c.create_text(w / 2, h / 2 - 1, text="Seslendirme bitince burada dinleyebilirsiniz", fill=MUTED,
                              font=self.app.f_small)
            x1, y1, x2, y2 = c.bbox(t)
            c.tag_lower(c.create_rectangle(x1 - 10, y1, x2 + 10, y2, fill=CARD, width=0), t)
            return
        n = max(1, w // 6)
        idx = (np.arange(n) * len(self.peaks) / n).astype(int)
        for i, v in enumerate(self.peaks[idx]):
            bh = max(3, v * (h - 4))
            x = i * 6 + 2
            self.wave_ids.append(c.create_rectangle(x, (h - bh) / 2, x + 3, (h + bh) / 2, fill=LINE_STRONG, width=0))

    def _wave_progress(self, frac: float):
        if not self.wave_ids:
            return
        k = int(max(0.0, min(1.0, frac)) * len(self.wave_ids))
        if k == self.played:
            return
        for i, rid in enumerate(self.wave_ids):
            self.wave.itemconfigure(rid, fill=AMBER if i < k else LINE_STRONG)
        self.played = k

    def save(self, ext: str):
        if self.audio is None:
            return
        path = filedialog.asksaveasfilename(title="Sesi kaydet", defaultextension=ext,
                                            initialfile=self.title + ext,
                                            initialdir=self.app.settings.get("export_dir") or os.path.expanduser("~"),
                                            filetypes=[("Ses dosyası", "*" + ext)])
        if not path:
            return
        try:
            tts.save_audio(path, self.audio.astype(np.float32) / 32767, self.sr)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Kaydedilemedi:\n{e}")
            return
        self.app.settings["export_dir"] = os.path.dirname(path)
        self.status.configure(text=f"Kaydedildi: {os.path.basename(path)}")


class SummaryPanel:
    """Özetle ekranı: metni kullanıcının kendi yapay zekâ hesabıyla özetler (metin dışarı gönderilir)."""

    def __init__(self, app: "App", parent: tk.Widget):
        self.app = app
        st = app.settings
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.cancel = threading.Event()
        self.title = "özet"
        k = app.ui_scale

        f = self.frame = tk.Frame(parent, bg=BG)
        head = tk.Frame(f, bg=BG)
        head.pack(fill="x")
        tools = tk.Frame(head, bg=BG)
        tools.pack(side="right")
        ttk.Button(tools, text="Yapay zekâ ayarları…", width=0, style="Ghost.TButton",
                   command=self.open_settings).pack(side="left")
        ttk.Button(tools, text="Dosyadan aç…", width=0, style="Ghost.TButton",
                   command=self.open_file).pack(side="left", padx=(8, 0))
        ttk.Button(tools, text="Temizle", width=0, style="Ghost.TButton", command=self.clear).pack(side="left", padx=(8, 0))
        tk.Label(head, text="Özetle", bg=BG, fg=TEXT, font=app.f_title, anchor="w").pack(side="left", fill="x", expand=True)
        self.sub = tk.Label(f, text="", bg=BG, fg=MUTED, font=app.f_ui, anchor="w")
        self.sub.pack(fill="x")

        # Seçenekler
        opt = tk.Frame(f, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=16, pady=12)
        opt.pack(fill="x", pady=(14, 0))
        row = tk.Frame(opt, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Özet türü", bg=CARD, fg=MUTED, font=app.f_ui).pack(side="left")
        self.kind_var = tk.StringVar(value=dict(ai.SUMMARY_TYPES).get(st.get("ai_kind", "points"),
                                                                      ai.SUMMARY_TYPES[1][1]))
        ttk.Combobox(row, textvariable=self.kind_var, values=[l for _, l in ai.SUMMARY_TYPES], state="readonly",
                     style="Light.TCombobox", width=34, font=app.f_ui).pack(side="left", padx=(8, 22))
        tk.Label(row, text="Dil", bg=CARD, fg=MUTED, font=app.f_ui).pack(side="left")
        self.lang_var = tk.StringVar(value=dict(ai.LANGUAGES).get(st.get("ai_lang", "tr"), "Türkçe"))
        ttk.Combobox(row, textvariable=self.lang_var, values=[l for _, l in ai.LANGUAGES], state="readonly",
                     style="Light.TCombobox", width=14, font=app.f_ui).pack(side="left", padx=(8, 0))
        row2 = tk.Frame(opt, bg=CARD)
        row2.pack(fill="x", pady=(10, 0))
        tk.Label(row2, text="Ek istek", bg=CARD, fg=MUTED, font=app.f_ui).pack(side="left")
        eb = tk.Frame(row2, bg=CARD, highlightthickness=1, highlightbackground=LINE_STRONG, highlightcolor=AMBER)
        eb.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.extra = tk.Entry(eb, font=app.f_ui, relief="flat", bg=CARD, fg=TEXT, insertbackground=TEXT,
                              highlightthickness=0, borderwidth=0)
        self.extra.pack(fill="x", padx=8, pady=5)
        self._extra_ph = False
        self.extra.bind("<FocusIn>", lambda e: self._extra_placeholder(False))
        self.extra.bind("<FocusOut>", lambda e: self._extra_placeholder(True))
        self._extra_placeholder(True)
        # Kalıcı veri uyarısı
        self.warn = tk.Label(opt, text="", bg="#FFF6E6", fg="#7A4A00", font=app.f_small, anchor="w", justify="left",
                             padx=10, pady=6)
        self.warn.pack(fill="x", pady=(10, 0))
        opt.bind("<Configure>", lambda e: self.warn.configure(wraplength=max(200, e.width - 50)))

        # Metin | Özet
        panes = tk.PanedWindow(f, orient="horizontal", bg=BG, sashwidth=int(10 * k), borderwidth=0, sashrelief="flat")
        panes.pack(fill="both", expand=True, pady=(12, 0))
        self.src, self.src_lbl = self._text_card(panes, "METİN")
        self.out, self.out_lbl = self._text_card(panes, "ÖZET")
        self.src.bind("<<Modified>>", self._src_modified)
        self.out.tag_configure("h", font=app.f_spk, foreground=NAVY, spacing1=8)
        self.out.tag_configure("b", font=app.f_spk)

        # Çalıştırma
        act = tk.Frame(f, bg=BG)
        act.pack(fill="x", pady=(12, 0))
        self.go_btn = ttk.Button(act, text="Özetle", style="Amber.TButton", command=self.start, width=12)
        self.go_btn.pack(side="left")
        right = tk.Frame(act, bg=BG)
        right.pack(side="right")
        self.copy_btn = ttk.Button(right, text="Kopyala", width=0, style="Ghost.TButton", command=self.copy)
        self.copy_btn.pack(side="left")
        self.speak_btn = ttk.Button(right, text="Seslendir", width=0, style="Ghost.TButton", command=self.speak)
        self.speak_btn.pack(side="left", padx=(8, 0))
        self.save_btn = ttk.Menubutton(right, text="Kaydet", width=0, style="Navy.TMenubutton")
        m = tk.Menu(self.save_btn, tearoff=False)
        for label, ext in (("Word (.docx)", ".docx"), ("PDF (.pdf)", ".pdf"), ("Metin (.txt)", ".txt"),
                           ("Markdown (.md)", ".md")):
            m.add_command(label=label, command=lambda e=ext: self.save(e))
        self.save_btn["menu"] = m
        self.save_btn.pack(side="left", padx=(8, 0))
        prog = tk.Frame(act, bg=BG)
        prog.pack(side="left", fill="x", expand=True, padx=16)
        self.status = tk.Label(prog, text="", bg=BG, fg=MUTED, font=app.f_small, anchor="w")
        self.status.pack(fill="x")
        self.pbar = ttk.Progressbar(prog, mode="indeterminate", style="Light.Horizontal.TProgressbar")

        app.root.after(100, self._poll)
        self.refresh()

    # --- yardımcılar
    def _text_card(self, panes, label):
        app = self.app
        card = tk.Frame(panes, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        lbl = tk.Label(card, text=label, bg=CARD, fg=MUTED, font=app.f_caps, anchor="w", padx=16, pady=8)
        lbl.pack(fill="x")
        box = tk.Frame(card, bg=CARD)
        box.pack(fill="both", expand=True)
        t = tk.Text(box, wrap="word", undo=True, relief="flat", padx=16, pady=6, font=app.f_text, height=6, width=20,
                    spacing1=2, spacing3=7, background=CARD, foreground=TEXT, insertbackground=TEXT,
                    highlightthickness=0, borderwidth=0, selectbackground="#CFE0FB", selectforeground=TEXT)
        sb = ttk.Scrollbar(box, orient="vertical", command=t.yview, style="Light.Vertical.TScrollbar")
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        panes.add(card, stretch="always", minsize=int(220 * app.ui_scale))
        return t, lbl

    def _extra_placeholder(self, on: bool):
        e = self.extra
        if on and not e.get().strip():
            e.delete(0, "end")
            e.insert(0, "İsteğe bağlı · ör. “öğrenciler için sade bir dille”, “en fazla 5 madde”")
            e.configure(fg="#A3ABBB")
            self._extra_ph = True
        elif not on and self._extra_ph:
            e.delete(0, "end")
            e.configure(fg=TEXT)
            self._extra_ph = False

    def _extra_text(self) -> str:
        return "" if self._extra_ph else self.extra.get().strip()

    def provider(self) -> ai.Provider:
        return ai.PROVIDER_BY_KEY.get(self.app.settings.get("ai_provider", "anthropic"), ai.PROVIDERS[0])

    def model(self) -> str:
        p = self.provider()
        return (self.app.settings.get("ai_models") or {}).get(p.key) or p.models[0][0]

    def _kind(self) -> str:
        return next((k for k, l in ai.SUMMARY_TYPES if l == self.kind_var.get()), "points")

    def _lang(self) -> str:
        return next((k for k, l in ai.LANGUAGES if l == self.lang_var.get()), "tr")

    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def get_text(self) -> str:
        return self.src.get("1.0", "end").strip()

    def summary_md(self) -> str:
        """Ekrandaki (biçimlendirilmiş, düzenlenebilir) özeti sade Markdown'a geri çevirir."""
        o = self.out
        last = int(o.index("end-1c").split(".")[0])
        lines = []
        for ln in range(1, last + 1):
            text = o.get(f"{ln}.0", f"{ln}.end")
            if not text.strip():
                lines.append("")
                continue
            # kalın aralıkları ** ile geri sar (sondan başa, konumlar kaymasın)
            ranges = o.tag_ranges("b")
            spans = []
            for a, b in zip(ranges[0::2], ranges[1::2]):
                la, ca = map(int, str(a).split("."))
                lb, cb = map(int, str(b).split("."))
                if la == ln:
                    spans.append((ca, cb if lb == ln else len(text)))
            is_head = "h" in o.tag_names(f"{ln}.0") and not text.startswith("• ")
            for ca, cb in sorted(spans, reverse=True):
                if not is_head:
                    text = text[:ca] + "**" + text[ca:cb] + "**" + text[cb:]
            if is_head:
                text = "## " + text
            elif text.startswith("• "):
                text = "- " + text[2:]
            lines.append(text)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    def set_text(self, text: str, title: str = "özet"):
        self.src.delete("1.0", "end")
        self.src.insert("1.0", text)
        self.src.edit_modified(False)
        self.title = title or "özet"
        self._src_modified()
        self.refresh()

    def _src_modified(self, _e=None):
        self.src.edit_modified(False)
        t = self.get_text()
        words = len(t.split())
        self.src_lbl.configure(text=f"METİN · {words:,} kelime".replace(",", ".") if t else "METİN")

    def _render(self, md: str):
        """Özeti biçimli gösterir (başlık, madde, kalın; işaretler gizli). Metin düzenlenebilir kalır."""
        o = self.out
        o.delete("1.0", "end")
        first = True
        for raw in md.strip().splitlines():
            line = raw.rstrip()
            if not first:
                o.insert("end", "\n")
            first = False
            if not line.strip():
                continue
            m = re.match(r"^\s*#{1,4}\s+(.*)$", line)
            if m:
                o.insert("end", re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(1)), ("h",))
                continue
            m = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$", line)
            if m and not re.match(r"^\s*\d+[.)]", line):
                o.insert("end", "• ")
                line = m.group(1)
            pos = 0
            for bm in re.finditer(r"\*\*(.+?)\*\*", line):
                o.insert("end", line[pos:bm.start()])
                o.insert("end", bm.group(1), ("b",))
                pos = bm.end()
            o.insert("end", line[pos:])

    # --- metin kaynakları
    def open_file(self):
        path = filedialog.askopenfilename(
            title="Özetlenecek dosyayı seç", initialdir=self.app.settings.get("last_dir") or os.path.expanduser("~"),
            filetypes=[("Metin, Word, PDF", "*.txt *.md *.docx *.pdf"), ("Tüm dosyalar", "*.*")])
        if not path:
            return
        try:
            if path.lower().endswith(".pdf"):
                self.status.configure(text="PDF okunuyor…")
                self.app.root.update_idletasks()
                pages = converters._pdf_blocks(path, lambda f, m: None, None)
                text = "\n\n".join(b.text for p in pages for b in p)
                if len(text.strip()) < 20:
                    raise RuntimeError("Bu PDF'te seçilebilir yazı yok (taranmış olabilir). Önce Dönüştür › "
                                       "“Taranmış belge → metin” ile metne çevirin.")
            else:
                text = tts.read_text_file(path)
        except Exception as e:  # noqa: BLE001
            self.status.configure(text="")
            messagebox.showerror(APP_NAME, f"Dosya okunamadı:\n{e}")
            return
        self.app.settings["last_dir"] = os.path.dirname(path)
        self.set_text(text, os.path.splitext(os.path.basename(path))[0])
        self.status.configure(text=f"Açıldı: {os.path.basename(path)}")

    def clear(self):
        if self.busy():
            return
        self.set_text("", "özet")
        self.out.delete("1.0", "end")
        self.status.configure(text="")
        self.refresh()

    # --- onay ve ayarlar
    def _consent(self, p: ai.Provider) -> bool:
        consents = self.app.settings.setdefault("ai_consent", {})
        if consents.get(p.key):
            return True
        app = self.app
        k = app.ui_scale
        win = tk.Toplevel(app.root, bg=CARD, padx=int(26 * k), pady=int(22 * k))
        win.title("Metin dışarı gönderilecek")
        win.transient(app.root)
        win.resizable(False, False)
        tk.Label(win, text="Metin dışarı gönderilecek", bg=CARD, fg=TEXT, font=app.f_title, anchor="w").pack(fill="x")
        tk.Label(win, text=(f"Özetlemek için bu metin, sizin API anahtarınızla {p.company_gen} yapay zekâ hizmeti "
                            f"{p.product_dat} gönderilecek ve orada işlenecek. Bu işlem için internet gerekir; "
                            f"{p.company_gen} veri kullanım koşulları geçerlidir.\n\n"
                            "Trafyle'ın diğer tüm işlemleri (yazıya dökme, seslendirme, dönüştürme) bilgisayarınızda "
                            "kalır ve hiçbir yere gönderilmez.\n\n"
                            "Kişisel ya da gizli bilgi içeren metinleri göndermeden önce dikkatli olun."),
                 bg=CARD, fg=TEXT, font=app.f_ui, justify="left", anchor="w",
                 wraplength=int(480 * k)).pack(fill="x", pady=(10, 0))
        never = tk.BooleanVar(value=False)
        ttk.Checkbutton(win, text=f"{p.name} için bir daha sorma", variable=never,
                        style="Light.TCheckbutton").pack(anchor="w", pady=(14, 0))
        res = {"ok": False}
        row = tk.Frame(win, bg=CARD)
        row.pack(fill="x", pady=(16, 0))

        def ok():
            res["ok"] = True
            if never.get():
                consents[p.key] = True
                save_settings(app._collect_settings())
            win.destroy()

        ttk.Button(row, text="Gönder ve özetle", style="Amber.TButton", command=ok).pack(side="right")
        ttk.Button(row, text="Vazgeç", style="Ghost.TButton", command=win.destroy).pack(side="right", padx=8)
        win.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - win.winfo_width()) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        self._consent_win = win
        win.grab_set()
        app.root.wait_window(win)
        return res["ok"]

    def open_settings(self):
        app = self.app
        k = app.ui_scale
        st = app.settings
        win = tk.Toplevel(app.root, bg=CARD, padx=int(26 * k), pady=int(22 * k))
        win.title("Yapay zekâ ayarları")
        win.transient(app.root)
        win.resizable(False, False)
        tk.Label(win, text="Yapay zekâ ayarları", bg=CARD, fg=TEXT, font=app.f_title, anchor="w").pack(fill="x")
        tk.Label(win, text="Özetleme, sizin seçtiğiniz yapay zekâ hizmetinde kendi API anahtarınızla yapılır. "
                           "Ücreti hizmet sağlayıcıya kullandıkça ödersiniz (bir saatlik toplantı genelde birkaç "
                           "sent ile birkaç on sent arası). Sohbet abonelikleri (ChatGPT Plus, Claude Pro vb.) "
                           "API kullanımını kapsamaz.",
                 bg=CARD, fg=MUTED, font=app.f_small, justify="left", anchor="w",
                 wraplength=int(520 * k)).pack(fill="x", pady=(4, 14))
        grid = tk.Frame(win, bg=CARD)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        def lab(r, t):
            tk.Label(grid, text=t, bg=CARD, fg=MUTED, font=app.f_ui).grid(row=r, column=0, sticky="w", pady=5,
                                                                         padx=(0, 12))

        lab(0, "Hizmet")
        prov_var = tk.StringVar(value=self.provider().name)
        prov_cb = ttk.Combobox(grid, textvariable=prov_var, values=[p.name for p in ai.PROVIDERS], state="readonly",
                               style="Light.TCombobox", font=app.f_ui, width=34)
        prov_cb.grid(row=0, column=1, sticky="ew")
        lab(1, "API anahtarı")
        kf = tk.Frame(grid, bg=CARD, highlightthickness=1, highlightbackground=LINE_STRONG, highlightcolor=AMBER)
        kf.grid(row=1, column=1, sticky="ew")
        key_var = tk.StringVar()
        key_entry = tk.Entry(kf, textvariable=key_var, show="•", font=app.f_mono, relief="flat", bg=CARD, fg=TEXT,
                             insertbackground=TEXT, highlightthickness=0, borderwidth=0, width=36)
        key_entry.pack(side="left", fill="x", expand=True, padx=8, pady=5)
        show = tk.Label(kf, text="Göster", bg=CARD, fg=TS_FG, font=app.f_small, cursor="hand2")
        show.pack(side="right", padx=8)

        def toggle_show(_e=None):
            hidden = key_entry.cget("show") == "•"
            key_entry.configure(show="" if hidden else "•")
            show.configure(text="Gizle" if hidden else "Göster")
        show.bind("<Button-1>", toggle_show)
        help_lbl = tk.Label(grid, text="", bg=CARD, fg=MUTED, font=app.f_small, justify="left", anchor="w",
                            wraplength=int(400 * k))
        help_lbl.grid(row=2, column=1, sticky="w", pady=(4, 0))
        link = tk.Label(grid, text="Anahtar sayfasını aç ↗", bg=CARD, fg=TS_FG, font=app.f_small, cursor="hand2")
        link.grid(row=3, column=1, sticky="w")
        lab(4, "Model")
        model_var = tk.StringVar()
        model_cb = ttk.Combobox(grid, textvariable=model_var, style="Light.TCombobox", font=app.f_ui, width=34)
        model_cb.grid(row=4, column=1, sticky="ew")
        state = tk.Label(win, text="", bg=CARD, fg=MUTED, font=app.f_small, anchor="w", justify="left",
                         wraplength=int(520 * k))
        state.pack(fill="x", pady=(12, 0))

        def cur() -> ai.Provider:
            return next((p for p in ai.PROVIDERS if p.name == prov_var.get()), ai.PROVIDERS[0])

        def model_label(p, mid):
            return dict(p.models).get(mid, mid)

        def load(_e=None):
            p = cur()
            key_var.set(ai.get_key(p.key))
            help_lbl.configure(text=p.key_help)
            labels = [f"{m} — {d}" for m, d in p.models]
            model_cb.configure(values=labels)
            mid = (st.get("ai_models") or {}).get(p.key) or p.models[0][0]
            model_var.set(next((l for l in labels if l.startswith(mid + " ")), mid))
            consent = (st.get("ai_consent") or {}).get(p.key)
            state.configure(text=("Anahtar kayıtlı. " if key_var.get() else "Henüz anahtar girilmedi. ")
                            + ("Gönderim onayı verildi (her seferinde sorulmuyor)." if consent else ""), fg=MUTED)
        prov_cb.bind("<<ComboboxSelected>>", load)
        link.bind("<Button-1>", lambda e: __import__("webbrowser").open(cur().key_url))

        def chosen_model() -> str:
            v = model_var.get().strip()
            return v.split(" — ")[0].strip()

        def test():
            p, key, mid = cur(), key_var.get().strip(), chosen_model()
            if not key:
                state.configure(text="Önce API anahtarını yapıştırın.", fg=RED)
                return
            state.configure(text="Bağlantı deneniyor…", fg=MUTED)
            test_btn.configure(state="disabled")

            def work():
                try:
                    models = ai.list_models(p.key, key)
                    ai.test_connection(p.key, key, mid)
                    self.events.put(("tested", win, state, test_btn, model_cb, p, models, None))
                except Exception as e:  # noqa: BLE001
                    self.events.put(("tested", win, state, test_btn, model_cb, p, [], str(e)))
            threading.Thread(target=work, daemon=True).start()

        def save():
            p = cur()
            persistent = ai.set_key(p.key, key_var.get())
            st["ai_provider"] = p.key
            st.setdefault("ai_models", {})[p.key] = chosen_model() or p.models[0][0]
            save_settings(app._collect_settings())
            if key_var.get().strip() and not persistent:
                messagebox.showwarning(APP_NAME, "Anahtar bu bilgisayarın güvenli anahtar deposuna yazılamadı; "
                                                 "yalnızca uygulama açık kaldığı sürece hatırlanacak.", parent=win)
            self.refresh()
            win.destroy()

        def forget():
            p = cur()
            ai.set_key(p.key, "")
            (st.get("ai_consent") or {}).pop(p.key, None)
            key_var.set("")
            save_settings(app._collect_settings())
            state.configure(text="Anahtar ve gönderim onayı silindi.", fg=MUTED)
            self.refresh()

        row = tk.Frame(win, bg=CARD)
        row.pack(fill="x", pady=(16, 0))
        test_btn = ttk.Button(row, text="Bağlantıyı dene", style="Ghost.TButton", width=0, command=test)
        test_btn.pack(side="left")
        ttk.Button(row, text="Anahtarı sil", style="Ghost.TButton", width=0, command=forget).pack(side="left", padx=8)
        ttk.Button(row, text="Kaydet", style="Navy.TButton", command=save).pack(side="right")
        ttk.Button(row, text="Vazgeç", style="Ghost.TButton", command=win.destroy).pack(side="right", padx=8)
        load()
        win.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - win.winfo_width()) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - win.winfo_height()) // 4
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        self._settings_win = win
        key_entry.focus_set()

    # --- özetleme
    def start(self):
        if self.busy():
            self.cancel.set()
            self.status.configure(text="İptal ediliyor…")
            return
        text = self.get_text()
        if not text:
            messagebox.showinfo(APP_NAME, "Önce özetlenecek metni yapıştırın ya da bir dosya açın.")
            return
        p = self.provider()
        if not ai.get_key(p.key):
            messagebox.showinfo(APP_NAME, "Özetleme için önce yapay zekâ ayarlarından bir hizmet seçip API "
                                          "anahtarınızı girin.")
            self.open_settings()
            return
        if not self._consent(p):
            self.status.configure(text="Gönderim iptal edildi; metin hiçbir yere gönderilmedi.")
            return
        st = self.app.settings
        st["ai_kind"], st["ai_lang"] = self._kind(), self._lang()
        opts = dict(provider=p.key, model=self.model(), kind=self._kind(), lang=self._lang(),
                    extra=self._extra_text(), title=self.title)
        self.cancel.clear()
        self.pbar.pack(fill="x", pady=(4, 0))
        self.pbar.start(12)
        self.status.configure(text=f"{p.name} özetliyor…")

        def work():
            try:
                md = ai.summarize(text, on_status=lambda s: self.events.put(("status", s)), cancel=self.cancel, **opts)
                self.events.put(("done", md))
            except ai.Cancelled:
                self.events.put(("cancelled",))
            except Exception as e:  # noqa: BLE001
                self.events.put(("error", str(e)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.refresh()

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "status":
                    self.status.configure(text=ev[1])
                elif kind == "done":
                    self._finish()
                    self._render(ev[1])
                    p = self.provider()
                    self.status.configure(text=f"Özet hazır · {p.name} · {self.model()}")
                elif kind == "cancelled":
                    self._finish()
                    self.status.configure(text="İptal edildi.")
                elif kind == "error":
                    self._finish()
                    self.status.configure(text="Özetlenemedi.")
                    messagebox.showerror(APP_NAME, ev[1])
                elif kind == "tested":
                    _, win, state, btn, model_cb, p, models, err = ev
                    if win.winfo_exists():
                        btn.configure(state="normal")
                        if err:
                            state.configure(text=err, fg=RED)
                        else:
                            known = [f"{m} — {d}" for m, d in p.models]
                            extra = [m for m in models if m not in dict(p.models)]
                            model_cb.configure(values=known + extra)
                            state.configure(text=f"Bağlantı başarılı. Hesabınızda {len(models)} model kullanılabilir; "
                                                 "listeden seçebilirsiniz. Kaydet'e basmayı unutmayın.", fg=GREEN)
                self.refresh()
        except queue.Empty:
            pass
        self.app.root.after(100, self._poll)

    def _finish(self):
        self.worker = None
        self.pbar.stop()
        self.pbar.pack_forget()

    def refresh(self):
        p = self.provider()
        has_key = bool(ai.get_key(p.key))
        busy = self.busy()
        if has_key:
            self.sub.configure(text=f"{p.name} · {self.model()} ile, kendi API anahtarınızla.")
        else:
            self.sub.configure(text="Başlamak için “Yapay zekâ ayarları…”ndan bir hizmet seçip API anahtarınızı girin.")
        self.warn.configure(text=f"⚠  Özetlemede metin {p.company_dat} ({p.product}) gönderilir. "
                                 "Trafyle'ın diğer tüm işlemleri bilgisayarınızda kalır.")
        self.go_btn.configure(text="İptal et" if busy else "Özetle", style="Side.TButton" if busy else "Amber.TButton",
                              state="disabled" if busy and self.cancel.is_set() else "normal")
        has_out = bool(self.summary_md())
        for b in (self.copy_btn, self.speak_btn, self.save_btn):
            b.configure(state="normal" if has_out and not busy else "disabled")

    # --- çıktı
    def copy(self):
        md = self.summary_md()
        if md:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(exporters.md_to_text(md))
            self.status.configure(text="Özet panoya kopyalandı.")

    def speak(self):
        md = self.summary_md()
        if md:
            self.app.set_mode("tts")
            self.app.tts_panel.set_text(exporters.md_to_text(md).replace("• ", ""), self.title + " özeti")

    def save(self, ext: str):
        md = self.summary_md()
        if not md:
            return
        path = filedialog.asksaveasfilename(title="Özeti kaydet", defaultextension=ext,
                                            initialfile=f"{self.title} - özet{ext}",
                                            initialdir=self.app.settings.get("export_dir") or os.path.expanduser("~"),
                                            filetypes=[("Dosya", "*" + ext)])
        if not path:
            return
        p = self.provider()
        note = f"{p.name} ({self.model()}) ile özetlendi · Trafyle"
        try:
            exporters.export_summary(path, md, f"{self.title} — özet", note)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Kaydedilemedi:\n{e}")
            return
        self.app.settings["export_dir"] = os.path.dirname(path)
        self.status.configure(text=f"Kaydedildi: {os.path.basename(path)}")


class ConvertPanel:
    """Dosya dönüştürme ekranı: OCR, PDF → metin/Word, video → ses, görüntü biçimleri."""

    STATUS_TEXT = {"pending": "Bekliyor", "skip": "Bu işleme uygun değil", "running": "İşleniyor…",
                   "done": "Bitti", "error": "Hata", "cancelled": "İptal edildi"}

    def __init__(self, app: "App", parent: tk.Widget):
        self.app = app
        st = app.settings
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.cancel = threading.Event()
        self.rows: dict[str, dict] = {}
        self._n = 0
        self.op = st.get("conv_op", "pdf") if st.get("conv_op") in converters.OP_BY_KEY else "pdf"
        self.out_choice: dict[str, str] = dict(st.get("conv_out", {}))
        self.dest_dir = st.get("conv_dir") or ""

        f = self.frame = tk.Frame(parent, bg=BG)
        head = tk.Frame(f, bg=BG)
        head.pack(fill="x")
        tools = tk.Frame(head, bg=BG)
        tools.pack(side="right")
        ttk.Button(tools, text="Dosya ekle…", width=0, style="Ghost.TButton", command=self.add_dialog).pack(side="left")
        self.clear_btn = ttk.Button(tools, text="Listeyi temizle", width=0, style="Ghost.TButton", command=self.clear)
        self.clear_btn.pack(side="left", padx=(8, 0))
        tk.Label(head, text="Dönüştür", bg=BG, fg=TEXT, font=app.f_title, anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(f, text="Bir işlem seçin, dosyaları ekleyin. Dönüştürme bilgisayarınızda yapılır.",
                 bg=BG, fg=MUTED, font=app.f_ui, anchor="w").pack(fill="x")

        # İşlem kartları
        cards = tk.Frame(f, bg=BG)
        cards.pack(fill="x", pady=(14, 12))
        self.op_cards: dict[str, tuple] = {}
        for i, op in enumerate(converters.OPS):
            cards.columnconfigure(i, weight=1, uniform="op")
            c = tk.Frame(cards, bg=CARD, highlightthickness=2, highlightbackground=LINE, padx=14, pady=10, cursor="hand2")
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            t = tk.Label(c, text=op.title, bg=CARD, fg=TEXT, font=app.f_ui_bold, anchor="w", justify="left")
            t.pack(fill="x")
            d = tk.Label(c, text=op.desc, bg=CARD, fg=MUTED, font=app.f_small, anchor="w", justify="left", wraplength=210)
            d.pack(fill="x", pady=(3, 0))
            for w in (c, t, d):
                w.bind("<Button-1>", lambda e, k=op.key: self.set_op(k))
            c.bind("<Configure>", lambda e, a=t, b=d: [x.configure(wraplength=max(120, e.width - 34)) for x in (a, b)])
            self.op_cards[op.key] = (c, t, d)

        # Seçenekler
        opt = tk.Frame(f, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=16, pady=12)
        opt.pack(fill="x", pady=(0, 12))
        row = tk.Frame(opt, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Çıktı", bg=CARD, fg=MUTED, font=app.f_ui).pack(side="left")
        self.out_var = tk.StringVar()
        self.out_cb = ttk.Combobox(row, textvariable=self.out_var, state="readonly", style="Light.TCombobox",
                                   width=13, font=app.f_ui)
        self.out_cb.pack(side="left", padx=(8, 22))
        self.out_cb.bind("<<ComboboxSelected>>", lambda e: self._remember_out())
        self.img_opts = tk.Frame(row, bg=CARD)
        tk.Label(self.img_opts, text="Boyut", bg=CARD, fg=MUTED, font=app.f_ui).pack(side="left")
        self.size_var = tk.StringVar(value=st.get("conv_size", converters.IMAGE_SIZES[0][0]))
        ttk.Combobox(self.img_opts, textvariable=self.size_var, state="readonly", style="Light.TCombobox", width=15,
                     font=app.f_ui, values=[s for s, _ in converters.IMAGE_SIZES]).pack(side="left", padx=(8, 22))
        self.q_lbl = tk.Label(self.img_opts, text="Kalite", bg=CARD, fg=MUTED, font=app.f_ui)
        self.q_lbl.pack(side="left")
        self.quality_var = tk.StringVar(value=st.get("conv_quality", converters.JPG_QUALITY[0][0]))
        self.q_cb = ttk.Combobox(self.img_opts, textvariable=self.quality_var, state="readonly", style="Light.TCombobox",
                                 width=17, font=app.f_ui, values=[s for s, _ in converters.JPG_QUALITY])
        self.q_cb.pack(side="left", padx=(8, 0))
        self.out_cb.bind("<<ComboboxSelected>>", lambda e: self._update_quality(), add="+")

        # Bağlantı (yalnızca Video → ses)
        self.link_row = tk.Frame(opt, bg=CARD)
        tk.Label(self.link_row, text="Bağlantı", bg=CARD, fg=MUTED, font=app.f_ui).pack(side="left")
        lb = tk.Frame(self.link_row, bg=CARD, highlightthickness=1, highlightbackground=LINE_STRONG,
                      highlightcolor=AMBER)
        lb.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.link_entry = tk.Entry(lb, font=app.f_ui, relief="flat", bg=CARD, fg=TEXT, insertbackground=TEXT,
                                   highlightthickness=0, borderwidth=0)
        self.link_entry.pack(fill="x", padx=8, pady=6)
        self.link_entry.bind("<Return>", lambda e: self.add_link_entry())
        self.link_entry.bind("<KP_Enter>", lambda e: self.add_link_entry())
        self.link_entry.bind("<FocusIn>", lambda e: self._link_placeholder(False))
        self.link_entry.bind("<FocusOut>", lambda e: self._link_placeholder(True))
        ttk.Button(self.link_row, text="Ekle", width=0, style="Navy.TButton",
                   command=self.add_link_entry).pack(side="left")
        self._link_ph = False
        self._link_placeholder(True)
        self.link_opts = tk.Frame(row, bg=CARD)
        self.auto_stt_var = tk.BooleanVar(value=bool(st.get("conv_auto_stt", False)))
        ttk.Checkbutton(self.link_opts, text="Bitince metne çevir", variable=self.auto_stt_var,
                        style="Light.TCheckbutton").pack(side="left")
        self.upd_btn = ttk.Button(row, text="Bağlantı desteğini güncelle", width=0, style="Ghost.TButton",
                                  command=self.update_links)

        row2 = self.row2 = tk.Frame(opt, bg=CARD)
        row2.pack(fill="x", pady=(10, 0))
        tk.Label(row2, text="Kaydet", bg=CARD, fg=MUTED, font=app.f_ui).pack(side="left")
        self.dest_var = tk.StringVar(value="Seçtiğim klasöre" if st.get("conv_dest") == "dir" and self.dest_dir
                                     else "Kaynak dosyanın yanına")
        dcb = ttk.Combobox(row2, textvariable=self.dest_var, state="readonly", style="Light.TCombobox", width=20,
                           font=app.f_ui, values=["Kaynak dosyanın yanına", "Seçtiğim klasöre"])
        dcb.pack(side="left", padx=(8, 10))
        dcb.bind("<<ComboboxSelected>>", lambda e: self._dest_changed())
        self.dir_btn = ttk.Button(row2, text="Klasör seç…", width=0, style="Ghost.TButton", command=self.pick_dir)
        self.dir_lbl = tk.Label(row2, text="", bg=CARD, fg=TEXT, font=app.f_small, anchor="w")
        self.note = tk.Label(opt, text="", bg=CARD, fg=MUTED, font=app.f_small, anchor="w", justify="left")
        self.note.pack(fill="x", pady=(8, 0))
        opt.bind("<Configure>", lambda e: self.note.configure(wraplength=max(200, e.width - 36)))

        # Dosya listesi
        lst = tk.Frame(f, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        lst.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(lst, columns=("file", "status", "result"), show="headings", style="Conv.Treeview",
                                 selectmode="extended", height=3)
        for col, txt, w, stretch in (("file", "Dosya", 260, True), ("status", "Durum", 150, False),
                                     ("result", "Sonuç", 330, True)):
            self.tree.heading(col, text=txt, anchor="w")
            self.tree.column(col, width=w, minwidth=90, stretch=stretch, anchor="w")
        tsb = ttk.Scrollbar(lst, orient="vertical", command=self.tree.yview, style="Light.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("done", foreground=GREEN)
        self.tree.tag_configure("error", foreground=RED)
        self.tree.tag_configure("skip", foreground="#A3ABBB")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        self.tree.bind("<Double-1>", lambda e: self.open_output())
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<BackSpace>", lambda e: self.remove_selected())
        self.empty = tk.Label(lst, text="", bg=CARD, fg=MUTED, font=app.f_ui, justify="center")
        if DND_OK:
            for w in (f, self.tree, self.empty, lst):
                try:
                    w.drop_target_register(DND_FILES, DND_TEXT)
                    w.dnd_bind("<<Drop>>", self._on_drop)
                except Exception:  # noqa: BLE001
                    pass

        # Çalıştırma
        act = tk.Frame(f, bg=BG)
        act.pack(side="bottom", fill="x", pady=(12, 0), before=lst)
        self.go_btn = ttk.Button(act, text="Dönüştür", style="Amber.TButton", command=self.start, width=12)
        self.go_btn.pack(side="left")
        right = tk.Frame(act, bg=BG)
        right.pack(side="right")
        self.open_btn = ttk.Button(right, text="Aç", width=0, style="Ghost.TButton", command=self.open_output)
        self.open_btn.pack(side="left")
        self.reveal_btn = ttk.Button(right, text="Klasörde göster", width=0, style="Ghost.TButton", command=self.reveal)
        self.reveal_btn.pack(side="left", padx=(8, 0))
        self.sum_btn = ttk.Button(right, text="Özetle", width=0, style="Ghost.TButton", command=self.summarize)
        self.next_btn = ttk.Button(right, text="Seslendir", width=0, style="Navy.TButton", command=self.next_step)
        self.next_btn.pack(side="left", padx=(8, 0))
        prog = tk.Frame(act, bg=BG)
        prog.pack(side="left", fill="x", expand=True, padx=16)
        self.status = tk.Label(prog, text="", bg=BG, fg=MUTED, font=app.f_small, anchor="w")
        self.status.pack(fill="x")
        self.pbar = ttk.Progressbar(prog, mode="determinate", maximum=1000, style="Light.Horizontal.TProgressbar")

        self._dest_changed(save=False)
        self.set_op(self.op, force=True)
        app.root.after(100, self._poll)

    # --- seçimler
    def set_op(self, key: str, force: bool = False):
        if self.busy() or (key == self.op and not force):
            return
        self.op = key
        op = converters.OP_BY_KEY[key]
        for k, (c, t, d) in self.op_cards.items():
            on = k == key
            bg = "#FFF6E6" if on else CARD
            c.configure(bg=bg, highlightbackground=AMBER if on else LINE)
            t.configure(bg=bg, fg=NAVY if on else TEXT)
            d.configure(bg=bg)
        labels = [lbl for lbl, _ in op.outputs]
        self.out_cb.configure(values=labels)
        want = self.out_choice.get(key)
        self.out_var.set(want if want in labels else labels[0])
        if key == "image":
            self.img_opts.pack(side="left")
        else:
            self.img_opts.pack_forget()
        if key == "video":
            self.link_row.pack(fill="x", pady=(10, 0), before=self.row2)
            self.link_opts.pack(side="left")
            self.upd_btn.pack(side="right")
        else:
            self.link_row.pack_forget()
            self.link_opts.pack_forget()
            self.upd_btn.pack_forget()
        self._update_quality()
        notes = {
            "ocr": f"Fotoğraf (JPG, PNG, HEIC…) ya da taranmış PDF ekleyin. Yazı, {OS_OWN} yerleşik metin "
                   "tanımasıyla okunur."
                   + ("" if converters.ocr_available() or not (IS_MAC or IS_WINDOWS)
                      else f"  ⚠ Metin tanıma bileşeni kurulu değil: {INSTALLER}'a yeniden çift tıklayın."),
            "pdf": "Word çıktısında yazı ve paragraflar (başlıklar dahil) aktarılır; sütunlar, tablolar ve resimler aktarılmaz. "
                   "Taranmış sayfalar otomatik olarak metin tanımayla okunur.",
            "video": "YouTube, Vimeo, X, Instagram… bağlantılarında video indirilmez, yalnızca ses alınır ve İndirilenler'e "
                     "(ya da seçtiğiniz klasöre) kaydedilir. Yalnızca kullanma hakkınız olan içerikler için kullanın.",
            "image": "Fotoğraf yönü korunur. Küçültme, yalnızca seçilen boyuttan büyük görüntülere uygulanır.",
        }
        if key == "ocr" and not (IS_MAC or IS_WINDOWS):
            notes["ocr"] = "Metin tanıma (OCR) yalnızca macOS ve Windows'ta çalışır."
        self.note.configure(text=notes[key])
        for iid, r in self.rows.items():
            if r["status"] in ("pending", "skip"):
                r["status"] = "pending" if key in converters.ops_for(r["path"]) else "skip"
                self._update_row(iid)
        self.refresh()

    def _remember_out(self):
        self.out_choice[self.op] = self.out_var.get()

    def _update_quality(self):
        jpg = self._out_ext() in (".jpg", ".jpeg")
        self.q_cb.configure(state="readonly" if jpg else "disabled")
        self.q_lbl.configure(fg=MUTED if jpg else "#A3ABBB")

    def _out_ext(self) -> str:
        op = converters.OP_BY_KEY[self.op]
        return dict(op.outputs).get(self.out_var.get(), op.outputs[0][1])

    def _dest_changed(self, save: bool = True):
        to_dir = self.dest_var.get() == "Seçtiğim klasöre"
        if to_dir and not self.dest_dir and save:
            if not self.pick_dir():
                self.dest_var.set("Kaynak dosyanın yanına")
                to_dir = False
        if to_dir:
            self.dir_btn.pack(side="left")
            self.dir_lbl.pack(side="left", padx=(10, 0))
            self.dir_lbl.configure(text=self._short(self.dest_dir))
        else:
            self.dir_btn.pack_forget()
            self.dir_lbl.pack_forget()

    @staticmethod
    def _short(path: str) -> str:
        home = os.path.expanduser("~")
        p = "~" + path[len(home):] if path.startswith(home) else path
        return p if len(p) < 46 else "…" + p[-44:]

    def pick_dir(self) -> bool:
        d = filedialog.askdirectory(title="Çıktıların kaydedileceği klasör",
                                    initialdir=self.dest_dir or self.app.settings.get("last_dir") or os.path.expanduser("~"))
        if not d:
            return False
        self.dest_dir = d
        self.dir_lbl.configure(text=self._short(d))
        return True

    def _out_dir(self) -> Optional[str]:
        return self.dest_dir if self.dest_var.get() == "Seçtiğim klasöre" and self.dest_dir else None

    def collect_settings(self) -> dict:
        self._remember_out()
        return {"conv_op": self.op, "conv_out": self.out_choice, "conv_size": self.size_var.get(),
                "conv_auto_stt": bool(self.auto_stt_var.get()),
                "conv_quality": self.quality_var.get(), "conv_dir": self.dest_dir,
                "conv_dest": "dir" if self._out_dir() else "src"}

    # --- dosyalar
    def add_dialog(self):
        op = converters.OP_BY_KEY[self.op]
        paths = filedialog.askopenfilenames(
            title="Dönüştürülecek dosyaları seç",
            initialdir=self.app.settings.get("last_dir") or os.path.expanduser("~"),
            filetypes=[(op.title, " ".join("*" + e for e in op.exts)),
                       ("Desteklenen tüm dosyalar", " ".join("*" + e for e in converters.ALL_EXTS)),
                       ("Tüm dosyalar", "*.*")])
        self.add_paths(paths)

    def add_paths(self, paths):
        files = []
        for p in paths:
            if converters.is_url(p):
                files.append(p.strip())
            elif os.path.isdir(p):
                files += [os.path.join(p, n) for n in sorted(os.listdir(p))
                          if not n.startswith(".") and os.path.isfile(os.path.join(p, n))]
            elif os.path.isfile(p):
                files.append(p)
        files = [p for p in files if converters.ops_for(p)]
        known = {r["path"] for r in self.rows.values()}
        files = [p for p in files if p not in known]
        if not files:
            if paths:
                self.status.configure(text="Eklenecek yeni ya da uygun dosya bulunamadı.")
            return 0
        # Liste boşsa ve dosyalar başka bir işleme uyuyorsa o işlemi seç
        if not self.rows and not self.busy():
            fits = [set(converters.ops_for(p)) for p in files]
            if not all(self.op in s for s in fits):
                common = set.intersection(*fits)
                for k in ("pdf", "image", "video", "ocr"):
                    if k in common:
                        self.set_op(k)
                        break
        if self.op != "video" and any(converters.is_url(p) for p in files) and not self.busy():
            self.set_op("video")
        local = [p for p in files if not converters.is_url(p)]
        if local:
            self.app.settings["last_dir"] = os.path.dirname(local[0])
        for p in files:
            self._n += 1
            iid = f"c{self._n}"
            ok = self.op in converters.ops_for(p)
            self.rows[iid] = {"path": p, "status": "pending" if ok else "skip", "out": None, "text": None, "note": ""}
            self.tree.insert("", "end", iid=iid, values=("", "", ""))
            self._update_row(iid)
        n_links = sum(converters.is_url(p) for p in files)
        self.status.configure(text=f"{n_links} bağlantı eklendi." if n_links == len(files)
                              else f"{len(files)} dosya eklendi.")
        self.refresh()
        return len(files)

    # --- bağlantılar
    def _link_placeholder(self, on: bool):
        e = self.link_entry
        if on and not e.get().strip():
            e.delete(0, "end")
            e.insert(0, "Video bağlantısını buraya yapıştırın ve Enter'a basın")
            e.configure(fg="#A3ABBB")
            self._link_ph = True
        elif not on and self._link_ph:
            e.delete(0, "end")
            e.configure(fg=TEXT)
            self._link_ph = False

    def add_link_entry(self):
        text = "" if self._link_ph else self.link_entry.get()
        if not text.strip():
            self.link_entry.focus_set()
            return
        if self.add_links(text):
            self.link_entry.delete(0, "end")
        elif not any(converters.is_url(u) for u in text.split()):
            self.status.configure(text="Bu bir video bağlantısına benzemiyor (http:// ya da https:// ile başlamalı).")

    def add_links(self, text: str) -> int:
        urls = [u for u in re.split(r"\s+", text.strip()) if converters.is_url(u)]
        return self.add_paths(urls) if urls else 0

    def _on_drop(self, event):
        data = (event.data or "").strip()
        if data and converters.is_url(data.split()[0]):
            self.add_links(data)
        else:
            self.add_paths(self.app.root.tk.splitlist(data))

    @staticmethod
    def _link_label(url: str) -> str:
        u = re.sub(r"^https?://(www\.|m\.)?", "", url)
        return u if len(u) <= 48 else u[:46] + "…"

    def _row_name(self, r: dict) -> str:
        if r.get("title"):
            return r["title"]
        return self._link_label(r["path"]) if converters.is_url(r["path"]) else os.path.basename(r["path"])

    def update_links(self):
        if getattr(self, "_updating", False):
            return
        self._updating = True
        self.upd_btn.configure(state="disabled", text="Güncelleniyor…")
        self.status.configure(text="Bağlantı desteği güncelleniyor (bir dakika sürebilir)…")

        def work():
            try:
                ok, msg = converters.update_downloader()
            except Exception as e:  # noqa: BLE001
                ok, msg = False, str(e)
            self.events.put(("updated", ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _on_select(self):
        sel = self.tree.selection()
        if len(sel) == 1 and self.rows.get(sel[0], {}).get("status") == "error" and not self.busy():
            r = self.rows[sel[0]]
            if len(r["note"]) > 60 or "\n" in r["note"]:
                messagebox.showerror(APP_NAME, f"{self._row_name(r)}\n\n{r['note']}")
        self.refresh()

    def _update_row(self, iid: str, extra: str = ""):
        r = self.rows[iid]
        status = extra or self.STATUS_TEXT[r["status"]]
        result = r["note"].split("\n")[0]
        if r["status"] == "done" and r["out"]:
            result = f"{os.path.basename(r['out'])}  ·  {r['note']}"
        self.tree.item(iid, values=(self._row_name(r), status, result),
                       tags=(r["status"],) if r["status"] in ("done", "error", "skip") else ())

    def remove_selected(self):
        if self.busy():
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.rows.pop(iid, None)
        self.refresh()

    def clear(self):
        if self.busy():
            return
        for iid in list(self.rows):
            self.tree.delete(iid)
        self.rows.clear()
        self.status.configure(text="")
        self.refresh()

    # --- çalıştırma
    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def start(self):
        if self.busy():
            self.cancel.set()
            self.status.configure(text="İptal ediliyor…")
            self.go_btn.configure(state="disabled")
            return
        todo = [i for i, r in self.rows.items() if r["status"] in ("pending", "error", "cancelled")
                and self.op in converters.ops_for(r["path"])]
        if not todo:
            messagebox.showinfo(APP_NAME, "Bu işleme uygun, bekleyen dosya yok. Önce dosya ekleyin.")
            return
        if self.op == "ocr" and not converters.ocr_available():
            messagebox.showerror(APP_NAME, "Metin tanıma (OCR) bu bilgisayarda kullanılamıyor.\n\n"
                                 + (f"Trafyle klasöründeki {INSTALLER}'a yeniden çift tıklayıp kurulumu tamamlayın."
                                    if IS_MAC or IS_WINDOWS else "Bu özellik yalnızca macOS ve Windows'ta çalışır."))
            return
        out_dir = self._out_dir()
        if out_dir and not os.path.isdir(out_dir):
            messagebox.showerror(APP_NAME, "Seçilen klasör bulunamadı. Başka bir klasör seçin.")
            return
        opts = {"max_px": dict(converters.IMAGE_SIZES).get(self.size_var.get(), 0),
                "quality": dict(converters.JPG_QUALITY).get(self.quality_var.get(), 85)}
        op, ext = self.op, self._out_ext()
        jobs = [(i, self.rows[i]["path"]) for i in todo]
        for i in todo:
            self.rows[i].update(status="pending", note="")
            self._update_row(i)
        self.cancel.clear()
        self._run_outputs: list[str] = []
        self._run_auto_stt = op == "video" and bool(self.auto_stt_var.get())
        self.pbar.pack(fill="x", pady=(4, 0))
        self.pbar.configure(value=0)

        def work():
            for k, (iid, src) in enumerate(jobs):
                if self.cancel.is_set():
                    self.events.put(("cancelled", iid))
                    continue
                self.events.put(("start", iid, k, len(jobs)))
                try:
                    dst = converters.out_path(src, ext, out_dir)
                    res = converters.run(op, src, dst, opts,
                                         lambda f, m, k=k: self.events.put(("progress", iid, (k + f) / len(jobs), m)),
                                         self.cancel)
                    self.events.put(("done", iid, res))
                except converters.Cancelled:
                    self.events.put(("cancelled", iid))
                except Exception as e:  # noqa: BLE001
                    self.events.put(("error", iid, str(e) or e.__class__.__name__))
            self.events.put(("finished",))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.refresh()

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "start":
                    _, iid, k, n = ev
                    self.rows[iid]["status"] = "running"
                    self._update_row(iid)
                    self.tree.see(iid)
                    self.status.configure(text=f"{k + 1}/{n} · {self._row_name(self.rows[iid])}")
                elif kind == "progress":
                    _, iid, frac, msg = ev
                    self.pbar.configure(value=int(frac * 1000))
                    self._update_row(iid, msg or "İşleniyor…")
                elif kind == "done":
                    _, iid, res = ev
                    self.rows[iid].update(status="done", out=res.path, text=res.text, note=res.note)
                    if res.title:
                        self.rows[iid]["title"] = res.title
                    self._run_outputs.append(res.path)
                    self._update_row(iid)
                elif kind == "error":
                    _, iid, msg = ev
                    self.rows[iid].update(status="error", note=msg)
                    self._update_row(iid)
                elif kind == "cancelled":
                    self.rows[ev[1]].update(status="cancelled", note="")
                    self._update_row(ev[1])
                elif kind == "finished":
                    self.worker = None
                    self.pbar.pack_forget()
                    done = sum(r["status"] == "done" for r in self.rows.values())
                    errs = [r for r in self.rows.values() if r["status"] == "error"]
                    msg = "İptal edildi." if self.cancel.is_set() else f"Tamamlandı · {done} hazır"
                    if errs:
                        msg += f", {len(errs)} hata"
                    self.status.configure(text=msg)
                    finished = [i for i, r in self.rows.items() if r["status"] == "done"]
                    if finished and not self.tree.selection():
                        self.tree.selection_set(finished[-1])
                    audio = [p for p in self._run_outputs if p.lower().endswith(engine.AUDIO_EXTS)]
                    if audio and self._run_auto_stt and not self.cancel.is_set():
                        self.app.set_mode("stt")
                        self.app._add_paths(audio)
                        if not self.app._busy():
                            self.app._start()
                elif kind == "updated":
                    self._updating = False
                    self.upd_btn.configure(state="normal", text="Bağlantı desteğini güncelle")
                    if ev[1]:
                        self.status.configure(text=f"Bağlantı desteği güncel ({ev[2]}).")
                        messagebox.showinfo(APP_NAME, f"Bağlantı desteği güncellendi (sürüm {ev[2]}).\n\n"
                                            "Yeni sürümün devreye girmesi için Trafyle'ı kapatıp yeniden açın.")
                    else:
                        self.status.configure(text="Güncellenemedi.")
                        messagebox.showerror(APP_NAME, f"Güncellenemedi:\n{ev[2]}")
                self.refresh()
        except queue.Empty:
            pass
        self.app.root.after(100, self._poll)

    def refresh(self):
        busy = self.busy()
        pending = any(r["status"] in ("pending", "error", "cancelled") and self.op in converters.ops_for(r["path"])
                      for r in self.rows.values())
        if busy:
            self.go_btn.configure(text="İptal et", style="Side.TButton",
                                  state="disabled" if self.cancel.is_set() else "normal")
        else:
            self.go_btn.configure(text="Dönüştür", style="Amber.TButton", state="normal" if pending else "disabled")
        self.out_cb.configure(state="disabled" if busy else "readonly")
        self.clear_btn.configure(state="disabled" if busy or not self.rows else "normal")
        r = self._selected_done()
        self.open_btn.configure(state="normal" if r else "disabled")
        self.reveal_btn.configure(state="normal" if r else "disabled")
        is_audio = bool(r) and r["out"].lower().endswith(engine.AUDIO_EXTS)
        is_text = bool(r) and r["out"].lower().endswith((".txt", ".docx"))
        self.next_btn.configure(text="Metne çevir" if is_audio or self.op == "video" else "Seslendir",
                                state="normal" if (is_audio or is_text) else "disabled")
        if self.op == "image" and not (is_audio or is_text):
            self.next_btn.pack_forget()
        elif not self.next_btn.winfo_ismapped():
            self.next_btn.pack(side="left", padx=(8, 0))
        if self.op in ("ocr", "pdf"):
            if not self.sum_btn.winfo_ismapped():
                self.sum_btn.pack(side="left", padx=(8, 0), before=self.next_btn)
            self.sum_btn.configure(state="normal" if is_text and not busy else "disabled")
        elif self.sum_btn.winfo_ismapped():
            self.sum_btn.pack_forget()
        if self.rows:
            self.empty.place_forget()
        else:
            op = converters.OP_BY_KEY[self.op]
            kinds = ", ".join(e[1:].upper() for e in op.exts[:6]) + ("…" if len(op.exts) > 6 else "")
            hint = "Dosyaları buraya sürükleyin" if DND_OK else "Dosya eklemek için “Dosya ekle…”ye basın"
            if self.op == "video":
                kinds += "\nya da yukarıya bir video bağlantısı yapıştırın"
            self.empty.configure(text=f"{hint}\n{kinds}")
            self.empty.place(relx=0.5, rely=0.55, anchor="center")

    # --- sonuçlar
    def _selected_done(self) -> Optional[dict]:
        sel = self.tree.selection()
        if len(sel) != 1:
            return None
        r = self.rows.get(sel[0])
        return r if r and r["status"] == "done" and r["out"] and os.path.exists(r["out"]) else None

    @staticmethod
    def _open(args: list[str]):
        try:
            if IS_MAC:
                subprocess.Popen(["open"] + args)
            elif IS_WINDOWS:
                if args[0] == "-R":
                    subprocess.Popen(f'explorer /select,"{os.path.normpath(args[-1])}"')
                else:
                    os.startfile(args[-1])  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", args[-1] if args[0] != "-R" else os.path.dirname(args[-1])])
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Açılamadı:\n{e}")

    def open_output(self):
        r = self._selected_done()
        if r:
            self._open([r["out"]])

    def reveal(self):
        r = self._selected_done()
        if r:
            self._open(["-R", r["out"]])

    def next_step(self):
        r = self._selected_done()
        if not r:
            return
        stem = os.path.splitext(os.path.basename(r["out"]))[0]
        if r["out"].lower().endswith(engine.AUDIO_EXTS):
            self.app.set_mode("stt")
            self.app._add_paths([r["out"]])
            self.app.status_var.set("Ses kuyruğa eklendi. “Dönüştürmeyi başlat”a basın.")
            return
        text = r["text"]
        if text is None:
            try:
                text = tts.read_text_file(r["out"])
            except Exception as e:  # noqa: BLE001
                messagebox.showerror(APP_NAME, f"Metin okunamadı:\n{e}")
                return
        self.app.set_mode("tts")
        self.app.tts_panel.set_text(text, stem)

    def summarize(self):
        r = self._selected_done()
        if not r or not r["out"].lower().endswith((".txt", ".docx")):
            return
        text = r["text"]
        if text is None:
            try:
                text = tts.read_text_file(r["out"])
            except Exception as e:  # noqa: BLE001
                messagebox.showerror(APP_NAME, f"Metin okunamadı:\n{e}")
                return
        self.app.set_mode("sum")
        self.app.sum_panel.set_text(text, os.path.splitext(os.path.basename(r["out"]))[0])


def main():
    global DND_OK
    if IS_WINDOWS:
        import winplat
        winplat.redirect_output_if_windowless()
        winplat.enable_dpi_awareness()
    root = None
    if DND_OK:
        try:
            root = TkinterDnD.Tk()
        except Exception:  # noqa: BLE001  (tkdnd bu sistemde yüklenemezse sürükle-bırak kapanır)
            DND_OK = False
    if root is None:
        root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

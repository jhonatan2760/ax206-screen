"""
Suite de configuracao da telinha AX206 do suporte de GPU.

Janela para enviar imagem com posicionamento por mouse (arrastar/zoom),
brilho, cor solida, slideshow de pasta, bandeja do sistema e iniciar
com o Windows restaurando o ultimo estado.

Uso:
  python suite.py            # abre a janela
  python suite.py --restore  # aplica o ultimo estado e fica na bandeja (boot)
"""

import glob
import json
import os
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import usb.core
from PIL import Image, ImageDraw, ImageTk

from ax206 import AX206, AX206Error
import widget_claude

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "AX206Screen"

PREVIEW_W, PREVIEW_H = 180, 240  # preview na mesma proporcao 240x320


# ---------- estado / config ----------

def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# ---------- acesso a tela: conexao unica com reconexao ----------

_lcd = None
_lcd_lock = threading.Lock()


def lcd_call(fn):
    """Executa fn(lcd) na conexao persistente; reconecta uma vez se falhar."""
    global _lcd
    with _lcd_lock:
        for attempt in (1, 2):
            try:
                if _lcd is None:
                    _lcd = AX206()
                return fn(_lcd)
            except (usb.core.USBError, AX206Error):
                if _lcd is not None:
                    try:
                        _lcd.close()
                    except usb.core.USBError:
                        pass
                    _lcd = None
                if attempt == 2:
                    raise
                # um comando interrompido no meio deixa o firmware fora de
                # sincronia; so um reset USB completo recupera
                try:
                    dev = usb.core.find(idVendor=0x1908, idProduct=0x0102)
                    if dev is not None:
                        dev.reset()
                except usb.core.USBError:
                    pass
                time.sleep(2)  # re-enumeracao


def send_pil_image(img, brightness=None):
    def _do(lcd):
        if brightness is not None:
            lcd.set_brightness(brightness)
        lcd.show_image(img)
    lcd_call(_do)


# ---------- autostart ----------

def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
        return True
    except OSError:
        return False


def set_autostart(enable):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enable:
            pyw = sys.executable.replace("python.exe", "pythonw.exe")
            cmd = f'"{pyw}" "{os.path.join(APP_DIR, "suite.py")}" --restore'
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


# ---------- slideshow ----------

class Slideshow:
    EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self.on_frame = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, folder, interval):
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, args=(folder, interval), daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _loop(self, folder, interval):
        while not self._stop.is_set():
            try:
                files = sorted(
                    f for f in os.listdir(folder)
                    if f.lower().endswith(self.EXTS)
                )
            except OSError:
                return
            if not files:
                return
            for name in files:
                if self._stop.is_set():
                    return
                path = os.path.join(folder, name)
                try:
                    send_pil_image(Image.open(path))
                    if self.on_frame:
                        self.on_frame(path)
                except (AX206Error, usb.core.USBError, OSError):
                    pass
                if self._stop.wait(interval):
                    return


# ---------- restauracao (boot) ----------

def restore_state(cfg, slideshow):
    try:
        if cfg.get("brightness") is not None:
            lcd_call(lambda lcd: lcd.set_brightness(cfg["brightness"]))
        mode = cfg.get("mode")
        if mode == "slideshow" and cfg.get("slideshow_folder"):
            slideshow.start(cfg["slideshow_folder"], cfg.get("slideshow_interval", 10))
        elif mode == "image" and cfg.get("last_image"):
            img = Image.open(cfg["last_image"]).convert("RGB")
            view = cfg.get("view")
            if view:
                img = compose_view(img, view["scale"], view["ox"], view["oy"])
            send_pil_image(img)
        elif mode == "fill" and cfg.get("fill_color"):
            r, g, b = cfg["fill_color"]
            send_pil_image(Image.new("RGB", (AX206.WIDTH, AX206.HEIGHT), (r, g, b)))
    except (AX206Error, usb.core.USBError, OSError):
        pass


# ---------- composicao do enquadramento ----------

def cover_scale(img):
    """Menor escala que cobre a tela inteira (sem sobra preta)."""
    return max(AX206.WIDTH / img.width, AX206.HEIGHT / img.height)


def clamp_view(img, scale, ox, oy):
    """Garante que o recorte fica dentro da imagem."""
    crop_w = AX206.WIDTH / scale
    crop_h = AX206.HEIGHT / scale
    ox = max(0.0, min(ox, img.width - crop_w))
    oy = max(0.0, min(oy, img.height - crop_h))
    return ox, oy


def compose_view(img, scale, ox, oy):
    """Recorta (ox,oy) com zoom `scale` e devolve a imagem final 240x320."""
    crop_w = AX206.WIDTH / scale
    crop_h = AX206.HEIGHT / scale
    ox, oy = clamp_view(img, scale, ox, oy)
    box = (int(ox), int(oy), int(ox + crop_w), int(oy + crop_h))
    return img.crop(box).resize((AX206.WIDTH, AX206.HEIGHT), Image.LANCZOS)


# ---------- scanner Steam + editor de jogos ----------

CONTEXT_CFG = os.path.join(APP_DIR, "context_config.json")
BADGE_CHOICES = ["RTX", "DLSS 4", "RAY TRACING", "PATH TRACING", "REFLEX",
                 "G-SYNC", "CUDA", "HDR", "FSR 3", "3D V-CACHE", "RYZEN"]
_SKIP_STEAM = ("redistributable", "proton", "steam linux", "steamworks",
               "runtime", "soundtrack", "dedicated server", "sdk")
_SKIP_EXE = ("unins", "crash", "setup", "redist", "vcredist", "dxsetup",
             "report", "eac", "anticheat", "helper")


def find_main_exe(gamedir):
    """Maior .exe ate 2 niveis de profundidade (heuristica do executavel)."""
    best, best_size = None, 0
    base_depth = gamedir.rstrip("\\/").count(os.sep)
    for root_, dirs, files in os.walk(gamedir):
        if root_.count(os.sep) - base_depth >= 4:
            dirs[:] = []
        for f in files:
            lf = f.lower()
            if not lf.endswith(".exe") or any(s in lf for s in _SKIP_EXE):
                continue
            p = os.path.join(root_, f)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz > best_size:
                best, best_size = p, sz
    return best


def scan_steam_games():
    """Le a biblioteca Steam local: [(nome, appid, exe_path), ...]."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Valve\Steam") as k:
            steam = winreg.QueryValueEx(k, "SteamPath")[0]
    except OSError:
        return []
    libs = {steam}
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    try:
        text = open(vdf, encoding="utf-8", errors="ignore").read()
        libs |= {p.replace("\\\\", "\\")
                 for p in re.findall(r'"path"\s+"([^"]+)"', text)}
    except OSError:
        pass
    games = []
    for lib in libs:
        sa = os.path.join(lib, "steamapps")
        for acf in glob.glob(os.path.join(sa, "appmanifest_*.acf")):
            try:
                t = open(acf, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            name = re.search(r'"name"\s+"([^"]+)"', t)
            idir = re.search(r'"installdir"\s+"([^"]+)"', t)
            appid = re.search(r'"appid"\s+"(\d+)"', t)
            if not (name and idir):
                continue
            nm = name.group(1)
            if any(s in nm.lower() for s in _SKIP_STEAM):
                continue
            gamedir = os.path.join(sa, "common", idir.group(1))
            exe = find_main_exe(gamedir) if os.path.isdir(gamedir) else None
            games.append((nm, appid.group(1) if appid else None, exe))
    return sorted(games)


def load_context_cfg():
    try:
        return json.load(open(CONTEXT_CFG, encoding="utf-8"))
    except (OSError, ValueError):
        return {"poll_seconds": 3, "game_min_gpu_util": 30,
                "default_game_badges": ["RTX", "DLSS 4", "RAY TRACING",
                                        "REFLEX"],
                "not_games": [], "games": {},
                "ai_processes": ["ollama.exe"], "ai_min_gpu_util": 25}


class GamesPanel(ttk.Frame):
    """Aba de configuracao dos jogos: scanner Steam, edicao manual e
    geracao dos paineis de key art."""

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.cfg = load_context_cfg()
        self._preview_img = None

        # esquerda: lista + acoes
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        self.listbox = tk.Listbox(left, width=30, height=16,
                                  exportselection=False)
        self.listbox.grid(row=0, column=0, columnspan=2, sticky="ns")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        ttk.Button(left, text="Escanear Steam",
                   command=self.scan_steam).grid(row=1, column=0,
                                                 sticky="ew", pady=(6, 2))
        ttk.Button(left, text="Adicionar exe...",
                   command=self.add_exe).grid(row=1, column=1,
                                              sticky="ew", pady=(6, 2),
                                              padx=(4, 0))
        ttk.Button(left, text="Remover",
                   command=self.remove).grid(row=2, column=0,
                                             columnspan=2, sticky="ew")
        ttk.Button(left, text="Gerar todos os paineis",
                   command=self.generate_all).grid(row=3, column=0,
                                                   columnspan=2,
                                                   sticky="ew", pady=(8, 0))

        # direita: editor
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="n")
        ttk.Label(right, text="Executavel:").grid(row=0, column=0, sticky="w")
        self.exe_label = ttk.Label(right, text="—", foreground="#777")
        self.exe_label.grid(row=0, column=1, sticky="w")
        ttk.Label(right, text="Titulo:").grid(row=1, column=0, sticky="w",
                                              pady=(6, 0))
        self.title_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.title_var, width=28).grid(
            row=1, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(right, text="Badges:").grid(row=2, column=0, sticky="nw",
                                              pady=(8, 0))
        badges = ttk.Frame(right)
        badges.grid(row=2, column=1, sticky="w", pady=(8, 0))
        self.badge_vars = {}
        for i, b in enumerate(BADGE_CHOICES):
            v = tk.BooleanVar()
            ttk.Checkbutton(badges, text=b, variable=v).grid(
                row=i % 6, column=i // 6, sticky="w")
            self.badge_vars[b] = v

        self.preview = tk.Canvas(right, width=220, height=76, bg="#111",
                                 highlightthickness=1,
                                 highlightbackground="#888")
        self.preview.grid(row=3, column=0, columnspan=2, pady=10)

        btns = ttk.Frame(right)
        btns.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Button(btns, text="Gerar painel",
                   command=self.generate_panel).pack(side="left",
                                                     expand=True, fill="x")
        ttk.Button(btns, text="Salvar",
                   command=self.save_current).pack(side="left", expand=True,
                                                   fill="x", padx=(6, 0))
        self.gstatus = ttk.Label(self, text="", foreground="#555")
        self.gstatus.grid(row=1, column=0, columnspan=2, sticky="w",
                          pady=(8, 0))
        self._reload_list()

    # ---- helpers ----

    def _save_cfg(self):
        with open(CONTEXT_CFG, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2, ensure_ascii=False)

    def _reload_list(self):
        self.listbox.delete(0, "end")
        for exe in sorted(self.cfg["games"]):
            self.listbox.insert("end",
                                self.cfg["games"][exe].get("title", exe))

    def _selected_exe(self):
        sel = self.listbox.curselection()
        if not sel:
            return None
        return sorted(self.cfg["games"])[sel[0]]

    def _on_select(self, _ev=None):
        exe = self._selected_exe()
        if not exe:
            return
        g = self.cfg["games"][exe]
        self.exe_label.config(text=exe)
        self.title_var.set(g.get("title", ""))
        for b, v in self.badge_vars.items():
            v.set(b in g.get("badges", []))
        self._show_cached_panel(g.get("title", ""))

    def _show_cached_panel(self, title):
        from engine.keyart import DEFAULT_CACHE, _slug
        path = os.path.join(DEFAULT_CACHE, f"art_{_slug(title)}.png")
        self.preview.delete("all")
        if os.path.exists(path):
            img = Image.open(path)
            self._preview_img = ImageTk.PhotoImage(img)
            self.preview.create_image(110, 38, image=self._preview_img)

    # ---- acoes ----

    def scan_steam(self):
        self.gstatus.config(text="Escaneando biblioteca Steam...")

        def worker():
            found = scan_steam_games()
            added = 0
            for name, appid, exe in found:
                if not exe:
                    continue
                key = os.path.basename(exe).lower()
                if key in self.cfg["games"]:
                    continue
                title = re.sub(r"[™®�]", "", name).strip()
                self.cfg["games"][key] = {
                    "title": title,
                    "badges": list(self.cfg["default_game_badges"]),
                    "exe_path": exe, "appid": appid}
                added += 1
            self._save_cfg()
            self.after(0, lambda: (self._reload_list(), self.gstatus.config(
                text=f"{len(found)} jogos na Steam, {added} adicionados — "
                     f"gerando paineis...")))
            self.after(200, self.generate_all)  # pre-gera tudo sozinho

        threading.Thread(target=worker, daemon=True).start()

    def add_exe(self):
        path = filedialog.askopenfilename(
            title="Executavel do jogo",
            filetypes=[("Executaveis", "*.exe")])
        if not path:
            return
        key = os.path.basename(path).lower()
        title = os.path.splitext(os.path.basename(path))[0].upper()
        self.cfg["games"].setdefault(key, {
            "title": title,
            "badges": list(self.cfg["default_game_badges"]),
            "exe_path": path})
        self._save_cfg()
        self._reload_list()
        self.gstatus.config(text=f"{key} adicionado — ajuste titulo e badges")

    def remove(self):
        exe = self._selected_exe()
        if exe and messagebox.askyesno("Remover", f"Remover {exe}?"):
            del self.cfg["games"][exe]
            self._save_cfg()
            self._reload_list()

    def save_current(self):
        exe = self._selected_exe()
        if not exe:
            return
        g = self.cfg["games"][exe]
        g["title"] = self.title_var.get().strip() or g.get("title", exe)
        g["badges"] = [b for b, v in self.badge_vars.items() if v.get()]
        self._save_cfg()
        self.gstatus.config(text=f"{g['title']} salvo")

    def generate_panel(self, exe=None, silent=False):
        exe = exe or self._selected_exe()
        if not exe:
            return
        g = self.cfg["games"][exe]
        title = g.get("title", exe)
        if not silent:
            self.gstatus.config(text=f"Gerando painel de {title}...")

        def worker():
            from engine.keyart import art_panel, DEFAULT_CACHE, _slug
            stale = os.path.join(DEFAULT_CACHE, f"art_{_slug(title)}.png")
            if os.path.exists(stale):
                os.remove(stale)
            miss = os.path.join(DEFAULT_CACHE, f"steam_{_slug(title)}.miss")
            if os.path.exists(miss):
                os.remove(miss)
            art_panel(title, g.get("exe_path"))
            if not silent:
                self.after(0, lambda: (self._show_cached_panel(title),
                                       self.gstatus.config(
                                           text=f"Painel de {title} pronto")))

        threading.Thread(target=worker, daemon=True).start()

    def generate_all(self):
        exes = list(self.cfg["games"])
        self.gstatus.config(text=f"Gerando {len(exes)} paineis...")

        def worker():
            from engine.keyart import art_panel
            for i, exe in enumerate(exes, 1):
                g = self.cfg["games"][exe]
                art_panel(g.get("title", exe), g.get("exe_path"))
                self.after(0, lambda i=i: self.gstatus.config(
                    text=f"Paineis: {i}/{len(exes)}"))
            self.after(0, lambda: self.gstatus.config(
                text=f"{len(exes)} paineis prontos (cacheados)"))

        threading.Thread(target=worker, daemon=True).start()


# ---------- editor de layouts (home / por programa) ----------

LAYOUTS_PATH = os.path.join(APP_DIR, "layouts_user.json")


def load_layouts():
    try:
        return json.load(open(LAYOUTS_PATH, encoding="utf-8"))
    except (OSError, ValueError):
        return {"layouts": {"home": {"bg": "#0e0d14", "elements": [
            {"type": "mascot", "x": 60, "y": 40},
            {"type": "clock", "x": 60, "y": 164, "size": "L",
             "color": "#f7f3f7"},
            {"type": "stats", "x": 12, "y": 216},
        ]}}, "assign": {"home": "home", "per_exe": {}}}


class LayoutEditor(ttk.Frame):
    """Editor visual: arrasta elementos num canvas 240x320 e salva
    layouts atribuiveis ao standby (home) ou a programas especificos."""

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.data = load_layouts()
        self.current = next(iter(self.data["layouts"]))
        self.sel = None
        self._drag = None
        self._photo = None

        # topo: seletor de layout + atribuicao
        top = ttk.Frame(self)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(top, text="Layout:").pack(side="left")
        self.layout_var = tk.StringVar(value=self.current)
        self.layout_cb = ttk.Combobox(top, textvariable=self.layout_var,
                                      width=14, state="readonly")
        self.layout_cb.pack(side="left", padx=4)
        self.layout_cb.bind("<<ComboboxSelected>>", self._switch_layout)
        ttk.Button(top, text="Novo", width=6,
                   command=self._new_layout).pack(side="left")
        ttk.Button(top, text="Excluir", width=7,
                   command=self._del_layout).pack(side="left", padx=(4, 10))
        ttk.Label(top, text="Usar em:").pack(side="left")
        self.assign_var = tk.StringVar()
        self.assign_cb = ttk.Combobox(top, textvariable=self.assign_var,
                                      width=18)
        self.assign_cb.pack(side="left", padx=4)
        ttk.Button(top, text="Atribuir", width=8,
                   command=self._assign).pack(side="left")

        # canvas
        self.canvas = tk.Canvas(self, width=240, height=320, bg="#000",
                                highlightthickness=1,
                                highlightbackground="#888", cursor="fleur")
        self.canvas.grid(row=1, column=0, rowspan=2, padx=(0, 12), sticky="n")
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)

        # direita: elementos + propriedades
        right = ttk.Frame(self)
        right.grid(row=1, column=1, sticky="n")
        add = ttk.Frame(right)
        add.grid(row=0, column=0, columnspan=2, sticky="ew")
        for i, (txt, fn) in enumerate([
                ("+ Imagem", lambda: self._add_media("image")),
                ("+ GIF", lambda: self._add_media("gif")),
                ("+ Relogio", lambda: self._add({"type": "clock", "x": 60,
                                                 "y": 140, "size": "L",
                                                 "color": "#f7f3f7"})),
                ("+ Texto", lambda: self._add({"type": "text", "x": 20,
                                               "y": 20, "text": "TEXTO",
                                               "size": "M",
                                               "color": "#9ca2b5"})),
                ("+ Stats", lambda: self._add({"type": "stats", "x": 12,
                                               "y": 216})),
                ("+ Mascote", lambda: self._add({"type": "mascot", "x": 60,
                                                 "y": 40}))]):
            ttk.Button(add, text=txt, width=10, command=fn).grid(
                row=i // 2, column=i % 2, sticky="ew", pady=1, padx=1)

        self.el_list = tk.Listbox(right, width=24, height=7,
                                  exportselection=False)
        self.el_list.grid(row=1, column=0, columnspan=2, pady=6, sticky="ew")
        self.el_list.bind("<<ListboxSelect>>", self._select_from_list)
        ttk.Button(right, text="Remover elemento",
                   command=self._remove_el).grid(row=2, column=0,
                                                 columnspan=2, sticky="ew")

        props = ttk.Frame(right)
        props.grid(row=3, column=0, columnspan=2, pady=(8, 0), sticky="ew")
        ttk.Label(props, text="Escala %:").grid(row=0, column=0, sticky="w")
        self.scale_var = tk.IntVar(value=100)
        ttk.Spinbox(props, from_=10, to=400, increment=10, width=6,
                    textvariable=self.scale_var,
                    command=self._apply_props).grid(row=0, column=1)
        ttk.Label(props, text="Texto:").grid(row=1, column=0, sticky="w")
        self.text_var = tk.StringVar()
        e = ttk.Entry(props, textvariable=self.text_var, width=16)
        e.grid(row=1, column=1)
        e.bind("<Return>", lambda _e: self._apply_props())
        ttk.Label(props, text="Tamanho:").grid(row=2, column=0, sticky="w")
        self.size_var = tk.StringVar(value="M")
        ttk.Combobox(props, textvariable=self.size_var, width=4,
                     values=["S", "M", "L"], state="readonly").grid(
            row=2, column=1, sticky="w")
        ttk.Button(props, text="Cor...", command=self._pick_color).grid(
            row=3, column=0, sticky="w", pady=2)
        ttk.Button(props, text="Aplicar", command=self._apply_props).grid(
            row=3, column=1, sticky="e", pady=2)

        bot = ttk.Frame(right)
        bot.grid(row=4, column=0, columnspan=2, pady=(8, 0), sticky="ew")
        ttk.Button(bot, text="Fundo cor...",
                   command=self._bg_color).pack(side="left", expand=True,
                                                fill="x")
        ttk.Button(bot, text="Fundo img...",
                   command=self._bg_image).pack(side="left", expand=True,
                                                fill="x", padx=(4, 0))
        ttk.Button(right, text="Salvar layout",
                   command=self._save).grid(row=5, column=0, columnspan=2,
                                            sticky="ew", pady=(8, 0))
        self.estatus = ttk.Label(self, text="", foreground="#555")
        self.estatus.grid(row=2, column=1, sticky="sw")

        self._refresh_layout_cb()
        self._refresh_assign_cb()
        self._redraw()

    # ---- persistencia / listas ----

    def _layout(self):
        return self.data["layouts"][self.current]

    def _save(self):
        with open(LAYOUTS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        self.estatus.config(text="Salvo — watcher aplica em ate 3s")

    def _refresh_layout_cb(self):
        self.layout_cb["values"] = sorted(self.data["layouts"])
        self.layout_var.set(self.current)

    def _refresh_assign_cb(self):
        exes = sorted(load_context_cfg()["games"])
        self.assign_cb["values"] = ["home (standby)"] + exes
        cur = [f"{exe} -> {name}" for exe, name in
               self.data["assign"].get("per_exe", {}).items()]
        if self.data["assign"].get("home"):
            cur.insert(0, f"home -> {self.data['assign']['home']}")

    def _refresh_el_list(self):
        self.el_list.delete(0, "end")
        for i, el in enumerate(self._layout().get("elements", [])):
            label = el["type"]
            if el["type"] in ("image", "gif"):
                label += " " + os.path.basename(el.get("path", ""))[:14]
            elif el["type"] == "text":
                label += f' "{el.get("text", "")[:12]}"'
            self.el_list.insert("end", f"{i}: {label}")
        if self.sel is not None and self.sel < self.el_list.size():
            self.el_list.selection_set(self.sel)

    # ---- render ----

    def _redraw(self):
        from engine.user_layout import compose_frame, element_bbox, _rgb
        try:
            frame = compose_frame(self._layout(),
                                  mascot_draw=_editor_mascot)
        except Exception as e:
            self.estatus.config(text=f"Erro no layout: {e}")
            return
        self._photo = ImageTk.PhotoImage(frame)
        self.canvas.delete("all")
        self.canvas.create_image(120, 160, image=self._photo)
        if self.sel is not None:
            els = self._layout().get("elements", [])
            if self.sel < len(els):
                x, y, w, h = element_bbox(els[self.sel],
                                          _rgb(self._layout().get("bg")))
                self.canvas.create_rectangle(x, y, x + w, y + h,
                                             outline="#ff4444", width=2)
        self._refresh_el_list()

    # ---- interacao ----

    def _press(self, ev):
        from engine.user_layout import element_bbox, _rgb
        els = self._layout().get("elements", [])
        bgc = _rgb(self._layout().get("bg"))
        self.sel = None
        for i in range(len(els) - 1, -1, -1):
            x, y, w, h = element_bbox(els[i], bgc)
            if x <= ev.x <= x + w and y <= ev.y <= y + h:
                self.sel = i
                self._drag = (ev.x, ev.y, els[i].get("x", 0),
                              els[i].get("y", 0))
                self._load_props(els[i])
                break
        self._redraw()

    def _motion(self, ev):
        if self.sel is None or self._drag is None:
            return
        x0, y0, ex, ey = self._drag
        el = self._layout()["elements"][self.sel]
        el["x"] = ex + (ev.x - x0)
        el["y"] = ey + (ev.y - y0)
        self._redraw()

    def _select_from_list(self, _ev=None):
        sel = self.el_list.curselection()
        if sel:
            self.sel = sel[0]
            self._load_props(self._layout()["elements"][self.sel])
            self._redraw()

    def _load_props(self, el):
        self.scale_var.set(el.get("scale", 100))
        self.text_var.set(el.get("text", ""))
        self.size_var.set(el.get("size", "M"))

    def _apply_props(self):
        if self.sel is None:
            return
        el = self._layout()["elements"][self.sel]
        if el["type"] in ("image", "gif"):
            el["scale"] = self.scale_var.get()
        if el["type"] == "text":
            el["text"] = self.text_var.get()
        if el["type"] in ("text", "clock"):
            el["size"] = self.size_var.get()
        self._redraw()

    def _pick_color(self):
        if self.sel is None:
            return
        el = self._layout()["elements"][self.sel]
        rgb, hexv = colorchooser.askcolor(title="Cor do elemento")
        if hexv and el["type"] in ("text", "clock"):
            el["color"] = hexv
            self._redraw()

    # ---- acoes ----

    def _add(self, el):
        self._layout().setdefault("elements", []).append(el)
        self.sel = len(self._layout()["elements"]) - 1
        self._redraw()

    def _add_media(self, typ):
        path = filedialog.askopenfilename(
            title="Escolher arquivo",
            filetypes=[("Imagens/GIF", "*.png *.jpg *.jpeg *.gif *.bmp "
                        "*.webp")])
        if path:
            self._add({"type": typ, "x": 40, "y": 40, "path": path,
                       "scale": 100})

    def _remove_el(self):
        if self.sel is not None:
            els = self._layout().get("elements", [])
            if self.sel < len(els):
                del els[self.sel]
                self.sel = None
                self._redraw()

    def _bg_color(self):
        rgb, hexv = colorchooser.askcolor(title="Cor de fundo")
        if hexv:
            self._layout()["bg"] = hexv
            self._redraw()

    def _bg_image(self):
        path = filedialog.askopenfilename(
            title="Imagem de fundo",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.webp")])
        if path:
            self._layout()["bg"] = path
            self._redraw()

    def _switch_layout(self, _ev=None):
        self.current = self.layout_var.get()
        self.sel = None
        self._redraw()

    def _new_layout(self):
        import tkinter.simpledialog as sd
        name = sd.askstring("Novo layout", "Nome do layout:")
        if not name or name in self.data["layouts"]:
            return
        self.data["layouts"][name] = {"bg": "#0e0d14", "elements": []}
        self.current = name
        self._refresh_layout_cb()
        self._redraw()

    def _del_layout(self):
        if len(self.data["layouts"]) <= 1:
            return
        if messagebox.askyesno("Excluir", f"Excluir '{self.current}'?"):
            del self.data["layouts"][self.current]
            a = self.data["assign"]
            if a.get("home") == self.current:
                a["home"] = None
            a["per_exe"] = {k: v for k, v in a.get("per_exe", {}).items()
                            if v != self.current}
            self.current = next(iter(self.data["layouts"]))
            self._refresh_layout_cb()
            self._redraw()

    def _assign(self):
        target = self.assign_var.get().strip().lower()
        if not target:
            return
        if target.startswith("home"):
            self.data["assign"]["home"] = self.current
            msg = f"standby usa '{self.current}'"
        else:
            self.data["assign"].setdefault("per_exe", {})[target] = \
                self.current
            msg = f"{target} usa '{self.current}'"
        self._save()
        self.estatus.config(text=f"Atribuido: {msg}")


def _editor_mascot(img, t, blink):
    import widget_claude as wc
    from PIL import ImageDraw
    wc.draw_clawd(ImageDraw.Draw(img), img.width // 2,
                  img.height // 2 - 6, blink, legs_t=t, px=5)


# ---------- GUI ----------

class App:
    def __init__(self, root, start_hidden=False):
        self.root = root
        self.cfg = load_config()
        self.slideshow = Slideshow()
        self.slideshow.on_frame = self._on_slideshow_frame
        self.tray_icon = None

        # estado do editor de enquadramento
        self.img = None          # imagem original (RGB)
        self.scale = 1.0         # zoom atual (px da tela por px da imagem)
        self.ox = self.oy = 0.0  # canto sup. esquerdo do recorte, em px da imagem
        self._drag_start = None
        self._send_job = None
        self._widget_stop = threading.Event()
        self._widget_thread = None

        root.title("GPU Screen — AX206")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        main = ttk.Frame(notebook, padding=12)
        notebook.add(main, text="Tela")
        notebook.add(GamesPanel(notebook), text="Jogos")
        notebook.add(LayoutEditor(notebook), text="Editor")

        # preview interativo
        left = ttk.Frame(main)
        left.grid(row=0, column=0, rowspan=9, padx=(0, 14), sticky="n")
        self.preview = tk.Canvas(left, width=PREVIEW_W, height=PREVIEW_H,
                                 bg="#111", highlightthickness=1,
                                 highlightbackground="#888", cursor="fleur")
        self.preview.pack()
        ttk.Label(left, text="arraste p/ mover\nroda do mouse p/ zoom\nduplo clique p/ resetar",
                  foreground="#777", justify="center").pack(pady=(4, 0))
        self._preview_img = None
        self.preview.bind("<ButtonPress-1>", self._drag_begin)
        self.preview.bind("<B1-Motion>", self._drag_move)
        self.preview.bind("<MouseWheel>", self._wheel)
        self.preview.bind("<Double-Button-1>", self._reset_view)

        # acoes
        ttk.Button(main, text="Abrir imagem...", command=self.pick_image).grid(
            row=0, column=1, sticky="ew", pady=2)
        ttk.Button(main, text="Cor solida...", command=self.pick_color).grid(
            row=1, column=1, sticky="ew", pady=2)
        ttk.Button(main, text="Padrao de teste", command=self.send_test).grid(
            row=2, column=1, sticky="ew", pady=2)
        self.widget_button = ttk.Button(main, text="Widget Claude",
                                        command=self.toggle_widget)
        self.widget_button.grid(row=8, column=1, sticky="ew", pady=2)

        # brilho
        bright_row = ttk.Frame(main)
        bright_row.grid(row=3, column=1, sticky="ew", pady=(10, 2))
        ttk.Label(bright_row, text="Brilho").pack(side="left")
        self.brightness = tk.IntVar(value=self.cfg.get("brightness", 7))
        ttk.Scale(bright_row, from_=0, to=7, orient="horizontal",
                  variable=self.brightness,
                  command=self._brightness_dragged).pack(
            side="left", fill="x", expand=True, padx=6)
        self.bright_label = ttk.Label(bright_row, text=str(self.brightness.get()))
        self.bright_label.pack(side="left")

        # slideshow
        ttk.Separator(main).grid(row=4, column=1, sticky="ew", pady=8)
        ss = ttk.Frame(main)
        ss.grid(row=5, column=1, sticky="ew")
        ttk.Label(ss, text="Slideshow").grid(row=0, column=0, sticky="w")
        self.ss_folder = tk.StringVar(value=self.cfg.get("slideshow_folder", ""))
        ttk.Entry(ss, textvariable=self.ss_folder, width=24).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(ss, text="Pasta...", width=8, command=self.pick_folder).grid(
            row=1, column=2, padx=(4, 0))
        int_row = ttk.Frame(ss)
        int_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(int_row, text="Trocar a cada").pack(side="left")
        self.ss_interval = tk.IntVar(value=self.cfg.get("slideshow_interval", 10))
        ttk.Spinbox(int_row, from_=2, to=3600, width=5,
                    textvariable=self.ss_interval).pack(side="left", padx=4)
        ttk.Label(int_row, text="s").pack(side="left")
        self.ss_button = ttk.Button(ss, text="Iniciar slideshow",
                                    command=self.toggle_slideshow)
        self.ss_button.grid(row=3, column=0, columnspan=3, sticky="ew", pady=2)

        # opcoes
        ttk.Separator(main).grid(row=6, column=1, sticky="ew", pady=8)
        self.autostart = tk.BooleanVar(value=autostart_enabled())
        ttk.Checkbutton(main, text="Iniciar com o Windows",
                        variable=self.autostart,
                        command=self.toggle_autostart).grid(
            row=7, column=1, sticky="w")

        self.status = ttk.Label(main, text="", foreground="#555")
        self.status.grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self._draw_placeholder()
        self._load_saved_image()
        if start_hidden:
            root.withdraw()
            self._make_tray()

    # ----- infra -----

    def set_status(self, text):
        self.status.config(text=text)

    def _run_bg(self, fn, done_msg):
        def worker():
            try:
                fn()
                self.root.after(0, lambda: self.set_status(done_msg))
            except (AX206Error, usb.core.USBError) as e:
                msg = str(e) or "Falha na comunicacao USB (tela ocupada?)"
                self.root.after(0, lambda: self.set_status(f"Erro: {msg}"))
        threading.Thread(target=worker, daemon=True).start()

    def _persist(self, **kw):
        self.cfg.update(kw)
        save_config(self.cfg)

    # ----- preview / editor de enquadramento -----

    def _draw_placeholder(self):
        img = Image.new("RGB", (PREVIEW_W, PREVIEW_H), (25, 25, 30))
        d = ImageDraw.Draw(img)
        d.text((PREVIEW_W // 2, PREVIEW_H // 2), "sem imagem",
               fill=(120, 120, 130), anchor="mm")
        self._show_on_canvas(img)

    def _show_on_canvas(self, pil_img):
        pil_img = pil_img.resize((PREVIEW_W, PREVIEW_H))
        self._preview_img = ImageTk.PhotoImage(pil_img)
        self.preview.delete("all")
        self.preview.create_image(PREVIEW_W // 2, PREVIEW_H // 2,
                                  image=self._preview_img)

    def _load_saved_image(self):
        path = self.cfg.get("last_image")
        if self.cfg.get("mode") == "image" and path and os.path.exists(path):
            try:
                self.img = Image.open(path).convert("RGB")
                view = self.cfg.get("view")
                if view:
                    self.scale = view["scale"]
                    self.ox, self.oy = view["ox"], view["oy"]
                else:
                    self._center_cover()
                self._refresh_preview()
            except OSError:
                self.img = None

    def _center_cover(self):
        self.scale = cover_scale(self.img)
        self.ox = (self.img.width - AX206.WIDTH / self.scale) / 2
        self.oy = (self.img.height - AX206.HEIGHT / self.scale) / 2

    def _refresh_preview(self):
        if self.img is None:
            return
        self.ox, self.oy = clamp_view(self.img, self.scale, self.ox, self.oy)
        self._show_on_canvas(compose_view(self.img, self.scale, self.ox, self.oy))

    def _schedule_send(self):
        """Envia pra tela 500ms depois da ultima interacao."""
        if self._send_job:
            self.root.after_cancel(self._send_job)
        self._send_job = self.root.after(500, self._send_current_view)

    def _send_current_view(self):
        self._send_job = None
        if self.img is None:
            return
        final = compose_view(self.img, self.scale, self.ox, self.oy)
        self._persist(mode="image",
                      view={"scale": self.scale, "ox": self.ox, "oy": self.oy})
        self._run_bg(lambda: send_pil_image(final), "Enviado")

    def _drag_begin(self, ev):
        self._drag_start = (ev.x, ev.y, self.ox, self.oy)

    def _drag_move(self, ev):
        if self.img is None or self._drag_start is None:
            return
        x0, y0, ox0, oy0 = self._drag_start
        # preview -> tela: PREVIEW_W/AX206.WIDTH; tela -> imagem: 1/scale
        px_to_img = (AX206.WIDTH / PREVIEW_W) / self.scale
        self.ox = ox0 - (ev.x - x0) * px_to_img
        self.oy = oy0 - (ev.y - y0) * px_to_img
        self._refresh_preview()
        self._schedule_send()

    def _wheel(self, ev):
        if self.img is None:
            return
        factor = 1.1 if ev.delta > 0 else 1 / 1.1
        new_scale = self.scale * factor
        min_s = cover_scale(self.img)
        new_scale = max(min_s, min(new_scale, min_s * 8))
        # zoom centrado no ponto do mouse
        img_x = self.ox + (ev.x / PREVIEW_W) * (AX206.WIDTH / self.scale)
        img_y = self.oy + (ev.y / PREVIEW_H) * (AX206.HEIGHT / self.scale)
        self.scale = new_scale
        self.ox = img_x - (ev.x / PREVIEW_W) * (AX206.WIDTH / self.scale)
        self.oy = img_y - (ev.y / PREVIEW_H) * (AX206.HEIGHT / self.scale)
        self._refresh_preview()
        self._schedule_send()

    def _reset_view(self, _ev=None):
        if self.img is None:
            return
        self._center_cover()
        self._refresh_preview()
        self._schedule_send()

    # ----- acoes -----

    def pick_image(self):
        path = filedialog.askopenfilename(
            title="Escolher imagem",
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.bmp *.gif *.webp"),
                       ("Todos", "*.*")])
        if not path:
            return
        self.stop_slideshow()
        self.stop_widget()
        try:
            self.img = Image.open(path).convert("RGB")
        except OSError as e:
            messagebox.showerror("Imagem", str(e))
            return
        self._center_cover()
        self._persist(mode="image", last_image=path,
                      view={"scale": self.scale, "ox": self.ox, "oy": self.oy})
        self._refresh_preview()
        self._send_current_view()
        self.set_status(f"{os.path.basename(path)} — ajuste com o mouse")

    def pick_color(self):
        rgb, _hex = colorchooser.askcolor(title="Cor solida")
        if not rgb:
            return
        self.stop_slideshow()
        self.stop_widget()
        self.img = None
        rgb = tuple(int(c) for c in rgb)
        img = Image.new("RGB", (AX206.WIDTH, AX206.HEIGHT), rgb)
        self._show_on_canvas(img)
        self._persist(mode="fill", fill_color=list(rgb))
        self._run_bg(lambda: send_pil_image(img), f"Cor {_hex} enviada")

    def send_test(self):
        self.stop_slideshow()
        self.stop_widget()
        self.img = None
        img = Image.new("RGB", (AX206.WIDTH, AX206.HEIGHT))
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
                  (255, 0, 255), (0, 255, 255), (255, 255, 255), (0, 0, 0)]
        d = ImageDraw.Draw(img)
        band = AX206.WIDTH // len(colors)
        for i, c in enumerate(colors):
            d.rectangle((i * band, 0, (i + 1) * band - 1, AX206.HEIGHT), fill=c)
        self._show_on_canvas(img)
        self._run_bg(lambda: send_pil_image(img), "Padrao de teste enviado")

    def _brightness_dragged(self, value):
        v = int(float(value))
        self.bright_label.config(text=str(v))
        if getattr(self, "_bright_job", None):
            self.root.after_cancel(self._bright_job)
        self._bright_job = self.root.after(300, self._apply_brightness)

    def _apply_brightness(self):
        self._bright_job = None
        v = self.brightness.get()
        self._persist(brightness=v)
        msg = "Brilho: 0 (tela apagada)" if v == 0 else f"Brilho: {v}"
        self._run_bg(lambda: lcd_call(lambda lcd: lcd.set_brightness(v)), msg)

    def pick_folder(self):
        folder = filedialog.askdirectory(title="Pasta do slideshow")
        if folder:
            self.ss_folder.set(folder)

    def toggle_slideshow(self):
        if self.slideshow.running:
            self.stop_slideshow()
            return
        folder = self.ss_folder.get()
        if not os.path.isdir(folder):
            messagebox.showwarning("Slideshow", "Escolha uma pasta valida.")
            return
        interval = max(2, self.ss_interval.get())
        self.stop_widget()
        self._persist(mode="slideshow", slideshow_folder=folder,
                      slideshow_interval=interval)
        self.img = None
        self.slideshow.start(folder, interval)
        self.ss_button.config(text="Parar slideshow")
        self.set_status("Slideshow rodando")

    def stop_slideshow(self):
        if self.slideshow.running:
            self.slideshow.stop()
        self.ss_button.config(text="Iniciar slideshow")

    def _on_slideshow_frame(self, path):
        def update():
            try:
                img = Image.open(path).convert("RGB")
                self._show_on_canvas(compose_view(img, cover_scale(img), 0, 0))
                self.set_status(f"Slideshow: {os.path.basename(path)}")
            except OSError:
                pass
        self.root.after(0, update)

    # ----- widget Claude -----

    @property
    def widget_running(self):
        return self._widget_thread is not None and self._widget_thread.is_alive()

    def toggle_widget(self):
        if self.widget_running:
            self.stop_widget()
            return
        self.start_widget()

    def start_widget(self):
        self.stop_slideshow()
        self.img = None
        self._widget_stop.clear()

        def send_full(img):
            lcd_call(lambda lcd: lcd.show_image(img))

        def send_region(x, y, img):
            data = AX206.image_to_rgb565(img)
            lcd_call(lambda lcd: lcd.blit(x, y, img.width, img.height, data))

        loop = widget_claude.WidgetLoop(send_full, send_region)

        def worker():
            try:
                loop.run(self._widget_stop.is_set)
            except (AX206Error, usb.core.USBError) as e:
                self.root.after(0, lambda: self.set_status(f"Widget parou: {e}"))

        self._widget_thread = threading.Thread(target=worker, daemon=True)
        self._widget_thread.start()
        self._persist(mode="widget")
        self.widget_button.config(text="Parar widget")
        self.set_status("Widget Claude rodando (surf, bola e soneca)")

    def stop_widget(self):
        self._widget_stop.set()
        if self._widget_thread:
            self._widget_thread.join(timeout=2)
            self._widget_thread = None
        self.widget_button.config(text="Widget Claude")

    def toggle_autostart(self):
        try:
            set_autostart(self.autostart.get())
            self.set_status("Iniciar com o Windows: "
                            + ("ativado" if self.autostart.get() else "desativado"))
        except OSError as e:
            messagebox.showerror("Autostart", str(e))

    # ----- bandeja -----

    def _tray_image(self):
        img = Image.new("RGB", (64, 64), (40, 20, 90))
        d = ImageDraw.Draw(img)
        d.rectangle((8, 4, 56, 60), outline=(255, 255, 255), width=4)
        d.rectangle((18, 18, 46, 34), fill=(120, 255, 180))
        return img

    def _make_tray(self):
        if self.tray_icon:
            return
        import pystray

        def show(icon, item):
            self.root.after(0, self.show_window)

        def quit_app(icon, item):
            icon.stop()
            self.root.after(0, self.quit)

        menu = pystray.Menu(
            pystray.MenuItem("Abrir", show, default=True),
            pystray.MenuItem("Sair", quit_app),
        )
        self.tray_icon = pystray.Icon("ax206", self._tray_image(),
                                      "GPU Screen", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_to_tray(self):
        self._make_tray()
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()

    def quit(self):
        self.stop_slideshow()
        self.stop_widget()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()


def main():
    restore = "--restore" in sys.argv
    root = tk.Tk()
    app = App(root, start_hidden=restore)
    if restore:
        if app.cfg.get("mode") == "widget":
            root.after(500, app.start_widget)
        else:
            threading.Thread(
                target=restore_state, args=(app.cfg, app.slideshow), daemon=True
            ).start()
    root.mainloop()


if __name__ == "__main__":
    main()

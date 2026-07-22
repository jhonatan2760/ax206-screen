"""
Suite de configuracao da telinha AX206 do suporte de GPU.

Janela para enviar imagem com posicionamento por mouse (arrastar/zoom),
brilho, cor solida, slideshow de pasta, bandeja do sistema e iniciar
com o Windows restaurando o ultimo estado.

Uso:
  python suite.py            # abre a janela
  python suite.py --restore  # aplica o ultimo estado e fica na bandeja (boot)
"""

import json
import os
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

        main = ttk.Frame(root, padding=12)
        main.grid()

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

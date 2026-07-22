"""
Suite de configuracao da telinha AX206 do suporte de GPU.

Janela para enviar imagem, ajustar brilho, cor solida, slideshow de pasta,
minimizar para a bandeja e iniciar com o Windows restaurando o ultimo estado.

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

from PIL import Image, ImageDraw, ImageTk

from ax206 import AX206, AX206Error

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "AX206Screen"


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


# ---------- acesso a tela (abre por operacao, evita conflito) ----------

_lcd_lock = threading.Lock()


def lcd_call(fn):
    """Abre a tela, executa fn(lcd) e fecha. Serializado por lock."""
    with _lcd_lock:
        lcd = AX206()
        try:
            return fn(lcd)
        finally:
            del lcd


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
        self.on_frame = None  # callback(caminho) p/ atualizar preview

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
                except (AX206Error, OSError):
                    pass  # tela ocupada ou arquivo invalido: tenta o proximo
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
            send_pil_image(Image.open(cfg["last_image"]))
        elif mode == "fill" and cfg.get("fill_color"):
            r, g, b = cfg["fill_color"]
            send_pil_image(Image.new("RGB", (AX206.WIDTH, AX206.HEIGHT), (r, g, b)))
    except (AX206Error, OSError):
        pass


# ---------- GUI ----------

class App:
    def __init__(self, root, start_hidden=False):
        self.root = root
        self.cfg = load_config()
        self.slideshow = Slideshow()
        self.slideshow.on_frame = self._on_slideshow_frame
        self.tray_icon = None

        root.title("GPU Screen — AX206")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        main = ttk.Frame(root, padding=12)
        main.grid()

        # preview
        self.preview = tk.Canvas(main, width=180, height=240, bg="#111",
                                 highlightthickness=1, highlightbackground="#888")
        self.preview.grid(row=0, column=0, rowspan=8, padx=(0, 14))
        self._preview_img = None

        # imagem
        ttk.Button(main, text="Enviar imagem...", command=self.pick_image).grid(
            row=0, column=1, sticky="ew", pady=2)
        ttk.Button(main, text="Cor solida...", command=self.pick_color).grid(
            row=1, column=1, sticky="ew", pady=2)
        ttk.Button(main, text="Padrao de teste", command=self.send_test).grid(
            row=2, column=1, sticky="ew", pady=2)

        # brilho
        bright_row = ttk.Frame(main)
        bright_row.grid(row=3, column=1, sticky="ew", pady=(10, 2))
        ttk.Label(bright_row, text="Brilho").pack(side="left")
        self.brightness = tk.IntVar(value=self.cfg.get("brightness", 7))
        self.bright_scale = ttk.Scale(
            bright_row, from_=0, to=7, orient="horizontal",
            variable=self.brightness, command=self._brightness_dragged)
        self.bright_scale.pack(side="left", fill="x", expand=True, padx=6)
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
        self.status.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self._draw_placeholder()
        if start_hidden:
            root.withdraw()
            self._make_tray()

    # ----- helpers -----

    def set_status(self, text):
        self.status.config(text=text)

    def _run_bg(self, fn, done_msg):
        def worker():
            try:
                fn()
                self.root.after(0, lambda: self.set_status(done_msg))
            except AX206Error as e:
                self.root.after(0, lambda: messagebox.showerror("Tela", str(e)))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Erro", str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def _draw_placeholder(self):
        img = Image.new("RGB", (180, 240), (25, 25, 30))
        d = ImageDraw.Draw(img)
        d.text((90, 120), "sem imagem", fill=(120, 120, 130), anchor="mm")
        self._set_preview(img)

    def _set_preview(self, pil_img):
        pil_img = pil_img.copy()
        pil_img.thumbnail((180, 240))
        self._preview_img = ImageTk.PhotoImage(pil_img)
        self.preview.delete("all")
        self.preview.create_image(90, 120, image=self._preview_img)

    def _persist(self, **kw):
        self.cfg.update(kw)
        save_config(self.cfg)

    # ----- acoes -----

    def pick_image(self):
        path = filedialog.askopenfilename(
            title="Escolher imagem",
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.bmp *.gif *.webp"),
                       ("Todos", "*.*")])
        if not path:
            return
        self.stop_slideshow()
        img = Image.open(path)
        self._set_preview(img)
        self._persist(mode="image", last_image=path)
        self._run_bg(lambda: send_pil_image(img), f"Imagem enviada: {os.path.basename(path)}")

    def pick_color(self):
        rgb, _hex = colorchooser.askcolor(title="Cor solida")
        if not rgb:
            return
        self.stop_slideshow()
        rgb = tuple(int(c) for c in rgb)
        img = Image.new("RGB", (AX206.WIDTH, AX206.HEIGHT), rgb)
        self._set_preview(img)
        self._persist(mode="fill", fill_color=list(rgb))
        self._run_bg(lambda: send_pil_image(img), f"Cor {_hex} enviada")

    def send_test(self):
        self.stop_slideshow()
        img = Image.new("RGB", (AX206.WIDTH, AX206.HEIGHT))
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
                  (255, 0, 255), (0, 255, 255), (255, 255, 255), (0, 0, 0)]
        d = ImageDraw.Draw(img)
        band = AX206.WIDTH // len(colors)
        for i, c in enumerate(colors):
            d.rectangle((i * band, 0, (i + 1) * band - 1, AX206.HEIGHT), fill=c)
        self._set_preview(img)
        self._run_bg(lambda: send_pil_image(img), "Padrao de teste enviado")

    def _brightness_dragged(self, _value):
        v = int(float(_value))
        self.bright_label.config(text=str(v))
        # aplica ao soltar? aplica com debounce simples
        if getattr(self, "_bright_job", None):
            self.root.after_cancel(self._bright_job)
        self._bright_job = self.root.after(300, self._apply_brightness)

    def _apply_brightness(self):
        self._bright_job = None
        v = self.brightness.get()
        self._persist(brightness=v)
        self._run_bg(lambda: lcd_call(lambda lcd: lcd.set_brightness(v)),
                     f"Brilho: {v}")

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
        self._persist(mode="slideshow", slideshow_folder=folder,
                      slideshow_interval=interval)
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
                self._set_preview(Image.open(path))
                self.set_status(f"Slideshow: {os.path.basename(path)}")
            except OSError:
                pass
        self.root.after(0, update)

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
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()


def main():
    restore = "--restore" in sys.argv
    root = tk.Tk()
    app = App(root, start_hidden=restore)
    if restore:
        threading.Thread(
            target=restore_state, args=(app.cfg, app.slideshow), daemon=True
        ).start()
    root.mainloop()


if __name__ == "__main__":
    main()

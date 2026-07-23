"""Compositor de camadas: cada tela segue os bboxes do manifest e atualiza
por dirty-rect — camada so e reenviada quando o estado dela muda."""

import time
from datetime import datetime

from PIL import Image, ImageDraw

from . import keyart, widgets as W, palette as P


class Layer:
    def __init__(self, bbox, render, key=None, animated=False):
        self.bbox = bbox              # (x, y, w, h)
        self.render = render          # (state, t) -> PIL.Image do tamanho bbox
        self.key = key or (lambda s: None)  # muda -> rerender
        self.animated = animated      # True: rerender toda chamada
        self._last = object()


class Screen:
    def __init__(self, layers):
        self.layers = layers
        self._pushed = False

    def reset(self):
        self._pushed = False
        for l in self.layers:
            l._last = object()

    def push(self, lcd, state, t):
        """Primeira chamada: frame cheio. Depois: so camadas sujas."""
        if not self._pushed:
            full = Image.new("RGB", (240, 320), (0, 0, 0))
            for l in self.layers:
                img = l.render(state, t)
                full.paste(img, l.bbox[:2])
                l._last = l.key(state)
            lcd.show_image(full)
            self._pushed = True
            return
        for l in self.layers:
            k = l.key(state)
            if l.animated or k != l._last:
                img = l.render(state, t)
                lcd.blit(l.bbox[0], l.bbox[1], img.width, img.height,
                         type(lcd).image_to_rgb565(img))
                l._last = k


# ---------- GAME ----------

def _crop(img, bbox):
    x, y, w, h = bbox
    return img.crop((x, y, x + w, y + h))


def make_game_screen():
    bg = keyart.bg_game()

    def r_bg(s, t):
        return bg

    def r_art(s, t):
        return keyart.art_panel(s["title"], s.get("exe"))

    def r_badges(s, t):
        img = _crop(bg, (10, 96, 220, 66)).copy()
        items = s["badges"][:4]
        for i, (label, family, active) in enumerate(items):
            b = W.badge(label, family, active)
            img.paste(b, ((i % 2) * 114, (i // 2) * 36))
        return img

    def r_gauge(s, t):
        return W.radial_gauge(s["gpu"])

    def r_side(s, t):
        return W.side_readout(s["temp"], s["vram"])

    def r_status(s, t):
        return W.statusbar(s.get("status_left", "REFLEX ON"),
                           s.get("status_right", ""), active=True)

    return Screen([
        Layer((0, 0, 240, 320), r_bg),
        Layer((10, 10, 220, 76), r_art, key=lambda s: s["title"]),
        Layer((10, 96, 220, 66), r_badges,
              key=lambda s: tuple(map(tuple, s["badges"]))),
        Layer((18, 171, 100, 100), r_gauge, key=lambda s: round(s["gpu"])),
        Layer((132, 180, 88, 80), r_side,
              key=lambda s: (round(s["temp"]), round(s["vram"], 1))),
        Layer((0, 294, 240, 26), r_status,
              key=lambda s: (s.get("status_left"), s.get("status_right"))),
    ])


# ---------- AI ----------

def make_ai_screen():
    bg = keyart.bg_ai()

    def r_bg(s, t):
        return bg

    def r_task(s, t):
        img = _crop(bg, (16, 58, 208, 14)).copy()
        ImageDraw.Draw(img).text((0, 7), s.get("task", "local inference"),
                                 font=P.F12, fill=P.TEXT_DIM, anchor="lm")
        return img

    def r_main(s, t):
        return W.scan_panel(s["gpu"], t)

    def r_temp(s, t):
        return W.metric_card("GPU TEMP", f"{s['temp']:.0f}°C",
                             s["temp"] / 110, P.AMBER)

    def r_vram(s, t):
        return W.metric_card("VRAM", f"{s['vram']:.1f} GB",
                             s["vram"] / max(s.get("vram_total", 16), 1),
                             P.TERM_GREEN)

    def r_console(s, t):
        return W.console(s.get("console", []))

    def r_status(s, t):
        busy = s["gpu"] >= 20
        return W.statusbar("BUSY" if busy else "READY",
                           f"{s['gpu']:.0f}% GPU", active=busy)

    return Screen([
        Layer((0, 0, 240, 320), r_bg),
        Layer((16, 58, 208, 14), r_task, key=lambda s: s.get("task")),
        Layer((12, 80, 216, 60), r_main, animated=True),
        Layer((12, 148, 102, 44), r_temp, key=lambda s: round(s["temp"])),
        Layer((126, 148, 102, 44), r_vram,
              key=lambda s: round(s["vram"], 1)),
        Layer((12, 200, 216, 86), r_console,
              key=lambda s: tuple(s.get("console", []))),
        Layer((0, 294, 240, 26), r_status,
              key=lambda s: (s["gpu"] >= 20, round(s["gpu"]))),
    ])


# ---------- IDLE (design + Clawd animado no slot do mascote) ----------

def make_idle_screen(draw_mascot):
    """draw_mascot(img_120x108, t, blink) desenha o Clawd no slot."""
    bg = keyart.bg_idle()

    def r_bg(s, t):
        return bg

    def r_header(s, t):
        img = _crop(bg, (12, 12, 216, 22)).copy()
        ImageDraw.Draw(img).text(
            (108, 11), datetime.now().strftime("%a %d %b").upper(),
            font=P.F14, fill=P.TEXT_DIM, anchor="mm")
        return img

    def r_mascot(s, t):
        img = _crop(bg, (60, 40, 120, 108)).copy()
        draw_mascot(img, t, s.get("blink", False))
        return img

    def r_clock(s, t):
        img = _crop(bg, (0, 164, 240, 44)).copy()
        ImageDraw.Draw(img).text((120, 22),
                                 datetime.now().strftime("%H:%M"),
                                 font=P.F40, fill=P.TEXT, anchor="mm")
        return img

    def r_stats(s, t):
        img = Image.new("RGB", (216, 74), P.BG_IDLE)
        img.paste(W.hbar("CPU", s.get("cpu", 0), P.CORAL), (0, 2))
        img.paste(W.hbar("RAM", s.get("ram", 0), P.SCANNER_CYAN), (0, 27))
        img.paste(W.hbar("GPU", s.get("gpu", 0), P.NEON_GREEN), (0, 52))
        return img

    def r_status(s, t):
        return W.statusbar("NOMINAL", s.get("uptime", ""), active=False)

    return Screen([
        Layer((0, 0, 240, 320), r_bg),
        Layer((12, 12, 216, 22), r_header,
              key=lambda s: datetime.now().strftime("%d%H%M")[:6]),
        Layer((60, 40, 120, 108), r_mascot, animated=True),
        Layer((0, 164, 240, 44), r_clock,
              key=lambda s: datetime.now().strftime("%H:%M")),
        Layer((12, 216, 216, 74), r_stats,
              key=lambda s: (round(s.get("cpu", 0)), round(s.get("ram", 0)),
                             round(s.get("gpu", 0)))),
        Layer((0, 294, 240, 26), r_status, key=lambda s: s.get("uptime")),
    ])

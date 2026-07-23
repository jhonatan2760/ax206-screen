"""Widgets programaticos do design system: badges skewed, gauge radial,
barras, cards e status bar. Cada funcao desenha dentro do proprio bbox."""

import math

from PIL import Image, ImageDraw

from . import palette as P

SKEW = math.tan(math.radians(13))  # skewX -13deg do design


def _skew_rect(d, x0, y0, x1, y1, fill=None, outline=None, width=1):
    """Paralelogramo com topo deslocado p/ direita (skewX -13)."""
    off = (y1 - y0) * SKEW
    d.polygon([(x0 + off, y0), (x1 + off, y0), (x1, y1), (x0, y1)],
              fill=fill, outline=outline, width=width)


# ---------- badge skewed two-tone (106x30) ----------

BADGE_W, BADGE_H = 106, 30

FAMILY_COLOR = {"NVIDIA": P.NEON_GREEN, "RT": P.RT_PURPLE, "AMD": P.AMBER}


def badge(label, family, active, w=BADGE_W, h=BADGE_H):
    """Badge do design: slab do nome + slab ON/OFF, divisor diagonal."""
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    color = FAMILY_COLOR.get(family, P.NEON_GREEN) if active else P.BADGE_OFF
    state_w = 34
    margin = int(h * SKEW) + 1

    # rotulo longo: slab unico + LED de estado (nome inteiro legivel)
    d_tmp = ImageDraw.Draw(img)
    if d_tmp.textlength(label, font=P.F12) > w - state_w - 14 - margin:
        _skew_rect(d, 2, 2, w - margin - 1, h - 2,
                   fill=(18, 22, 28) if active else (14, 16, 20),
                   outline=color, width=2)
        led_x = w - margin - 14
        text_x = 9 + margin // 2
        avail = led_x - 8 - text_x
        font = P.F12 if d_tmp.textlength(label, font=P.F12) <= avail else P.F11
        d.text((text_x, h // 2), label, font=font,
               fill=P.TEXT if active else color, anchor="lm")
        d.ellipse((led_x - 4, h // 2 - 4, led_x + 4, h // 2 + 4),
                  fill=color if active else (26, 30, 38),
                  outline=color, width=1)
        return img

    if active:
        # slab do nome: fundo escuro com borda; slab do estado: cor cheia
        _skew_rect(d, 2, 2, w - state_w, h - 2, fill=(18, 22, 28),
                   outline=color, width=2)
        _skew_rect(d, w - state_w, 2, w - margin - 1, h - 2, fill=color)
        state_txt, state_fill = "ON", (
            (0x24, 0x18, 0x00) if family == "AMD" else P.TEXT)
        name_fill = P.TEXT
    else:
        _skew_rect(d, 2, 2, w - state_w, h - 2, fill=(14, 16, 20),
                   outline=color, width=2)
        _skew_rect(d, w - state_w, 2, w - margin - 1, h - 2,
                   fill=(26, 30, 38), outline=color, width=2)
        state_txt, state_fill = "OFF", color
        name_fill = color

    font = P.F14 if d.textlength(label, font=P.F14) <= w - state_w - 14 - margin else P.F12
    d.text((8 + margin // 2, h // 2), label, font=font, fill=name_fill,
           anchor="lm")
    d.text((w - state_w // 2 - margin // 2 - 1, h // 2), state_txt,
           font=P.F12, fill=state_fill, anchor="mm")
    return img


# ---------- gauge radial (100x100) ----------

def radial_gauge(value, size=100, label="GPU", sub="LOAD %"):
    img = Image.new("RGB", (size, size), P.BG_GRAPHITE)
    d = ImageDraw.Draw(img)
    c = size // 2
    r_ring = c - 12

    # tick ring externo tracejado (r47, dash 1.5/9.3 ~ 27 ticks)
    r_tick = c - 3
    for i in range(27):
        a = math.radians(i * 360 / 27 - 90)
        x0 = c + (r_tick - 2) * math.cos(a)
        y0 = c + (r_tick - 2) * math.sin(a)
        x1 = c + r_tick * math.cos(a)
        y1 = c + r_tick * math.sin(a)
        d.line((x0, y0, x1, y1), fill=P.TICK_RING, width=2)

    # trilho + arco de valor (comeca 12h)
    box = (c - r_ring, c - r_ring, c + r_ring, c + r_ring)
    d.arc(box, 0, 360, fill=P.GAUGE_TRACK, width=7)
    val = max(0, min(100, value))
    color = P.NEON_GREEN if val < 92 else P.RED_ALERT
    d.arc(box, -90, -90 + 360 * val / 100, fill=color, width=7)

    d.text((c, c - 24), label, font=P.F12, fill=P.LABEL, anchor="mm")
    d.text((c, c), f"{val:.0f}", font=P.F33, fill=P.NEON_BRIGHT
           if val < 92 else P.RED_ALERT, anchor="mm")
    d.text((c, c + 22), sub, font=P.F12, fill=P.LABEL, anchor="mm")
    return img


# ---------- leitura lateral: temp + vram (88x80) ----------

def side_readout(temp, vram_gb, w=88, h=80):
    img = Image.new("RGB", (w, h), P.BG_GRAPHITE)
    d = ImageDraw.Draw(img)
    tcolor = P.AMBER if temp < 85 else P.RED_ALERT
    # termometro
    d.rounded_rectangle((4, 6, 10, 26), radius=3, outline=tcolor, width=2)
    d.ellipse((2, 24, 12, 34), fill=tcolor)
    d.text((20, 8), f"{temp:.0f}°", font=P.F22, fill=tcolor)
    d.text((20, 32), "GPU TEMP", font=P.F12, fill=P.LABEL)

    # camadas (vram)
    for i in range(3):
        d.polygon([(7, 56 + i * 5), (14, 53 + i * 5), (21, 56 + i * 5),
                   (14, 59 + i * 5)], outline=P.TEXT, width=1)
    d.text((28, 46), f"{vram_gb:.1f}", font=P.F18, fill=P.TEXT)
    gb_x = 28 + d.textlength(f"{vram_gb:.1f}", font=P.F18) + 2
    d.text((gb_x, 50), "GB", font=P.F12, fill=P.TEXT_DIM)
    d.text((28, 66), "VRAM", font=P.F12, fill=P.LABEL)
    return img


# ---------- status bar (240x26) ----------

def statusbar(text_left, text_right, active=True, w=240, h=26):
    img = Image.new("RGB", (w, h), P.NEON_GREEN if active else (26, 30, 38))
    d = ImageDraw.Draw(img)
    fg = (10, 14, 8) if active else P.TEXT_DIM
    d.ellipse((10, h // 2 - 3, 16, h // 2 + 3), fill=fg)
    d.text((24, h // 2), text_left, font=P.F14, fill=fg, anchor="lm")
    d.text((w - 10, h // 2), text_right, font=P.F16, fill=fg, anchor="rm")
    return img


# ---------- barra com scanner (painel principal AI, 216x60) ----------

def scan_panel(value, t, w=216, h=60):
    img = Image.new("RGB", (w, h), P.BG_AI)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=8,
                        outline=P.TERM_DIM, width=2)
    d.text((10, 8), "PROCESSING", font=P.F12, fill=P.TERM_DIM)
    d.text((w - 10, 8), f"{value:.0f}%", font=P.F16, fill=P.TERM_GREEN,
           anchor="ra")
    bx0, bx1, by0, by1 = 10, w - 10, 30, 50
    d.rounded_rectangle((bx0, by0, bx1, by1), radius=5,
                        outline=P.TERM_DIM, width=2)
    fill_w = int((bx1 - bx0 - 6) * max(0, min(100, value)) / 100)
    if fill_w > 4:
        d.rounded_rectangle((bx0 + 3, by0 + 3, bx0 + 3 + fill_w, by1 - 3),
                            radius=3, fill=P.TERM_DIM)
        sw = 14
        sx = bx0 + 3 + int((fill_w - sw) * (0.5 + 0.5 * math.sin(t * 3.2)))
        if sx > bx0 + 2:
            d.rounded_rectangle((sx, by0 + 3, sx + sw, by1 - 3), radius=3,
                                fill=P.SCANNER_CYAN)
    return img


# ---------- card metrica (102x44) ----------

def metric_card(label, value_txt, frac, color, w=102, h=44):
    img = Image.new("RGB", (w, h), P.BG_AI)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=6,
                        outline=P.PANEL_LINE, width=2)
    d.text((8, 5), label, font=P.F12, fill=P.LABEL)
    d.text((8, 18), value_txt, font=P.F16, fill=color)
    bw = int((w - 16) * max(0, min(1, frac)))
    d.rectangle((8, h - 8, w - 8, h - 5), fill=(30, 36, 34))
    if bw > 0:
        d.rectangle((8, h - 8, 8 + bw, h - 5), fill=color)
    return img


# ---------- console (216x86) ----------

def console(lines, w=216, h=86):
    img = Image.new("RGB", (w, h), (8, 12, 10))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=6,
                        outline=P.TERM_DIM, width=2)
    y = 8
    for ln in lines[-4:]:
        d.text((10, y), "> " + ln[:30], font=P.F12R, fill=P.TERM_GREEN)
        y += 19
    return img


# ---------- barra horizontal simples (stats idle) ----------

def hbar(label, pct, color, w=216, h=20):
    img = Image.new("RGB", (w, h), P.BG_IDLE)
    d = ImageDraw.Draw(img)
    d.text((0, h // 2), label, font=P.F12, fill=P.LABEL, anchor="lm")
    bx0 = 46
    d.rounded_rectangle((bx0, 4, w - 40, h - 4), radius=4,
                        outline=P.PANEL_LINE, width=1)
    bw = int((w - 40 - bx0 - 4) * max(0, min(100, pct)) / 100)
    if bw > 2:
        d.rounded_rectangle((bx0 + 2, 6, bx0 + 2 + bw, h - 6), radius=3,
                            fill=color)
    d.text((w, h // 2), f"{pct:.0f}%", font=P.F12, fill=P.TEXT,
           anchor="rm")
    return img

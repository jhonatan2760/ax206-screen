"""
Widget animado para a telinha AX206: mascote do Claude Code + uso do dia.

Cenas que alternam sozinhas: parado (flutuando/piscando), surfando e
jogando bola. Le os transcripts locais do Claude Code
(~/.claude/projects/**/*.jsonl) e soma os tokens de hoje.

Uso standalone:
  python widget_claude.py           # roda ate Ctrl+C
(tambem e usado pela suite.py como modo "Widget Claude")
"""

import glob
import json
import math
import os
import time
from datetime import date, datetime

from PIL import Image, ImageDraw, ImageFont

from ax206 import AX206

BG = (24, 18, 16)          # fundo escuro quente
ORANGE = (217, 119, 87)    # laranja Claude
ORANGE_DARK = (170, 85, 60)
CREAM = (240, 238, 230)
GRAY = (150, 143, 138)
SEA = (36, 90, 120)
SEA_LIGHT = (70, 140, 170)
GRASS = (46, 96, 52)
BALL_W = (235, 235, 230)

ANIM_BOX = (10, 16, 230, 176)     # regiao animada 220x160
SCENE_SECONDS = 12                # troca de cena


# ---------- uso do Claude Code ----------

def usage_today():
    """Soma tokens de hoje nos transcripts locais do Claude Code."""
    root = os.path.expanduser("~/.claude/projects")
    today = date.today()
    tin = tout = msgs = 0
    cutoff = time.time() - 36 * 3600
    for path in glob.glob(os.path.join(root, "*", "*.jsonl")):
        try:
            if os.path.getmtime(path) < cutoff:
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if '"usage"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    ts = rec.get("timestamp", "")
                    if not ts or date.fromisoformat(ts[:10]) != today:
                        continue
                    u = (rec.get("message") or {}).get("usage") or {}
                    tin += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                    tout += u.get("output_tokens", 0)
                    msgs += 1
        except OSError:
            continue
    return tin, tout, msgs


def fmt(n):
    if n >= 1_000_000:
        return f"{n/1e6:.1f}M"
    if n >= 1_000:
        return f"{n/1e3:.0f}k"
    return str(n)


# ---------- mascote (Clawd em pixel art 8-bit) ----------

# Clawd oficial: retangulo laranja, dois olhos = barrinhas verticais finas,
# bracinhos retos nas laterais e 4 perninhas curtas embaixo.
CLAWD_W = 14   # células de largura do corpo
CLAWD_H = 10   # células de altura do corpo


def draw_clawd(d, x, y, blink, legs_t=None, tilt=0, px=6):
    """Clawd 8-bit centrado em (x, y). px = tamanho do pixel (célula)."""
    gw, gh = CLAWD_W, CLAWD_H
    x0 = x - gw * px // 2
    y0 = y - gh * px // 2
    t = legs_t if legs_t is not None else 0

    # corpo retangular liso
    d.rectangle((x0, y0, x0 + gw * px - 1, y0 + gh * px - 1), fill=ORANGE)

    # olhos: barrinhas verticais finas (meia célula de largura, 2 células de altura)
    eye_w = max(2, px // 2)
    eye_h = 2 * px
    eye_y = y0 + 2 * px
    for ex_cell in (2, 11):
        ex = x0 + ex_cell * px + (px - eye_w) // 2
        if blink:
            d.rectangle((ex - px // 2, eye_y + eye_h - 2,
                         ex + eye_w + px // 2, eye_y + eye_h), fill=(20, 16, 14))
        else:
            d.rectangle((ex, eye_y, ex + eye_w - 1, eye_y + eye_h - 1),
                        fill=(20, 16, 14))

    # bracinhos: retangulos retos saindo do meio das laterais (balancam)
    arm_h = px
    for side in (-1, 1):
        lift = int(px * 0.7 * math.sin(t * 2.5 + (0 if side < 0 else math.pi)))
        ay = y0 + 4 * px + lift
        if side < 0:
            d.rectangle((x0 - 2 * px, ay, x0 - 1, ay + arm_h + px // 2 - 1),
                        fill=ORANGE)
        else:
            d.rectangle((x0 + gw * px, ay,
                         x0 + gw * px + 2 * px - 1, ay + arm_h + px // 2 - 1),
                        fill=ORANGE)

    # perninhas: 4 stubs (2 pares), alternam comprimento ao "andar"
    if legs_t is not None:
        for i, cell in enumerate((2, 4, 9, 11)):
            step = int(px * 0.5 * math.sin(legs_t * 6 + i * 1.7))
            lx = x0 + cell * px
            d.rectangle((lx, y0 + gh * px, lx + px - 1,
                         y0 + gh * px + int(1.5 * px) + step), fill=ORANGE)


# ---------- cenas (desenham dentro de 220x160) ----------

def scene_idle(d, w, h, t, blink):
    bob = int(4 * math.sin(t * 2.2))
    sway = int(2 * math.sin(t * 1.1))
    draw_clawd(d, w // 2 + sway, h // 2 - 10 + bob, blink, legs_t=t)
    # sombra
    sw = 40 - bob * 2
    d.ellipse((w // 2 - sw, h - 26, w // 2 + sw, h - 16), fill=(15, 11, 10))


def scene_surf(d, w, h, t, blink):
    # mar
    d.rectangle((0, h - 58, w, h), fill=SEA)
    for row in range(3):
        yy = h - 52 + row * 16
        for i in range(-1, w // 28 + 2):
            xx = i * 28 + int(10 * math.sin(t * 2 + row * 1.3 + i * 0.7))
            d.arc((xx, yy, xx + 26, yy + 12), 200, 340, fill=SEA_LIGHT, width=3)
    # sol
    d.ellipse((w - 46, 8, w - 14, 40), fill=(245, 200, 90))

    # surfe: sobe e desce na onda, inclinado
    bob = int(5 * math.sin(t * 2.6))
    tilt = math.sin(t * 2.6 + 0.6) * 0.35
    cx, cy = w // 2 + int(12 * math.sin(t * 0.8)), h - 66 + bob

    # prancha
    board = Image.new("RGBA", (110, 22), (0, 0, 0, 0))
    bd = ImageDraw.Draw(board)
    bd.ellipse((0, 4, 110, 20), fill=CREAM)
    bd.ellipse((8, 7, 102, 17), fill=(220, 170, 120))
    board = board.rotate(math.degrees(tilt), expand=True,
                         resample=Image.BICUBIC)
    d._image.paste(board, (cx - board.width // 2, cy + 18 - board.height // 2),
                   board)

    draw_clawd(d, cx, cy - 12, blink, legs_t=None, tilt=tilt)
    # perninhas fixas na prancha
    d.line((cx - 16, cy + 12, cx - 20 + int(tilt * 10), cy + 22), fill=ORANGE, width=6)
    d.line((cx + 16, cy + 12, cx + 20 + int(tilt * 10), cy + 22), fill=ORANGE, width=6)
    # spray
    if bob < -2:
        for k in range(4):
            sx = cx - 40 - k * 7
            sy = cy + 26 - k * 5
            d.ellipse((sx, sy, sx + 5, sy + 5), fill=CREAM)


def scene_soccer(d, w, h, t, blink):
    # gramado
    d.rectangle((0, h - 42, w, h), fill=GRASS)
    d.line((0, h - 42, w, h - 42), fill=(70, 130, 76), width=3)

    period = 1.6
    ph = (t % period) / period          # 0..1 ciclo do chute

    cx, cy = 70, h - 66
    # pulinho no chute
    hop = int(6 * math.sin(min(ph * 3, 1) * math.pi)) if ph < 0.35 else 0
    draw_clawd(d, cx, cy - hop, blink, legs_t=None)

    # perna de apoio + perna que chuta
    d.line((cx - 14, cy + 22, cx - 16, cy + 38), fill=ORANGE, width=6)
    kick = math.sin(min(ph / 0.3, 1) * math.pi) if ph < 0.3 else 0
    kx = cx + 14 + int(kick * 18)
    ky = cy + 22 + int(kick * -6)
    d.line((cx + 10, cy + 20, kx, ky + 14), fill=ORANGE, width=6)

    # bola: sai chutada, quica e volta
    if ph < 0.3:
        bx = cx + 52
        by = h - 55
    else:
        q = (ph - 0.3) / 0.7
        bx = cx + 52 + int(q * (w - cx - 105))
        by = h - 55 - int(46 * abs(math.sin(q * math.pi * 2)) * (1 - q))
    r = 13
    d.ellipse((bx - r, by - r, bx + r, by + r), fill=BALL_W)
    # gomos
    d.ellipse((bx - 5, by - 5, bx + 5, by + 5), fill=(30, 30, 30))
    for ang in range(0, 360, 72):
        a = math.radians(ang + ph * 360)
        px, py = bx + int(9 * math.cos(a)), by + int(9 * math.sin(a))
        d.ellipse((px - 3, py - 3, px + 3, py + 3), fill=(30, 30, 30))


SCENES = [scene_idle, scene_surf, scene_soccer]


def render_anim_region(t, blink):
    w = ANIM_BOX[2] - ANIM_BOX[0]
    h = ANIM_BOX[3] - ANIM_BOX[1]
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d._image = img  # p/ cenas colarem sprites rotacionados
    scene = SCENES[int(t // SCENE_SECONDS) % len(SCENES)]
    scene(d, w, h, t, blink)
    return img


# ---------- layout ----------

def load_fonts():
    try:
        return (ImageFont.truetype("arialbd.ttf", 22),
                ImageFont.truetype("arialbd.ttf", 26),
                ImageFont.truetype("arial.ttf", 15))
    except OSError:
        f = ImageFont.load_default()
        return f, f, f


F_TITLE, F_BIG, F_SMALL = load_fonts()


def draw_usage(d, usage):
    tin, tout, msgs = usage
    d.text((120, 190), "CLAUDE CODE", font=F_TITLE, fill=CREAM, anchor="mm")
    d.line((20, 208, 220, 208), fill=(60, 50, 45), width=2)
    d.text((120, 230), f"{fmt(tin + tout)} tokens hoje",
           font=F_BIG, fill=ORANGE, anchor="mm")
    d.text((120, 260), f"entrada {fmt(tin)}   saida {fmt(tout)}",
           font=F_SMALL, fill=GRAY, anchor="mm")
    d.text((120, 283), f"{msgs} respostas",
           font=F_SMALL, fill=GRAY, anchor="mm")
    d.text((120, 305), datetime.now().strftime("atualizado %H:%M"),
           font=F_SMALL, fill=(90, 84, 80), anchor="mm")


def render_full(t, blink, usage):
    img = Image.new("RGB", (240, 320), BG)
    img.paste(render_anim_region(t, blink), ANIM_BOX[:2])
    draw_usage(ImageDraw.Draw(img), usage)
    return img


# ---------- loop (standalone e suite) ----------

class WidgetLoop:
    """Roda a animacao chamando send_full/send_region fornecidos."""

    def __init__(self, send_full, send_region):
        self.send_full = send_full      # (PIL 240x320) -> None
        self.send_region = send_region  # (x, y, PIL) -> None

    def run(self, should_stop):
        usage = usage_today()
        t0 = time.perf_counter()
        self.send_full(render_full(0, False, usage))
        last_refresh = time.time()
        blink_until = 0
        next_blink = time.time() + 3

        while not should_stop():
            t = time.perf_counter() - t0
            now = time.time()
            if now >= next_blink:
                blink_until = now + 0.18
                next_blink = now + 2.5 + 2.5 * abs(math.sin(now))
            blink = now < blink_until

            self.send_region(ANIM_BOX[0], ANIM_BOX[1],
                             render_anim_region(t, blink))

            if now - last_refresh > 60:
                usage = usage_today()
                self.send_full(render_full(t, blink, usage))
                last_refresh = now
            time.sleep(0.02)


def main():
    lcd = AX206()

    def send_full(img):
        lcd.show_image(img)

    def send_region(x, y, img):
        lcd.blit(x, y, img.width, img.height, AX206.image_to_rgb565(img))

    print("Widget rodando (Ctrl+C para sair)")
    try:
        WidgetLoop(send_full, send_region).run(lambda: False)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

"""Layouts personalizados: elementos livres (imagem, gif, relogio, texto,
stats, mascote) posicionados pelo editor da suite e renderizados como
camadas com dirty-rect.

Formato (layouts_user.json):
{
  "layouts": {
    "home": {
      "bg": "#0e0d14" | "C:/caminho/fundo.png",
      "elements": [
        {"type": "image", "x": 10, "y": 10, "path": "...", "scale": 100},
        {"type": "gif",   "x": 60, "y": 40, "path": "...", "scale": 100},
        {"type": "clock", "x": 0,  "y": 164, "size": "L", "color": "#f7f3f7"},
        {"type": "text",  "x": 12, "y": 12, "text": "...", "size": "M",
         "color": "#9ca2b5"},
        {"type": "stats", "x": 12, "y": 216},
        {"type": "mascot", "x": 60, "y": 40}
      ]
    }
  },
  "assign": {"home": "home", "per_exe": {"code.exe": "coding"}}
}
"""

import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageSequence

from . import palette as P, widgets as W
from .screens import Screen, Layer

CLOCK_FONTS = {"S": P.F22, "M": P.F33, "L": P.F40}
TEXT_FONTS = {"S": P.F14, "M": P.F18, "L": P.F22}
STATS_SIZE = (216, 74)
MASCOT_SIZE = (120, 108)

_gif_cache = {}
_img_cache = {}


def _rgb(s, default=(14, 13, 20)):
    try:
        s = str(s).lstrip("#")
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return default


def _scaled_size(w, h, scale):
    s = max(5, min(400, scale or 100)) / 100
    return max(1, int(w * s)), max(1, int(h * s))


def load_image(path, scale=100, bg=(14, 13, 20)):
    key = (path, scale, bg)
    if key in _img_cache:
        return _img_cache[key]
    try:
        img = Image.open(path)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGBA")
            base = Image.new("RGB", img.size, bg)
            base.paste(img, (0, 0), img)
            img = base
        else:
            img = img.convert("RGB")
        img = img.resize(_scaled_size(img.width, img.height, scale),
                         Image.LANCZOS)
        if img.width > 240 or img.height > 320:
            img.thumbnail((240, 320), Image.LANCZOS)
    except OSError:
        img = Image.new("RGB", (48, 48), (60, 20, 20))
        ImageDraw.Draw(img).text((24, 24), "?", fill=(255, 255, 255),
                                 anchor="mm", font=P.F22)
    _img_cache[key] = img
    return img


def load_gif(path, scale=100, bg=(14, 13, 20)):
    """[(frame RGB, duracao_s), ...] pre-processados."""
    key = (path, scale, bg)
    if key in _gif_cache:
        return _gif_cache[key]
    frames = []
    try:
        gif = Image.open(path)
        size = _scaled_size(gif.width, gif.height, scale)
        for fr in ImageSequence.Iterator(gif):
            dur = max(0.03, fr.info.get("duration", 100) / 1000)
            f = fr.convert("RGBA")
            base = Image.new("RGB", f.size, bg)
            base.paste(f, (0, 0), f)
            frames.append((base.resize(size, Image.LANCZOS), dur))
    except OSError:
        pass
    if not frames:
        frames = [(load_image(path, scale, bg), 1.0)]
    _gif_cache[key] = frames
    return frames


def element_size(el, bg_rgb):
    t = el["type"]
    if t == "image":
        img = load_image(el["path"], el.get("scale", 100), bg_rgb)
        return img.width, img.height
    if t == "gif":
        return load_gif(el["path"], el.get("scale", 100), bg_rgb)[0][0].size
    if t == "clock":
        f = CLOCK_FONTS.get(el.get("size", "L"), P.F40)
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bb = d.textbbox((0, 0), "88:88", font=f)
        return bb[2] - bb[0] + 8, bb[3] - bb[1] + 10
    if t == "text":
        f = TEXT_FONTS.get(el.get("size", "M"), P.F18)
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        txt = el.get("text", "texto") or " "
        bb = d.textbbox((0, 0), txt, font=f)
        return bb[2] - bb[0] + 6, bb[3] - bb[1] + 8
    if t == "stats":
        return STATS_SIZE
    if t == "mascot":
        return MASCOT_SIZE
    return 40, 40


def element_bbox(el, bg_rgb):
    w, h = element_size(el, bg_rgb)
    x = max(0, min(240 - w, int(el.get("x", 0))))
    y = max(0, min(320 - h, int(el.get("y", 0))))
    return x, y, w, h


def _gif_frame(frames, t):
    total = sum(d for _, d in frames)
    tt = t % total if total > 0 else 0
    for img, d in frames:
        tt -= d
        if tt <= 0:
            return img
    return frames[-1][0]


def _make_bg(layout):
    bg_spec = layout.get("bg", "#0e0d14")
    if isinstance(bg_spec, str) and not bg_spec.startswith("#") \
            and os.path.exists(bg_spec):
        img = Image.open(bg_spec).convert("RGB")
        s = max(240 / img.width, 320 / img.height)
        img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1),
                         Image.LANCZOS)
        x = (img.width - 240) // 2
        y = (img.height - 320) // 2
        return img.crop((x, y, x + 240, y + 320)), _rgb("#101010")
    rgb = _rgb(bg_spec)
    return Image.new("RGB", (240, 320), rgb), rgb


def render_element(el, t, state, bg_rgb, bg_full, mascot_draw=None):
    """Retorna a imagem do elemento no tamanho do proprio bbox."""
    x, y, w, h = element_bbox(el, bg_rgb)
    typ = el["type"]
    if typ == "image":
        return load_image(el["path"], el.get("scale", 100), bg_rgb)
    if typ == "gif":
        return _gif_frame(load_gif(el["path"], el.get("scale", 100), bg_rgb), t)
    base = bg_full.crop((x, y, x + w, y + h)).copy()
    d = ImageDraw.Draw(base)
    if typ == "clock":
        f = CLOCK_FONTS.get(el.get("size", "L"), P.F40)
        d.text((w // 2, h // 2), datetime.now().strftime("%H:%M"), font=f,
               fill=_rgb(el.get("color", "#f7f3f7")), anchor="mm")
    elif typ == "text":
        f = TEXT_FONTS.get(el.get("size", "M"), P.F18)
        d.text((3, h // 2), el.get("text", ""), font=f,
               fill=_rgb(el.get("color", "#9ca2b5")), anchor="lm")
    elif typ == "stats":
        base.paste(W.hbar("CPU", state.get("cpu", 0), P.CORAL), (0, 2))
        base.paste(W.hbar("RAM", state.get("ram", 0), P.SCANNER_CYAN), (0, 27))
        base.paste(W.hbar("GPU", state.get("gpu", 0), P.NEON_GREEN), (0, 52))
    elif typ == "mascot" and mascot_draw:
        mascot_draw(base, t, state.get("blink", False))
    return base


def compose_frame(layout, t=0.0, state=None, mascot_draw=None):
    """Frame completo 240x320 (usado pelo editor como preview)."""
    state = state or {"cpu": 12, "ram": 43, "gpu": 5}
    bg_full, bg_rgb = _make_bg(layout)
    frame = bg_full.copy()
    for el in layout.get("elements", []):
        img = render_element(el, t, state, bg_rgb, bg_full, mascot_draw)
        x, y, _, _ = element_bbox(el, bg_rgb)
        frame.paste(img, (x, y))
    return frame


def build_user_screen(layout, mascot_draw=None):
    """Screen com dirty-rect: estaticos no bg, dinamicos como camadas."""
    bg_full, bg_rgb = _make_bg(layout)
    static_types = {"image", "text"}
    dynamic = []
    for el in layout.get("elements", []):
        if el["type"] in static_types:
            img = render_element(el, 0, {}, bg_rgb, bg_full)
            x, y, _, _ = element_bbox(el, bg_rgb)
            bg_full.paste(img, (x, y))
        else:
            dynamic.append(el)

    layers = [Layer((0, 0, 240, 320), lambda s, t, _b=bg_full: _b)]
    for el in dynamic:
        bbox = element_bbox(el, bg_rgb)

        def make_render(el=el):
            return lambda s, t: render_element(el, t, s, bg_rgb, bg_full,
                                               mascot_draw)

        typ = el["type"]
        if typ in ("gif", "mascot"):
            layers.append(Layer(bbox, make_render(), animated=True))
        elif typ == "clock":
            layers.append(Layer(bbox, make_render(),
                                key=lambda s: datetime.now().strftime("%H:%M")))
        elif typ == "stats":
            layers.append(Layer(bbox, make_render(),
                                key=lambda s: (round(s.get("cpu", 0)),
                                               round(s.get("ram", 0)),
                                               round(s.get("gpu", 0)))))
    return Screen(layers)

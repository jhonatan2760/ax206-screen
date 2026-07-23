"""Key art e backgrounds: Steam (cacheado) -> icone do exe -> fallback.
Tudo gerado uma vez e salvo em cache_dir; execucoes seguintes so carregam."""

import ctypes
import ctypes.wintypes
import json
import os
import re
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw

from . import palette as P

user32 = ctypes.windll.user32

_here = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE = os.path.join(os.path.dirname(_here), "assets_local")


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


# ---------- icone do exe (WinAPI) ----------

def icon_from_exe(exe_path, size=96, bg=(16, 20, 24)):
    try:
        N = 256
        hicon = (ctypes.c_void_p * 1)()
        iconid = (ctypes.c_uint * 1)()
        n = user32.PrivateExtractIconsW(exe_path, 0, N, N, hicon, iconid, 1, 0)
        if n < 1 or not hicon[0]:
            return None
        gdi32 = ctypes.windll.gdi32
        hdc_screen = user32.GetDC(0)
        hdc = gdi32.CreateCompatibleDC(hdc_screen)

        class BMIH(ctypes.Structure):
            _fields_ = [("sz", ctypes.c_uint32), ("w", ctypes.c_int32),
                        ("h", ctypes.c_int32), ("planes", ctypes.c_uint16),
                        ("bpp", ctypes.c_uint16), ("comp", ctypes.c_uint32),
                        ("simg", ctypes.c_uint32), ("xppm", ctypes.c_int32),
                        ("yppm", ctypes.c_int32), ("used", ctypes.c_uint32),
                        ("imp", ctypes.c_uint32)]

        bmi = BMIH(sz=ctypes.sizeof(BMIH), w=N, h=-N, planes=1, bpp=32)
        bits = ctypes.c_void_p()
        hbm = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0,
                                     ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(hdc, hbm)
        brush = gdi32.CreateSolidBrush(bg[0] | (bg[1] << 8) | (bg[2] << 16))
        rect = ctypes.wintypes.RECT(0, 0, N, N)
        user32.FillRect(hdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)
        user32.DrawIconEx(hdc, 0, 0, hicon[0], N, N, 0, None, 3)
        buf = ctypes.string_at(bits, N * N * 4)
        img = Image.frombuffer("RGB", (N, N), buf, "raw", "BGRX", 0, 1)
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(0, hdc_screen)
        user32.DestroyIcon(hicon[0])
        return img.resize((size, size), Image.LANCZOS)
    except OSError:
        return None


# ---------- Steam header (1 tentativa, cacheada mesmo se falhar) ----------

def steam_header(title, cache_dir=DEFAULT_CACHE, timeout=6):
    os.makedirs(cache_dir, exist_ok=True)
    slug = _slug(title)
    hit = os.path.join(cache_dir, f"steam_{slug}.jpg")
    miss = os.path.join(cache_dir, f"steam_{slug}.miss")
    if os.path.exists(hit):
        try:
            return Image.open(hit).convert("RGB")
        except OSError:
            pass
    if os.path.exists(miss):
        return None
    try:
        q = urllib.parse.quote(title)
        url = (f"https://store.steampowered.com/api/storesearch/"
               f"?term={q}&l=english&cc=US")
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.load(r)
        items = data.get("items") or []
        if not items:
            raise LookupError
        # tiny_image traz a URL com hash correta; tenta a versao maior antes
        img_url = items[0].get("tiny_image", "")
        if not img_url:
            raise LookupError
        raw = None
        for candidate in (img_url.replace("capsule_231x87", "capsule_616x353"),
                          img_url):
            try:
                with urllib.request.urlopen(candidate, timeout=timeout) as r:
                    raw = r.read()
                break
            except Exception:
                continue
        if raw is None:
            raise LookupError
        with open(hit, "wb") as f:
            f.write(raw)
        return Image.open(hit).convert("RGB")
    except Exception:
        open(miss, "w").close()  # nao tenta de novo
        return None


# ---------- painel de key art (220x76, spec do manifest) ----------

def _cover(img, w, h):
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1),
                     Image.LANCZOS)
    x = (img.width - w) // 2
    y = (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def art_panel(title, exe_path=None, cache_dir=DEFAULT_CACHE, w=220, h=76):
    """Painel completo: arte a direita + fade + tag GAME + titulo.
    Gerado 1x por jogo e cacheado como PNG."""
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, f"art_{_slug(title)}.png")
    if os.path.exists(cache):
        try:
            return Image.open(cache).convert("RGB")
        except OSError:
            pass

    img = Image.new("RGB", (w, h), (0x12, 0x16, 0x2A))
    art = steam_header(title, cache_dir)
    if art is None and exe_path:
        art = icon_from_exe(exe_path, size=160, bg=(0x12, 0x16, 0x2A))
    if art is not None:
        art_w = 130
        img.paste(_cover(art, art_w, h), (w - art_w, 0))
        # fade esquerda->direita por cima da arte
        fade = Image.new("L", (art_w, 1), 0)
        for x in range(art_w):
            fade.putpixel((x, 0), max(0, 200 - int(x * 200 / (art_w * 0.6))))
        fade = fade.resize((art_w, h))
        img.paste(Image.new("RGB", (art_w, h), (0x12, 0x16, 0x2A)),
                  (w - art_w, 0), fade)

    d = ImageDraw.Draw(img)
    # scrim inferior p/ titulo
    scrim = Image.new("L", (1, 30), 0)
    for y in range(30):
        scrim.putpixel((0, y), int(y * 170 / 30))
    d._image.paste(Image.new("RGB", (w, 30), (6, 8, 14)), (0, h - 30),
                   scrim.resize((w, 30)))

    # borda + tag GAME skewed
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=10,
                        outline=P.PANEL_LINE, width=2)
    from .widgets import _skew_rect
    _skew_rect(d, 12, 8, 68, 26, fill=P.NEON_GREEN)
    d.text((42, 17), "GAME", font=P.F12, fill=(10, 14, 8), anchor="mm")
    d.text((12, h - 8), title[:20], font=P.F16, fill=P.TEXT, anchor="lb")

    # so cacheia quando conseguiu arte; sem arte, tenta de novo na proxima
    if art is not None:
        img.save(cache)
    return img


# ---------- backgrounds (gerados 1x e cacheados) ----------

def bg_game(cache_dir=DEFAULT_CACHE):
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, "bg_game.png")
    if os.path.exists(cache):
        return Image.open(cache).convert("RGB")
    img = Image.new("RGB", (240, 320), P.BG_GRAPHITE)
    d = ImageDraw.Draw(img)
    grid = (0x14, 0x19, 0x1F)
    for x in range(0, 240, 16):
        d.line((x, 0, x, 320), fill=grid)
    for y in range(0, 320, 16):
        d.line((0, y, 240, y), fill=grid)
    img.save(cache)
    return img


def bg_ai(cache_dir=DEFAULT_CACHE):
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, "bg_ai.png")
    if os.path.exists(cache):
        return Image.open(cache).convert("RGB")
    img = Image.new("RGB", (240, 320), P.BG_AI)
    d = ImageDraw.Draw(img)
    for y in range(0, 320, 4):  # scanlines sutis
        d.line((0, y, 240, y), fill=(9, 13, 11))
    # header AI RTX GARAGE
    d.rounded_rectangle((36, 8, 204, 42), radius=8, outline=P.TERM_GREEN,
                        width=3)
    d.text((120, 25), "AI RTX GARAGE", font=P.F18, fill=P.TERM_GREEN,
           anchor="mm")
    img.save(cache)
    return img


def bg_idle(cache_dir=DEFAULT_CACHE):
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, "bg_idle.png")
    if os.path.exists(cache):
        return Image.open(cache).convert("RGB")
    img = Image.new("RGB", (240, 320), P.BG_IDLE)
    d = ImageDraw.Draw(img)
    d.text((120, 158), "· S T A N D B Y ·", font=P.F12, fill=P.TEXT_DIM,
           anchor="mm")
    img.save(cache)
    return img

"""Paleta e fontes do design system (cores ja quantizadas p/ RGB565)."""

import json
import os

from PIL import ImageFont

_here = os.path.dirname(os.path.abspath(__file__))
MANIFEST = json.load(open(os.path.join(_here, "manifest.json"), encoding="utf-8"))


def _hex(name):
    h = MANIFEST["palette"][name]["hex"].lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


BG_GRAPHITE = _hex("bg_graphite")
BG_AI = _hex("bg_ai_green")
BG_IDLE = _hex("bg_idle")
PANEL_LINE = _hex("panel_line")
NEON_GREEN = _hex("neon_green")
NEON_BRIGHT = _hex("neon_bright")
RT_PURPLE = _hex("rt_purple")
RT_PURPLE_LT = _hex("rt_purple_lt")
TERM_GREEN = _hex("term_green")
TERM_DIM = _hex("term_dim")
AMBER = _hex("amber")
AMBER_BRIGHT = _hex("amber_bright")
SCANNER_CYAN = _hex("scanner_cyan")
CRAB_ORANGE = _hex("crab_orange")
RED_ALERT = _hex("red_alert")
TEXT = _hex("text")
TEXT_DIM = _hex("text_dim")
CORAL = _hex("coral_claude")

GAUGE_TRACK = (0x22, 0x28, 0x3A)
TICK_RING = (0x31, 0x38, 0x50)
BADGE_OFF = (0x3A, 0x41, 0x50)
LABEL = (0x7F, 0x8A, 0xA0)


def _font(size, bold=True):
    for name in (("arialbd.ttf",) if bold else ("arial.ttf",)):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


F11 = _font(11)
F12 = _font(12)
F14 = _font(14)
F16 = _font(16)
F18 = _font(18)
F22 = _font(22)
F33 = _font(33)
F40 = _font(40)
F12R = _font(12, bold=False)
F14R = _font(14, bold=False)

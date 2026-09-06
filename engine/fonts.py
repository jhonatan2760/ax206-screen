"""Fontes cross-platform.

Arial no Windows; no Linux, Liberation Sans (metricamente compativel com a
Arial) ou DejaVu/Noto. O Pillow procura nomes simples nas pastas de fontes do
sistema nos dois, entao basta uma lista de candidatos.
"""

import functools

from PIL import ImageFont

BOLD = ("arialbd.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf",
        "NotoSans-Bold.ttf", "FreeSansBold.ttf")
REGULAR = ("arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf",
           "NotoSans-Regular.ttf", "FreeSans.ttf")


@functools.lru_cache(maxsize=None)
def font(size, bold=True):
    for name in (BOLD if bold else REGULAR):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)  # Pillow >= 10.1 aceita tamanho
    except TypeError:
        return ImageFont.load_default()

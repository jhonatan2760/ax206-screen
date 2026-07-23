"""Motor de renderizacao do design system Mini-LCD (240x320, RGB565).

Camadas com bbox fixo + dirty-rect: estaticas vao 1x, dinamicas so quando
o estado muda. Assets pesados (key art, backgrounds) sao gerados uma unica
vez e cacheados em assets_local/.
"""

from .screens import Screen, Layer, make_game_screen, make_ai_screen, make_idle_screen  # noqa
from . import widgets, keyart, palette  # noqa

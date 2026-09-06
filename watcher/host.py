"""Seleciona o backend de plataforma (janela em foco, dicas de jogo)."""

import sys

if sys.platform == "win32":
    from . import platform_win as impl
else:
    from . import platform_linux as impl

NAME = impl.NAME
foreground = impl.foreground
supports_foreground = impl.supports_foreground
game_hint = impl.game_hint

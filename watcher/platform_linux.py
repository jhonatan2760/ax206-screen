"""Linux: janela em foco via xprop/xwininfo (pacote x11-utils).

Em Wayland nao existe API generica de janela ativa, mas jogos Proton/Wine
rodam em XWayland e continuam visiveis pelo xprop. Quando nem isso responde,
detect.py cai no fallback por processos graficos na GPU (NVML). O GameMode
da Feral, se instalado, e um sinal extra de "jogo rodando".
"""

import os
import re
import shutil
import subprocess

import psutil

NAME = "linux"
_HAS_X = bool(os.environ.get("DISPLAY")) and shutil.which("xprop") is not None
_HAS_XWININFO = shutil.which("xwininfo") is not None
_HAS_GDBUS = shutil.which("gdbus") is not None


def _run(cmd, timeout=1.5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def supports_foreground():
    return _HAS_X


def _screen_size():
    out = _run(["xprop", "-root", "_NET_DESKTOP_GEOMETRY"])
    m = re.search(r"=\s*(\d+),\s*(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def foreground():
    """(pid, nome do processo em minusculas, tela cheia) ou (None, "", False)."""
    if not _HAS_X:
        return None, "", False
    out = _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    m = re.search(r"window id # (0x[0-9a-fA-F]+)", out)
    if not m or int(m.group(1), 16) == 0:
        return None, "", False
    wid = m.group(1)
    props = _run(["xprop", "-id", wid, "_NET_WM_PID", "_NET_WM_STATE"])
    pm = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", props)
    if not pm:
        return None, "", False
    pid = int(pm.group(1))
    fullscreen = "_NET_WM_STATE_FULLSCREEN" in props
    if not fullscreen and _HAS_XWININFO:
        geo = _run(["xwininfo", "-id", wid])
        w = re.search(r"Width:\s*(\d+)", geo)
        h = re.search(r"Height:\s*(\d+)", geo)
        sw, sh = _screen_size()
        if w and h and sw and sh:
            fullscreen = (int(w.group(1)) >= sw - 4
                          and int(h.group(1)) >= sh - 4)
    try:
        return pid, psutil.Process(pid).name().lower(), fullscreen
    except psutil.Error:
        return None, "", False


def game_hint():
    """True se o GameMode (Feral) tem algum cliente ativo."""
    if not _HAS_GDBUS:
        return False
    out = _run(["gdbus", "call", "--session",
                "--dest", "com.feralinteractive.GameMode",
                "--object-path", "/com/feralinteractive/GameMode",
                "--method", "org.freedesktop.DBus.Properties.Get",
                "com.feralinteractive.GameMode", "ClientCount"])
    m = re.search(r"<(\d+)>", out)
    return bool(m and int(m.group(1)) > 0)

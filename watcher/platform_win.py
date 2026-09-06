"""Windows: janela em foco via user32."""

import ctypes
import ctypes.wintypes

import psutil

NAME = "windows"
user32 = ctypes.windll.user32


def supports_foreground():
    return True


def foreground():
    """(pid, nome do exe em minusculas, tela cheia) ou (None, "", False)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, "", False
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    fullscreen = (rect.right - rect.left >= user32.GetSystemMetrics(0) - 4
                  and rect.bottom - rect.top >= user32.GetSystemMetrics(1) - 4)
    try:
        return pid.value, psutil.Process(pid.value).name().lower(), fullscreen
    except psutil.Error:
        return None, "", False


def game_hint():
    """Windows nao tem um GameMode equivalente."""
    return False

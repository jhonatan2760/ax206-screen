"""Deteccao de contexto: jogo em foco / IA na GPU / ocioso.

Ordem: layout atribuido pelo editor > jogo (janela em foco) > jogo (fallback
por processos graficos na GPU, para Wayland) > IA > idle.
"""

import os

import psutil

from . import host

# processos de desktop que aparecem como "graficos" no NVML e nunca sao jogo
DESKTOP_PROCS = {
    "dwm.exe", "explorer.exe", "shellhost.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "applicationframehost.exe",
    "gnome-shell", "kwin_wayland", "kwin_x11", "xwayland", "xorg", "x",
    "plasmashell", "mutter", "sway", "hyprland", "steam", "steamwebhelper",
    "wine64-preloader", "wineserver", "gamescope", "obs",
}

BADGE_FAMILY = {"RTX": "NVIDIA", "DLSS": "NVIDIA", "REFLEX": "NVIDIA",
                "G-SYNC": "NVIDIA", "CUDA": "NVIDIA",
                "RAY": "RT", "PATH": "RT",
                "FSR": "AMD", "V-CACHE": "AMD", "RYZEN": "AMD", "HDR": "AMD"}


def proc_name(pid):
    """Nome do processo em minusculas. No Linux o kernel trunca em 15 chars e
    processos Wine/Proton trazem caminho Windows no cmdline; corrige os dois."""
    try:
        p = psutil.Process(pid)
        name = p.name()
        if len(name) >= 15:
            try:
                cmd = p.cmdline()
                if cmd:
                    base = cmd[0].replace("\\", "/").rsplit("/", 1)[-1]
                    if base:
                        name = base
            except psutil.Error:
                pass
        return name.lower()
    except psutil.Error:
        return ""


def exe_path(pid):
    try:
        return psutil.Process(pid).exe()
    except psutil.Error:
        return None


def pretty_title(exe):
    base = os.path.splitext(exe)[0]
    for suffix in ("-win64-shipping", "-win32-shipping", "-shipping",
                   "_x64", "_x86", "-dx12", "-dx11"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return base.replace("_", " ").replace("-", " ").upper()


def to_badge_tuples(names, active_names=None):
    out = []
    for n in names:
        fam = next((f for k, f in BADGE_FAMILY.items() if k in n.upper()),
                   "NVIDIA")
        active = True if active_names is None else (n in active_names)
        out.append((n, fam, active))
    return out


def _game_info(cfg, name, pid, game_cfg):
    game_cfg = game_cfg or {}
    title = game_cfg.get("title", pretty_title(name))
    badges = game_cfg.get("badges", cfg.get("default_game_badges"))
    off = game_cfg.get("badges_off", [])
    return {"title": title, "exe": exe_path(pid) if pid else None,
            "name": name,
            "badges": to_badge_tuples(badges, set(badges) - set(off))}


def _gpu_fallback(cfg, gpu, util, hint):
    """Sem janela ativa (Wayland): escolhe o processo grafico mais pesado."""
    not_games = set(cfg.get("not_games")) | DESKTOP_PROCS
    games = cfg.get("games")
    cands = []
    for pid, mem in gpu.graphics_pids():
        n = proc_name(pid)
        if n and n not in not_games:
            cands.append((mem or 0, pid, n))
    cands.sort(reverse=True)
    known = [c for c in cands if c[2] in games]
    if known:
        mem, pid, n = known[0]
        return n, pid
    if cands and (hint or util >= cfg.get("game_min_gpu_util")):
        mem, pid, n = cands[0]
        return n, pid
    return None, None


def detect(cfg, layouts, gpu):
    """(modo, info): modo em {"user", "game", "ai", "idle"}."""
    pid, name, fullscreen = host.foreground()
    if pid is not None:
        name = proc_name(pid) or name
    util = gpu.util()
    hint = host.game_hint()

    if layouts and name:
        ln = layouts.layout_for_exe(name)
        if ln:
            return "user", {"layout": ln}

    not_games = set(cfg.get("not_games"))
    games = cfg.get("games")
    if name and name not in not_games:
        game_cfg = games.get(name)
        if game_cfg or ((fullscreen or hint)
                        and util >= cfg.get("game_min_gpu_util")):
            return "game", _game_info(cfg, name, pid, game_cfg)

    if pid is None:
        fname, fpid = _gpu_fallback(cfg, gpu, util, hint)
        if fname:
            if layouts and layouts.layout_for_exe(fname):
                return "user", {"layout": layouts.layout_for_exe(fname)}
            return "game", _game_info(cfg, fname, fpid, games.get(fname))

    if util >= cfg.get("ai_min_gpu_util"):
        running = set()
        for p in psutil.process_iter(["name"]):
            n = p.info["name"]
            if n:
                running.add(n.lower())
        hits = [p for p in cfg.get("ai_processes") if p in running]
        if hits:
            return "ai", {"task": hits[0].replace(".exe", "")}

    return "idle", None

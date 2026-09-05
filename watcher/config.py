"""Arquivos JSON de configuracao, recarregados quando o mtime muda.

context_config.json  regras de deteccao e lista de jogos (aba Jogos da suite)
layouts_user.json    layouts do editor e atribuicao home / por exe
"""

import json
import logging
import os

log = logging.getLogger("watcher")

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(APP_DIR, "context_config.json")
LAYOUTS_PATH = os.path.join(APP_DIR, "layouts_user.json")

DEFAULTS = {
    "poll_seconds": 3,
    "game_min_gpu_util": 30,
    "ai_min_gpu_util": 25,
    "default_game_badges": ["RTX ON", "DLSS", "RAY TRACING", "REFLEX"],
    "not_games": [],
    "games": {},
    "ai_processes": ["ollama.exe", "ollama_llama_server.exe", "ollama"],
}


class Reloadable:
    def __init__(self, path, default):
        self.path = path
        self.default = default
        self.mtime = None
        self.data = default
        self.reload()

    def reload(self):
        """True quando o conteudo mudou."""
        try:
            m = os.path.getmtime(self.path)
        except OSError:
            if self.data is not self.default:
                log.warning("%s sumiu; usando padrao", self.path)
                self.data, self.mtime = self.default, None
                return True
            return False
        if m == self.mtime:
            return False
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            # a suite pode estar no meio da escrita; tenta de novo no proximo poll
            log.warning("%s invalido (%s); mantendo o anterior", self.path, e)
            return False
        self.mtime = m
        self.data = data
        return True


class Config(Reloadable):
    def __init__(self):
        super().__init__(CFG_PATH, {})

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))


class Layouts(Reloadable):
    def __init__(self, mascot_draw):
        self.mascot_draw = mascot_draw
        self.screens = {}
        super().__init__(LAYOUTS_PATH,
                         {"layouts": {}, "assign": {"home": None, "per_exe": {}}})

    def reload(self):
        changed = super().reload()
        if changed:
            self.screens = {}
        return changed

    def screen_for(self, name):
        if name not in self.data.get("layouts", {}):
            return None
        if name not in self.screens:
            from engine.user_layout import build_user_screen
            self.screens[name] = build_user_screen(
                self.data["layouts"][name], self.mascot_draw)
        return self.screens[name]

    def layout_for_exe(self, exe):
        return self.data.get("assign", {}).get("per_exe", {}).get(exe)

    def home_layout(self):
        return self.data.get("assign", {}).get("home")

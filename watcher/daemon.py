"""Loop principal do daemon.

Sobrevive a: tela desconectada/reconectada, firmware fora de sincronia
(reset USB), excecao no render (loga e segue). Escreve watcher_status.json a
cada 2 s para a suite e para `python -m watcher --status`, e uma linha de
"vivo" no log a cada 5 min.
"""

import argparse
import json
import math
import os
import signal
import sys
import time
import traceback

import psutil
import usb.core

from ax206 import AX206, AX206Error, VID, PID
from engine import make_game_screen, make_ai_screen, make_idle_screen

from . import __version__, config as C, detect, host, log as L
from .gpu import Gpu

APP_DIR = C.APP_DIR
STATUS_PATH = os.path.join(APP_DIR, "watcher_status.json")
PID_PATH = os.path.join(APP_DIR, "watcher.pid")
HEARTBEAT_S = 300
STATUS_EVERY_S = 2


def draw_mascot_in_slot(img, t, blink):
    from PIL import ImageDraw
    import widget_claude as wc
    d = ImageDraw.Draw(img)
    wc.draw_clawd(d, img.width // 2, img.height // 2 - 6, blink,
                  legs_t=t, px=5)


def read_status():
    """Conteudo de watcher_status.json ou None."""
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def other_instance():
    """pid de outro watcher vivo (pelo pidfile), ou None."""
    try:
        with open(PID_PATH) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    if pid == os.getpid():
        return None
    try:
        cmd = " ".join(psutil.Process(pid).cmdline()).lower()
        if "watcher" in cmd or "context_watch" in cmd:
            return pid
    except psutil.Error:
        pass
    return None


class Watcher:
    def __init__(self, log):
        self.log = log
        self.stop = False
        self.cfg = C.Config()
        self.layouts = C.Layouts(draw_mascot_in_slot)
        self.gpu = Gpu()
        self.screens = {"game": make_game_screen(), "ai": make_ai_screen(),
                        "idle": make_idle_screen(draw_mascot_in_slot)}
        self.mode, self.info = None, None
        self.mode_since = time.time()
        self.boot = time.time()
        self.t0 = time.perf_counter()
        self.last_poll = 0.0
        self.util_smooth = 0.0
        self.console_lines = []
        self.blink_until = 0.0
        self.next_blink = time.time() + 3
        self.cpu_smooth = self.ram_val = 0.0
        self.last_sys = 0.0
        self.frames = 0
        self.last_status = 0.0
        self.last_heartbeat = time.time()
        psutil.cpu_percent()  # primeira chamada zera a janela

    def request_stop(self, *_):
        self.stop = True

    # ---------- USB ----------

    def open_lcd(self):
        """Espera a tela aparecer, reseta o USB (firmware pode estar fora de
        sincronia) e abre. Retorna None se pediram para parar."""
        waiting = False
        while not self.stop:
            dev = usb.core.find(idVendor=VID, idProduct=PID)
            if dev is not None:
                try:
                    dev.reset()
                except usb.core.USBError as e:
                    self.log.debug("reset USB: %s", e)
                time.sleep(2)  # re-enumeracao
                try:
                    lcd = AX206()
                    self.log.info("tela aberta%s",
                                  " (reconectada)" if waiting else "")
                    return lcd
                except (AX206Error, usb.core.USBError) as e:
                    self.log.warning("abrir a tela falhou: %s", e)
            if not waiting:
                self.log.warning("tela nao encontrada (VID %04x PID %04x); "
                                 "aguardando", VID, PID)
                waiting = True
            time.sleep(2)
        return None

    @staticmethod
    def _close(lcd):
        if lcd is not None:
            try:
                lcd.close()
            except Exception:
                pass

    # ---------- deteccao ----------

    @staticmethod
    def _describe(mode, info):
        info = info or {}
        if mode == "game":
            return info.get("title", "")
        if mode == "user":
            return info.get("layout", "")
        if mode == "ai":
            return info.get("task", "")
        return ""

    def poll(self):
        self.cfg.reload()
        if self.layouts.reload():
            self.mode = None  # forca recomposicao com layouts novos
        new_mode, new_info = detect.detect(self.cfg, self.layouts, self.gpu)
        if new_mode == "idle" and self.layouts.home_layout():
            new_mode, new_info = "user", {"layout": self.layouts.home_layout()}
        changed = (new_mode != self.mode
                   or (new_mode == "game" and (new_info or {}).get("title")
                       != (self.info or {}).get("title"))
                   or (new_mode == "user" and (new_info or {}).get("layout")
                       != (self.info or {}).get("layout")))
        if changed:
            self.log.info("modo %s -> %s %s", self.mode, new_mode,
                          self._describe(new_mode, new_info))
            self.mode, self.info = new_mode, new_info
            self.mode_since = time.time()
            if new_mode == "user":
                scr = self.layouts.screen_for(new_info["layout"])
                if scr:
                    scr.reset()
            else:
                self.screens[new_mode].reset()

    # ---------- frame ----------

    def _sys_stats(self, now):
        if now - self.last_sys >= 1.0:  # janela de 1 s + media movel
            self.cpu_smooth += (psutil.cpu_percent() - self.cpu_smooth) * 0.4
            self.ram_val = psutil.virtual_memory().percent
            self.last_sys = now

    def _blink(self, now):
        if now >= self.next_blink:
            self.blink_until = now + 0.18
            self.next_blink = now + 2.5 + 2.5 * abs(math.sin(now))
        return now < self.blink_until

    def tick(self, lcd):
        now = time.time()
        t = time.perf_counter() - self.t0
        if now - self.last_poll >= self.cfg.get("poll_seconds"):
            self.last_poll = now
            self.poll()

        util = self.gpu.util()
        used, total = self.gpu.vram_gb()
        temp = self.gpu.temp()
        mode = self.mode

        if mode == "user":
            scr = self.layouts.screen_for(self.info["layout"])
            if scr is None:
                self.mode = "idle"
                return
            self._sys_stats(now)
            state = {"cpu": self.cpu_smooth, "ram": self.ram_val, "gpu": util,
                     "blink": self._blink(now)}
            scr.push(lcd, state, t)
            delay = 0.05
        elif mode == "game":
            state = dict(self.info)
            state.update(gpu=util, temp=temp, vram=used,
                         status_left="REFLEX ON",
                         status_right=f"{util:.0f}% GPU")
            self.screens["game"].push(lcd, state, t)
            delay = 0.2
        elif mode == "ai":
            self.util_smooth += (util - self.util_smooth) * 0.3
            line = f"gpu {util:3.0f}%  vram {used:4.1f}G  {temp}C"
            if not self.console_lines or self.console_lines[-1] != line:
                self.console_lines.append(line)
                self.console_lines = self.console_lines[-4:]
            state = dict(self.info)
            state.update(gpu=self.util_smooth, temp=temp, vram=used,
                         vram_total=total, console=self.console_lines)
            self.screens["ai"].push(lcd, state, t)
            delay = 0.12
        else:
            self._sys_stats(now)
            up = int(now - self.boot)
            state = {"cpu": self.cpu_smooth, "ram": self.ram_val, "gpu": util,
                     "blink": self._blink(now),
                     "uptime": f"up {up // 3600}h{(up % 3600) // 60:02d}"}
            self.screens["idle"].push(lcd, state, t)
            delay = 0.05

        self.frames += 1
        if now - self.last_status >= STATUS_EVERY_S:
            self.last_status = now
            self.write_status(util, temp)
        if now - self.last_heartbeat >= HEARTBEAT_S:
            self.last_heartbeat = now
            self.log.info("vivo: modo=%s %s frames=%d gpu=%d%% %dC",
                          self.mode, self._describe(self.mode, self.info),
                          self.frames, util, temp)
        time.sleep(delay)

    def write_status(self, util=0, temp=0, mode=None):
        data = {"pid": os.getpid(), "version": __version__, "host": host.NAME,
                "gpu_name": self.gpu.name,
                "mode": mode or self.mode or "idle",
                "detail": self._describe(self.mode, self.info),
                "since": self.mode_since, "updated": time.time(),
                "frames": self.frames, "gpu_util": util, "gpu_temp": temp}
        tmp = STATUS_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, STATUS_PATH)
        except OSError as e:
            self.log.debug("status: %s", e)

    # ---------- supervisao ----------

    def run(self):
        lcd = None
        while not self.stop:
            try:
                if lcd is None:
                    lcd = self.open_lcd()
                    if lcd is None:
                        break
                    self.mode = None    # frame cheio ao (re)abrir
                    self.last_poll = 0  # detecta ja no primeiro tick
                self.tick(lcd)
            except (AX206Error, usb.core.USBError) as e:
                self.log.warning("USB: %s; reconectando", e)
                self._close(lcd)
                lcd = None
                time.sleep(2)
            except Exception:
                self.log.error("erro no loop (segue):\n%s",
                               traceback.format_exc())
                time.sleep(3)
        self._close(lcd)


def _cmd_status():
    st = read_status()
    if not st:
        print("sem watcher_status.json: o daemon nunca rodou nesta pasta")
        return 1
    alive = psutil.pid_exists(st.get("pid", -1))
    age = time.time() - st.get("updated", 0)
    print(f"pid {st.get('pid')}  {'vivo' if alive else 'MORTO'}  "
          f"host {st.get('host')}  v{st.get('version')}")
    print(f"modo {st.get('mode')} {st.get('detail') or ''}  "
          f"(ha {int(time.time() - st.get('since', 0))}s)")
    print(f"gpu {st.get('gpu_name')}  {st.get('gpu_util')}%  "
          f"{st.get('gpu_temp')}C  frames {st.get('frames')}")
    print(f"ultimo status ha {age:.0f}s"
          + ("  ATRASADO" if alive and age > 15 else ""))
    return 0 if alive else 2


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m watcher",
                                 description="daemon contextual da telinha AX206")
    ap.add_argument("--status", action="store_true",
                    help="mostra o estado do daemon em execucao")
    ap.add_argument("--once", action="store_true",
                    help="detecta o contexto uma vez e imprime")
    ap.add_argument("--log-level", default="INFO")
    a = ap.parse_args(argv)

    if a.status:
        return _cmd_status()

    log = L.setup(APP_DIR, a.log_level)

    if a.once:
        cfg = C.Config()
        layouts = C.Layouts(draw_mascot_in_slot)
        mode, info = detect.detect(cfg, layouts, Gpu())
        print(mode, info)
        return 0

    other = other_instance()
    if other:
        log.error("ja existe um watcher rodando (pid %d); saindo", other)
        return 3
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))

    log.info("watcher %s iniciando: host=%s python=%s pid=%d",
             __version__, host.NAME, sys.version.split()[0], os.getpid())
    w = Watcher(log)
    log.info("gpu: %s (nvml %s); janela em foco: %s", w.gpu.name,
             "ok" if w.gpu.ok else "indisponivel",
             "sim" if host.supports_foreground() else "nao (fallback GPU)")
    for sig in (getattr(signal, "SIGTERM", None), signal.SIGINT):
        if sig is not None:
            try:
                signal.signal(sig, w.request_stop)
            except (ValueError, OSError):
                pass
    try:
        w.run()
    except KeyboardInterrupt:
        pass
    finally:
        w.write_status(mode="stopped")
        try:
            os.remove(PID_PATH)
        except OSError:
            pass
        log.info("watcher encerrado")
    return 0

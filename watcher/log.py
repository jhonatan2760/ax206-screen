"""Log rotativo em watcher.log (1 MB x 3) e, quando ha terminal, no stderr."""

import logging
import logging.handlers
import os
import sys


def setup(app_dir, level="INFO"):
    log = logging.getLogger("watcher")
    if log.handlers:
        return log
    log.setLevel(level.upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(app_dir, "watcher.log"), maxBytes=1_000_000,
        backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    # pythonw nao tem stderr; systemd captura stderr no journal
    if sys.stderr is not None and (sys.stderr.isatty()
                                   or os.environ.get("INVOCATION_ID")):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    return log

"""Daemon contextual da telinha AX206 (Windows e Linux).

    python -m watcher            # roda o daemon
    python -m watcher --status   # mostra o estado do daemon em execucao
    python -m watcher --once     # detecta o contexto uma vez e imprime

Um unico processo e dono do USB. A suite (suite.py) so edita os JSONs de
configuracao, que o daemon recarrega sozinho.
"""

__version__ = "2.0.0"

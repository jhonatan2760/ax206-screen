"""GPU via NVML (NVIDIA, Windows e Linux).

Sem NVML (driver sem libnvidia-ml, GPU de outra marca) os valores ficam em
zero e o daemon segue funcionando so com a lista de jogos por nome.
"""

import logging

log = logging.getLogger("watcher")


class Gpu:
    def __init__(self):
        self.ok = False
        self.name = "GPU"
        self.h = None
        self.nv = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self.nv = pynvml
            self.h = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(self.h)
            self.name = name.decode() if isinstance(name, bytes) else name
            self.ok = True
        except Exception as e:  # ImportError, NVMLError...
            log.warning("NVML indisponivel (%s): uso/temperatura da GPU "
                        "ficam em 0", e)

    def util(self):
        if not self.ok:
            return 0
        try:
            return self.nv.nvmlDeviceGetUtilizationRates(self.h).gpu
        except Exception:
            return 0

    def vram_gb(self):
        if not self.ok:
            return 0.0, 0.0
        try:
            m = self.nv.nvmlDeviceGetMemoryInfo(self.h)
            return m.used / 2**30, m.total / 2**30
        except Exception:
            return 0.0, 0.0

    def temp(self):
        if not self.ok:
            return 0
        try:
            return self.nv.nvmlDeviceGetTemperature(
                self.h, self.nv.NVML_TEMPERATURE_GPU)
        except Exception:
            return 0

    def graphics_pids(self):
        """[(pid, bytes_de_vram_ou_None)] dos processos graficos na GPU.
        No Windows (WDDM) a memoria vem None; no Linux vem o valor real."""
        if not self.ok:
            return []
        for fn in ("nvmlDeviceGetGraphicsRunningProcesses_v3",
                   "nvmlDeviceGetGraphicsRunningProcesses"):
            f = getattr(self.nv, fn, None)
            if f is None:
                continue
            try:
                return [(p.pid, p.usedGpuMemory) for p in f(self.h)]
            except Exception:
                return []
        return []

# meshtui/core/ports.py
import threading
import time
from typing import List, Callable

try:
    import serial.tools.list_ports as list_ports
except Exception:
    list_ports = None

class PortScanner:
    def __init__(self, on_update: Callable[[List[str]], None], interval: float = 3.0):
        self.on_update = on_update
        self.interval = interval
        self._stop = threading.Event()
        self._thr = None
        self._last = []

    def _scan_once(self) -> List[str]:
        if list_ports is None:
            return []
        ports = [p.device for p in list_ports.comports()]
        ports.sort(key=str.lower)
        return ports

    def _run(self):
        while not self._stop.is_set():
            try:
                ports = self._scan_once()
                if ports != self._last:
                    self._last = ports
                    self.on_update(ports)
            except Exception:
                pass
            time.sleep(self.interval)

    def start(self):
        if self._thr and self._thr.is_alive():
            return
        self._stop.clear()
        self._thr = threading.Thread(target=self._run, daemon=True)
        self._thr.start()

    def stop(self):
        self._stop.set()
        if self._thr:
            self._thr.join(timeout=1.0)

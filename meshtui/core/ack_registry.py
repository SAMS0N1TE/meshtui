# meshtui/core/ack_registry.py
import threading
import time
from typing import Dict, Optional, Tuple

class AckRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status: Dict[int, Dict] = {}
        self._waiters: Dict[int, threading.Event] = {}

    def register(self, tx_id: int) -> None:
        with self._lock:
            self._status[tx_id] = {"state": "PENDING", "from": None, "ts": time.time()}
            self._waiters.setdefault(tx_id, threading.Event())

    def set_result(self, tx_id: int, state: str, from_node: Optional[int]) -> None:
        with self._lock:
            if tx_id not in self._status:
                self._status[tx_id] = {"state": state, "from": from_node, "ts": time.time()}
            else:
                self._status[tx_id].update({"state": state, "from": from_node, "ts": time.time()})
            ev = self._waiters.get(tx_id)
            if ev:
                ev.set()

    def get(self, tx_id: int) -> Optional[Dict]:
        with self._lock:
            return dict(self._status.get(tx_id) or {}) or None

    def wait_for(self, tx_id: int, timeout: float) -> Optional[Dict]:
        with self._lock:
            ev = self._waiters.setdefault(tx_id, threading.Event())
            # If already decided, return immediately
            st = self._status.get(tx_id)
            if st and st.get("state") in ("ACK", "NAK"):
                return dict(st)
        if not ev.wait(timeout):
            return None
        with self._lock:
            st = self._status.get(tx_id)
            return dict(st) if st else None

# Singleton used by transport and meshtastic_io
ack_registry = AckRegistry()
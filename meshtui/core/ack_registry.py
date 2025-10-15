# meshtui/core/ack_registry.py
import threading
import time
from typing import Any, Dict, Optional


class AckRegistry:
    """In-memory tracker for delivery acknowledgements."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status: Dict[int, Dict[str, Any]] = {}
        self._waiters: Dict[int, threading.Event] = {}

    def _ensure_waiter(self, tx_id: int) -> threading.Event:
        event = self._waiters.get(tx_id)
        if event is None:
            event = threading.Event()
            self._waiters[tx_id] = event
        return event

    def register(self, tx_id: int) -> None:
        with self._lock:
            self._status[tx_id] = {"state": "PENDING", "from": None, "ts": time.time()}
            self._ensure_waiter(tx_id)

    def set_result(self, tx_id: int, state: str, from_node: Optional[int]) -> None:
        with self._lock:
            self._status[tx_id] = {
                "state": state,
                "from": from_node,
                "ts": time.time(),
            }
            self._ensure_waiter(tx_id).set()

    def get(self, tx_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._status.get(tx_id)
            return dict(entry) if entry else None

    def wait_for(self, tx_id: int, timeout: float) -> Optional[Dict[str, Any]]:
        with self._lock:
            waiter = self._ensure_waiter(tx_id)
            status = self._status.get(tx_id)
            if status and status.get("state") in {"ACK", "NAK"}:
                return dict(status)

        if not waiter.wait(timeout):
            return None

        with self._lock:
            status = self._status.get(tx_id)
            return dict(status) if status else None


# Singleton used by transport and meshtastic_io
ack_registry = AckRegistry()

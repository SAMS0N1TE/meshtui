# meshtui/core/state.py
import time
from collections import deque, defaultdict
from typing import Dict, Optional, List, Tuple, Set


class AppState:
    def __init__(self):
        self.nodes: Dict[int, Dict] = {}
        self.dm_target: Optional[int] = None
        self.log = deque(maxlen=2000)
        self.channels: List[Tuple[int, str]] = []
        self.active_channels: Set[int] = set()
        self.chats = defaultdict(lambda: deque(maxlen=1000))  # num -> deque[str]
        self.last_rx_time: float = 0.0

    def add_log(self, text: str):
        t = time.strftime("%H:%M:%S")
        self.log.append(f"[{t}] {text}")

    def add_chat(self, peer: Optional[int], text: str, me: bool = False, sender_id: Optional[int] = None):
        key = peer if peer is not None else -1  # -1 for broadcast room

        if me:
            prefix = "You: "
        else:
            sender_name = self.nodes.get(sender_id, {}).get("short",
                                                            f"#{sender_id}") if sender_id is not None else "Unknown"
            prefix = f"{sender_name}: "

        self.chats[key].append(prefix + text)

    def set_dm(self, num: Optional[int]):
        self.dm_target = num
        for n in self.nodes.values():
            n["dm"] = (n["num"] == num) if num is not None else False

    def upsert_node(self, num: int, short: str, ts: float):
        n = self.nodes.get(num)
        if n is None:
            n = {"num": num, "short": short, "last": ts, "dm": False, "pos": None, "meta": {}}
            self.nodes[num] = n
        else:
            n["short"] = short or n["short"]
            n["last"] = max(ts, n.get("last", 0))
        n["dm"] = (self.dm_target == num)

    def set_position(self, num: int, lat: float, lon: float, alt: float | None = None, ts: float | None = None):
        n = self.nodes.get(num)
        if not n:
            n = {"num": num, "short": f"{num:x}", "last": ts or time.time(), "dm": False, "pos": None, "meta": {}}
            self.nodes[num] = n
        n["pos"] = {"lat": lat, "lon": lon, "alt": alt, "ts": ts or time.time()}
        n["last"] = max(n.get("last", 0), ts or time.time())

    def set_msg_meta(self, src: int | None, dst: int | None, encrypted: bool, channel: int | None,
                     hop_limit: int | None, rx_time: float | None, msg_id: str | None):
        if src is None:
            return
        n = self.nodes.get(src)
        if not n:
            n = {"num": src, "short": f"{src:x}", "last": rx_time or time.time(), "dm": False, "pos": None, "meta": {}}
            self.nodes[src] = n
        n["meta"] = {
            "encrypted": bool(encrypted),
            "channel": channel,
            "hop": hop_limit,
            "rx": rx_time or time.time(),
            "last_msg_id": msg_id,
        }
        n["last"] = max(n.get("last", 0), rx_time or time.time())

    def set_channels(self, items: List[Tuple[int, str]]):
        self.channels = list(sorted(items, key=lambda x: x[0]))

    def set_active_channels(self, enabled: List[int]):
        self.active_channels = set(enabled)

    def ordered_nodes(self):
        return sorted(self.nodes.values(), key=lambda n: (-n.get("last", 0), n.get("short", "")))
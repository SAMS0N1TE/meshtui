# meshtui/core/state.py
import asyncio
import time
from collections import deque, defaultdict
from typing import Dict, Optional, List, Tuple, Set
from meshtui.ui_ptk.text_sanitize import sanitize_text
from meshtui.model import ChatMsg, MsgStatus, next_msg_id

def _to_int(x):
    try:
        return int(str(x), 10)
    except (ValueError, TypeError):
        return None

class AppState:
    def __init__(self):
        self.nodes: Dict[int, Dict] = {}
        self.dm_target: Optional[int] = None
        self.log = deque(maxlen=2000)
        self.channels: List[Tuple[int, str]] = []
        self.active_channels: Set[int] = set()
        self.chats: dict[int, list[ChatMsg]] = defaultdict(list)
        self.msg_index: dict[int, ChatMsg] = {}
        self.msg_by_delivery: dict[int, ChatMsg] = {}
        self.last_rx_time: float = 0.0

        welcome_text = f"Welcome to Meshtui! - {time.strftime('%Y-%m-%d %H:%M:%S')}"
        self.add_chat(peer=None, text=welcome_text, is_system_message=True)

    def add_log(self, text: str):
        t = time.strftime("%H:%M:%S")
        self.log.append(f"[{t}] {sanitize_text(text)}")

    def add_chat(self, peer: int | None, text: str, me: bool = False,
                 sender_id: int | None = None, is_system_message: bool = False):
        key = peer if peer is not None else -1
        if is_system_message:
            prefix = ""
        elif me:
            prefix = "You: "
        else:
            sender_name = self.nodes.get(sender_id, {}).get("short", f"#{sender_id:x}") if sender_id is not None else "Unknown"
            if len(sender_name) > 15:
                sender_name = sender_name[:12] + "..."
            prefix = f"{sender_name}: "
        txt = prefix + sanitize_text(text)
        status = MsgStatus.ACKED if is_system_message else MsgStatus.SENT
        m = ChatMsg(id=next_msg_id(), to=key, text=txt, status=status)
        self.chats[key].append(m)

    def add_outgoing(self, to: int, text: str) -> ChatMsg:
        m = ChatMsg(id=next_msg_id(), to=to, text=f"You: {text}", status=MsgStatus.PENDING)
        self.chats[to if to != 0xFFFFFFFF else -1].append(m)
        self.msg_index[m.id] = m
        return m

    def bind_delivery_ids(self, msg: ChatMsg, *ids: int):
        for d in ids:
            di = _to_int(d)
            if di is not None:
                self.msg_by_delivery[di] = msg
        msg.status = MsgStatus.SENT

    def bind_delivery_id(self, msg: ChatMsg, delivery_id: int | None):
        # keep compatibility
        msg.delivery_id = delivery_id
        self.bind_delivery_ids(msg, delivery_id)

    def mark_acked(self, delivery_id: int):
        di = _to_int(delivery_id)
        if di is not None and di in self.msg_by_delivery:
            self.msg_by_delivery[di].status = MsgStatus.ACKED

    def ack_last_pending_from(self, peer:int, window_sec:float=20.0):
        lst = self.chats.get(peer, [])
        for m in reversed(lst):
            if m.status in (MsgStatus.PENDING, MsgStatus.SENT, MsgStatus.RETRYING):
                m.status = MsgStatus.ACKED
                return

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
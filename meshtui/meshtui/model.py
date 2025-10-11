# meshtui/model.py
from enum import Enum
from dataclasses import dataclass, field
import time, itertools

class MsgStatus(Enum):
    PENDING = 0
    SENT = 1
    ACKED = 2
    FAILED = 3
    RETRYING = 4

STATUS_SYMBOL = {
    MsgStatus.PENDING: "-",
    MsgStatus.SENT: "·",
    MsgStatus.ACKED: "✓",
    MsgStatus.FAILED: "✗",
    MsgStatus.RETRYING: "↻",
}

_id_counter = itertools.count(1)

@dataclass
class ChatMsg:
    id: int
    to: int         # node id or -1 for broadcast
    text: str
    ts: float = field(default_factory=time.time)
    status: MsgStatus = MsgStatus.PENDING
    retries: int = 0
    delivery_id: int | None = None  # radio-level id if available

def next_msg_id() -> int:
    return next(_id_counter)

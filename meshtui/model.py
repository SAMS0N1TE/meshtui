# meshtui/model.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
import time
import itertools

class MsgStatus(Enum):
    PENDING  = "PENDING"   # UI uses this
    RETRYING = "RETRYING"  # UI uses this
    QUEUED   = "QUEUED"
    SENT     = "SENT"
    ACKED    = "ACKED"
    FAILED   = "FAILED"

STATUS_SYMBOL: Dict[MsgStatus, str] = {
    MsgStatus.PENDING:  "…",
    MsgStatus.RETRYING: "↻",
    MsgStatus.QUEUED:   "…",
    MsgStatus.SENT:     "→",
    MsgStatus.ACKED:    "✓",
    MsgStatus.FAILED:   "✗",
}

_MSG_ID = itertools.count(1)
def next_msg_id() -> int: return next(_MSG_ID)

@dataclass
class ChatMsg:
    to: Any
    text: str
    status: MsgStatus = MsgStatus.PENDING
    id: int = field(default_factory=next_msg_id)
    ts: float = field(default_factory=time.time)
    delivery_id: Optional[int] = None
    meta: Dict[str, Any] = field(default_factory=dict)

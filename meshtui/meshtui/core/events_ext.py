# meshtui/core/events_ext.py
from dataclasses import dataclass
from typing import List, Optional, Tuple

@dataclass(frozen=True)
class Position:
    num: int
    lat: float
    lon: float
    alt: Optional[float] = None
    ts: Optional[float] = None

@dataclass(frozen=True)
class MsgMeta:
    msg_id: Optional[str]
    src: Optional[int]
    dst: Optional[int]
    channel: Optional[int]
    encrypted: bool
    hop_limit: Optional[int] = None
    rx_time: Optional[float] = None

@dataclass(frozen=True)
class Channels:
    items: List[Tuple[int, str]]

@dataclass(frozen=True)
class Connection:
    up: bool
    detail: str = ""

@dataclass(frozen=True)
class OwnerInfo:
    long: str
    short: str

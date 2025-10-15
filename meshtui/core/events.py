# meshtui/core/events.py
from dataclasses import dataclass
from typing import List, Union, Optional

@dataclass(frozen=True)
class RxText:
    src: int
    text: str
    dst: Optional[int] = None

@dataclass(frozen=True)
class Ack:
    msg_id: int

@dataclass(frozen=True)
class Beacon:
    num: int
    short: str
    ts: float

@dataclass(frozen=True)
class Log:
    text: str

@dataclass(frozen=True)
class Ports:
    items: List[str]

Event = Union[RxText, Ack, Beacon, Log, Ports]
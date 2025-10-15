# meshtui/core/reducer.py
import time
from meshtui.core import events
from meshtui.core.events_ext import Position, MsgMeta, Channels, Connection, OwnerInfo
from meshtui.core.meshtastic_io import BROADCAST

def apply_event(state, ev):
    if isinstance(ev, events.Beacon):
        state.upsert_node(ev.num, ev.short, ev.ts)
    elif isinstance(ev, events.RxText):
        state.last_rx_time = time.time()
        if ev.dst == BROADCAST:
            state.add_chat(None, ev.text, me=False, sender_id=ev.src)
        else:
            state.add_chat(ev.src, ev.text, me=False, sender_id=ev.src)
    elif isinstance(ev, events.Ack):
        state.add_log(f"ACK {ev.msg_id}")
    elif isinstance(ev, events.Log):
        state.add_log(ev.text)
    elif isinstance(ev, events.Ports):
        state.add_log("Ports: " + (", ".join(ev.items) if ev.items else "none"))
    elif isinstance(ev, Position):
        state.set_position(ev.num, ev.lat, ev.lon, ev.alt, ev.ts)
    elif isinstance(ev, MsgMeta):
        state.set_msg_meta(ev.src, ev.dst, ev.encrypted, ev.channel, ev.hop_limit, ev.rx_time, ev.msg_id)
    elif isinstance(ev, Channels):
        state.set_channels(ev.items)
        state.add_log("Channels: " + (", ".join(f"{i}:{n}" for i, n in ev.items) if ev.items else "none"))
    elif isinstance(ev, Connection):
        state.add_log("Connected" if ev.up else "Disconnected")
    elif isinstance(ev, OwnerInfo):
        state.add_log(f"Owner: {ev.long} / {ev.short}")

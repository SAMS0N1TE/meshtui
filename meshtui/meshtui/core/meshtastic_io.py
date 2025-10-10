# meshtui/core/meshtastic_io.py
import threading
import time

try:
    import meshtastic
    import meshtastic.serial_interface
    from pubsub import pub
except Exception:
    meshtastic = None
    pub = None

from meshtui.core import events
from meshtui.core.events_ext import Position, MsgMeta, Channels, Connection, OwnerInfo

BROADCAST = 0xFFFFFFFF


class MeshtasticIO:
    def __init__(self, bus, loop):
        self.bus = bus
        self.loop = loop
        self.iface = None
        self._thr = None
        self._stop = threading.Event()
        self._next_port = None
        self._subscribed = False

    def _emit(self, ev):
        self.loop.call_soon_threadsafe(lambda: self.loop.create_task(self.bus.emit(ev)))

    # ---------- PubSub callbacks ----------
    def _on_receive(self, packet=None, interface=None, **kwargs):
        """pubsub topic: 'meshtastic.receive' passes keywords: packet, interface"""
        try:
            # Safely get our own node number and ignore packets from self
            my_node_num = getattr(getattr(self.iface, "myInfo", None), "my_node_num", None)
            if not packet or packet.get("from") == my_node_num:
                return

            pkt = packet or {}
            src = pkt.get("from")
            dst = pkt.get("to")
            dec = pkt.get("decoded") or {}
            text = dec.get("text")

            meta = MsgMeta(
                msg_id=str(pkt.get("id")) if pkt.get("id") is not None else None,
                src=src,
                dst=dst,
                channel=pkt.get("channel"),
                encrypted=bool(pkt.get("encrypted")),
                hop_limit=pkt.get("hop_limit"),
                rx_time=pkt.get("rx_time"),
            )
            self._emit(meta)

            if text:
                self._emit(events.RxText(src=src, text=text, dst=dst))

            pos = dec.get("position")
            if isinstance(pos, dict) and ("latitude" in pos and "longitude" in pos):
                self._emit(
                    Position(
                        num=src,
                        lat=float(pos.get("latitude") or 0.0),
                        lon=float(pos.get("longitude") or 0.0),
                        alt=pos.get("altitude"),
                        ts=pkt.get("rx_time") or time.time(),
                    )
                )

            if pkt.get("ack"):
                self._emit(events.Ack(msg_id=str(pkt.get("id")) if pkt.get("id") is not None else "0"))

        except Exception as e:
            self._emit(events.Log(text=f"RX error: {e!r}"))

    def _on_connection(self, interface=None, event_name=None, **kwargs):
        """pubsub topic: 'meshtastic.connection' passes keywords: interface, event_name"""
        name = event_name or ""
        up = name.endswith("established")
        down = name.endswith("lost") or name == "disconnected"
        if up:
            self._emit(Connection(up=True, detail=name))
            self._push_owner()
            self._push_channels()
            self._push_nodes_snapshot()
        elif down:
            self._emit(Connection(up=False, detail=name))

    def _on_node(self, node=None, interface=None, **kwargs):
        """pubsub topic: 'meshtastic.node' passes keywords: node, interface"""
        try:
            n = node or {}
            num = n.get("num")
            short = n.get("user", {}).get("longName") or n.get("shortName") or f"{num:x}"
            ts = n.get("lastHeard") or time.time()
            self._emit(events.Beacon(num=num, short=short, ts=ts))
        except Exception:
            pass

    # ---------- Helpers ----------
    def _push_owner(self):
        try:
            me = getattr(self.iface, "myInfo", None)
            user = getattr(me, "user", None)
            long_name = getattr(user, "long_name", "") or getattr(user, "longName", "") or ""
            short_name = getattr(user, "short_name", "") or getattr(user, "shortName", "") or ""
            if long_name or short_name:
                self._emit(OwnerInfo(long=long_name, short=short_name))
        except Exception:
            pass

    def _push_channels(self):
        try:
            rc = getattr(self.iface, "radioConfig", None)
            chmap = getattr(rc, "channels", None)
            items = []
            if isinstance(chmap, dict):
                for i, ch in sorted(chmap.items()):
                    name = getattr(getattr(ch, "settings", None), "name", "") or f"ch{i}"
                    items.append((int(i), str(name)))
            elif hasattr(rc, "channels") and isinstance(rc.channels, list):
                for i, ch in enumerate(rc.channels):
                    name = getattr(getattr(ch, "settings", None), "name", "") or f"ch{i}"
                    items.append((i, str(name)))
            self._emit(Channels(items=items))
        except Exception:
            pass

    def _push_nodes_snapshot(self):
        try:
            nodes = getattr(self.iface, "nodes", {}) or {}
            for n in nodes.values():
                self._on_node(n)
        except Exception:
            pass

    def _subscribe(self):
        if self._subscribed or pub is None:
            return
        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_connection, "meshtastic.connection")
        pub.subscribe(self._on_node, "meshtastic.node")
        self._subscribed = True

    def _close(self):
        try:
            if self.iface:
                self.iface.close()
        except Exception:
            pass
        self.iface = None

    # ---------- Worker thread ----------
    def _worker(self, first_port):
        port = first_port
        self._subscribe()
        while not self._stop.is_set():
            try:
                if not port:
                    time.sleep(0.5)
                    port = self._next_port
                    continue
                self._emit(events.Log(text=f"Connecting to {port}"))
                self.iface = meshtastic.serial_interface.SerialInterface(port) if meshtastic else None
                if not self.iface:
                    self._emit(events.Log(text="Meshtastic not installed"))
                    return
                self._push_owner()
                self._push_channels()
                self._push_nodes_snapshot()
                while not self._stop.is_set() and self._next_port is None:
                    time.sleep(0.2)
            except Exception as e:
                self._emit(events.Log(text=f"Conn error: {e!r}"))
                time.sleep(1.5)
            finally:
                self._close()
            port = self._next_port
            self._next_port = None

    # ---------- Public API ----------
    def start(self, port=None):
        if self._thr and self._thr.is_alive():
            self._next_port = port
            return
        self._stop.clear()
        self._thr = threading.Thread(target=self._worker, args=(port,), daemon=True)
        self._thr.start()

    def stop(self):
        self._stop.set()
        self._close()
        if self._thr:
            self._thr.join(timeout=1.0)

    def set_port(self, port):
        self._next_port = port

    def send_text(self, text, dest=BROADCAST):
        try:
            if not self.iface:
                self._emit(events.Log(text="Not connected"))
                return False
            if dest == BROADCAST:
                pid = self.iface.sendText(text)
            else:
                pid = self.iface.sendText(text, destinationId=dest)
            self._emit(events.Log(text=f"TX id={pid} -> {'BROADCAST' if dest==BROADCAST else f'#{dest}'}"))
            return True
        except Exception as e:
            self._emit(events.Log(text=f"TX error: {e!r}"))
            return False

    def send_traceroute(self, dest):
        try:
            if not self.iface:
                self._emit(events.Log(text="Not connected"))
                return False
            self.iface.sendTraceRoute(dest)
            self._emit(events.Log(text=f"Traceroute to {dest}"))
            return True
        except Exception as e:
            self._emit(events.Log(text=f"Traceroute error: {e!r}"))
            return False
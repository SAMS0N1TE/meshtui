# meshtui/core/meshtastic_io.py
import threading
import time
import inspect

try:
    import meshtastic
    import meshtastic.serial_interface
    import meshtastic.tcp_interface
    from pubsub import pub
except Exception:
    meshtastic = None
    pub = None

from meshtui.core import events
from meshtui.core.events_ext import Position, MsgMeta, Channels, Connection, OwnerInfo, ConnectionFailed

BROADCAST = 0xFFFFFFFF


def _get(o, k, d=None):
    try:
        if isinstance(o, dict): return o.get(k, d)
        return getattr(o, k, d)
    except Exception:
        return d


class MeshtasticIO:
    def __init__(self, bus, loop, state, cfg):
        self.bus = bus
        self.loop = loop
        self.state = state
        self.cfg = cfg
        self.iface = None
        self._thr = None
        self._stop = threading.Event()
        self._next_port = None
        self._subscribed = False

    def _emit(self, ev):
        self.loop.call_soon_threadsafe(lambda: self.loop.create_task(self.bus.emit(ev)))

    # ---------- PubSub callbacks ----------
    def _on_receive(self, packet=None, interface=None, **kwargs):
        try:
            if not packet:
                return
            my_num = _get(_get(self.iface, "myInfo"), "my_node_num")
            if _get(packet, "from") == my_num:
                return

            dec = _get(packet, "decoded") or {}
            routing = _get(dec, "routing") or {}

            # handle ACK/NAK FIRST
            rid = _get(routing, "requestId") or _get(packet, "requestId") or _get(packet, "id")
            err = _get(routing, "errorReason") or _get(routing, "error")
            if isinstance(rid, int) and routing:
                if not err or str(err) == "NONE":
                    self.state.mark_acked(rid)
                # else NAK -> leave as is or log

            # now normal text handling
            port = _get(dec, "portnum")
            text = _get(dec, "text")
            src = _get(packet, "from");
            dst = _get(packet, "to")
            if text and isinstance(port, str) and port == "TEXT_MESSAGE_APP":
                self._emit(events.RxText(src=src, text=text, dst=dst))
                if isinstance(dst, int) and dst == my_num and isinstance(src, int):
                    self.state.ack_last_pending_from(src)

            self.state.last_rx_time = time.time()
        except Exception as e:
            self._emit(events.Log(text=f"RX error: {e!r}"))

    def _on_ack(self, packet=None, interface=None, **kwargs):
        aid = (_get(packet, "requestId") or _get(packet, "request_id") or _get(packet, "id"))
        if isinstance(aid, int):
            self.state.mark_acked(aid)

    def _on_connection(self, interface=None, event_name=None, **kwargs):
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
        try:
            n = node or {}
            num = n.get("num")
            short = n.get("user", {}).get("longName") or n.get("shortName") or f"{num:x}"
            ts = n.get("lastHeard") or time.time()
            self._emit(events.Beacon(num=num, short=short, ts=ts))
        except Exception:
            pass

    def _push_owner(self):
        try:
            info = _get(self.iface, "myInfo", {})
            user = _get(info, "user", {})
            long_name = _get(user, "longName", "")
            short_name = _get(user, "shortName", "")
            self._emit(OwnerInfo(long=long_name, short=short_name))
        except Exception as e:
            self._emit(events.Log(text=f"Owner info error: {e!r}"))

    def _push_channels(self):
        try:
            items = []
            for ch in _get(self.iface, "channels", []):
                ch_settings = _get(ch, "settings", {})
                ch_index = _get(ch, "index")
                if ch_settings and ch_index is not None:
                    items.append((ch_index, _get(ch_settings, "name", "")))
            self._emit(Channels(items=items))
        except Exception as e:
            self._emit(events.Log(text=f"Channels error: {e!r}"))

    def _push_nodes_snapshot(self):
        try:
            nodes = _get(self.iface, "nodes", {}).values()
            for n in nodes:
                num = _get(n, "num")
                user = _get(n, "user", {})
                short = _get(user, "longName") or _get(user, "shortName") or f"{num:x}"
                ts = _get(n, "lastHeard") or time.time()
                self._emit(events.Beacon(num=num, short=short, ts=ts))

                pos = _get(n, "position")
                if pos:
                    self._emit(Position(
                        num=num,
                        lat=_get(pos, "latitude", 0.0),
                        lon=_get(pos, "longitude", 0.0),
                        alt=_get(pos, "altitude", 0),
                        ts=_get(pos, "time"),
                    ))
        except Exception as e:
            self._emit(events.Log(text=f"Nodes snapshot error: {e!r}"))

    def _subscribe(self):
        if self._subscribed or pub is None:
            return
        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_ack, "meshtastic.receive.ack")
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

    def _worker(self, first_port):
        def _parse_tcp(target: str) -> tuple[str, int]:
            s = target.strip()
            if s.lower().startswith("tcp://"):
                s = s[6:]
            if s.startswith("["):
                close = s.find("]")
                if close != -1:
                    host = s[1:close]
                    rest = s[close + 1:].lstrip(":")
                    try:
                        return host, int(rest) if rest else 4403
                    except Exception:
                        return host, 4403
            host, portnum = s, 4403
            if ":" in s:
                h, maybe = s.rsplit(":", 1)
                if h:
                    host = h
                try:
                    portnum = int(maybe)
                except Exception:
                    portnum = 4403
            return host, portnum

        port = first_port
        self._subscribe()

        while not self._stop.is_set():
            if not port:
                time.sleep(0.5)
                port = self._next_port
                self._next_port = None
                continue

            try:
                self._emit(events.Log(text=f"Connecting to {port}..."))
                is_tcp = (":" in port) or ("." in port) or port.lower().startswith("tcp://")

                if meshtastic is None:
                    self.iface = None
                elif is_tcp:
                    host, tcp_port = _parse_tcp(port)
                    ctor = meshtastic.tcp_interface.TCPInterface
                    params = set(inspect.signature(ctor).parameters.keys())
                    if "portNum" in params:
                        self.iface = ctor(hostname=host, portNum=tcp_port)
                    elif "port" in params:
                        self.iface = ctor(hostname=host, port=tcp_port)
                    else:
                        # fall back to positional (hostname, portNum)
                        self.iface = ctor(host, tcp_port)
                    self._emit(events.Log(text=f"TCP {host}:{tcp_port}"))
                else:
                    baud_rate = getattr(self.cfg, "baud_rate", None)
                    if baud_rate:
                        self.iface = meshtastic.serial_interface.SerialInterface(port, baudrate=baud_rate)
                    else:
                        self.iface = meshtastic.serial_interface.SerialInterface(port)
                    self._emit(events.Log(text=f"Serial {port} baud={baud_rate or 'default'}"))

                if not self.iface:
                    self._emit(events.Log(text="Meshtastic library not installed"))
                    self._stop.set()
                    return

                self._push_owner()
                self._push_channels()
                self._push_nodes_snapshot()

                while not self._stop.is_set() and self._next_port is None:
                    time.sleep(0.2)

            except Exception as e:
                self._emit(ConnectionFailed(port=port, error=repr(e)))
                port = None
            finally:
                self._close()

            if self._next_port:
                port = self._next_port
                self._next_port = None

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
            self._thr.join(timeout=3.0)

    def set_port(self, port):
        self._next_port = port

    def sendText(self, text, destinationId=BROADCAST, wantAck=False, **kwargs):
        try:
            if not self.iface:
                self._emit(events.Log(text="Not connected"))
                return None
            try:
                return self.iface.sendText(text, destinationId=destinationId, wantAck=wantAck, **kwargs)
            except TypeError:
                return self.iface.sendText(text, destinationId=destinationId, wantAck=wantAck)
        except Exception as e:
            self._emit(events.Log(text=f"TX error: {e!r}"))
            return None

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

# meshtui/core/mqtt_ptk.py
import asyncio
from typing import Optional

try:
    import paho.mqtt.client as mqtt
except Exception:
    mqtt = None

from meshtui.core import events

class MQTTClient:
    def __init__(self, bus, loop, state=None, cfg=None):
        self.bus = bus
        self.loop = loop
        self.state = state
        self.cfg = cfg
        self.client: Optional["mqtt.Client"] = None
        self._connected = False

    def _emit(self, ev):
        if self.state and hasattr(self.state, "add_log") and isinstance(getattr(ev, "text", None), str):
            self.state.add_log(ev.text)
        self.loop.call_soon_threadsafe(lambda: self.loop.create_task(self.bus.emit(ev)))

    # paho callbacks
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self._connected = (rc == 0)
        self._emit(events.Log(text=f"MQTT connect rc={rc}"))
        if self._connected:
            try:
                client.subscribe("#", qos=0)
            except Exception:
                pass

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode(errors="ignore")
        except Exception:
            payload = "<binary>"
        self._emit(events.Log(text=f"MQTT {msg.topic}: {payload[:200]}"))

    def _on_disconnect(self, client, userdata, rc, properties=None):
        self._connected = False
        self._emit(events.Log(text=f"MQTT disconnected rc={rc}"))

    def connect(self, host: str = "localhost", port: int = 1883, client_id: Optional[str] = None, tls: bool = False):
        if mqtt is None:
            self._emit(events.Log(text="paho-mqtt not installed"))
            return False
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
        self.client = mqtt.Client(client_id=client_id or "meshtui")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        if tls:
            try:
                self.client.tls_set()
            except Exception:
                self._emit(events.Log(text="MQTT TLS setup failed"))
        try:
            self.client.connect(host, port, keepalive=30)
            self.client.loop_start()
            return True
        except Exception as e:
            self._emit(events.Log(text=f"MQTT connect error: {e!r}"))
            return False

    def disconnect(self):
        if not self.client:
            return
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
        self.client = None
        self._connected = False

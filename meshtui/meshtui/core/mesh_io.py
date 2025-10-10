# meshtui/core/mesh_io.py
import asyncio
import time
import meshtastic
from meshtastic.protobuf.portnums_pb2 import PortNum
from meshtui.core.events import Beacon, RxText, Ack, Log

async def run_meshtastic(bus, iface):
    loop = asyncio.get_running_loop()

    def on_receive(packet, interface):
        try:
            if packet.decoded.portnum == PortNum.TEXT_MESSAGE_APP and packet.decoded.text:
                ev = RxText(src=packet.fromId, text=packet.decoded.text)
                asyncio.run_coroutine_threadsafe(bus.emit(ev), loop)
            elif packet.decoded.portnum == PortNum.TRACEROUTE_APP:
                ev = Log(text=f"Traceroute reply from {packet.fromId}")
                asyncio.run_coroutine_threadsafe(bus.emit(ev), loop)
            if packet.ack:
                ev = Ack(msg_id=getattr(packet, "id", 0))
                asyncio.run_coroutine_threadsafe(bus.emit(ev), loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(bus.emit(Log(text=f"RX error: {e}")), loop)

    def on_node_updated(node, interface):
        try:
            num = node.get("num")
            short = node.get("shortName", "?")
            ts = time.time()
            ev = Beacon(num=num, short=short, ts=ts)
            asyncio.run_coroutine_threadsafe(bus.emit(ev), loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(bus.emit(Log(text=f"Node update error: {e}")), loop)

    iface.onReceive = on_receive
    iface.onNodeUpdated = on_node_updated

    while True:
        await asyncio.sleep(1)

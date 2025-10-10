# meshtui/core/actions.py
import time
from meshtui.core.events import Log

def send_text(state, iface, bus, text: str):
    dest = None if state.dm_target is None else state.dm_target
    try:
        pkt = iface.sendText(text, destinationId=dest, wantAck=True)
        msg_id = getattr(pkt, "id", None)
        t = time.strftime("%H:%M:%S")
        state.log.append(f"[{t}] TX -> {dest or 'BROADCAST'}: {text}")
        return msg_id
    except Exception as e:
        state.log.append(f"[ERR] send_text: {e}")
        return None

def send_traceroute(iface, dest_num: int):
    from meshtastic.protobuf.portnums_pb2 import PortNum
    from meshtastic.protobuf.mesh_pb2 import MeshPacket
    try:
        pkt = MeshPacket()
        pkt.to = dest_num
        pkt.want_ack = True
        pkt.want_response = True
        pkt.decoded.portnum = PortNum.TRACEROUTE_APP
        iface.sendPacket(pkt)
        return True
    except Exception:
        return False

def reconnect(iface_class, port: str, bus):
    try:
        iface = iface_class(port)
        return iface
    except Exception as e:
        print(f"Reconnect failed: {e}")
        return None

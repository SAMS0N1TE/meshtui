# rx_hooks.py
from meshtui.model import MsgStatus
from meshtui.core.state import AppState

def handle_rx_packet(state: AppState, packet):
    """
    packet: MeshPacket
    Called for every received packet.
    """
    if hasattr(packet, "decoded") and packet.decoded.portnum == "ACK":
        delivery_id = getattr(packet, "id", None)
        if delivery_id is not None:
            state.mark_acked(delivery_id)
            state.add_log(f"ACK received for TX id {delivery_id}")
        return

    # normal message path
    payload = getattr(packet.decoded, "payload", b"").decode(errors="ignore")
    src = getattr(packet, "fromId", None)
    dst = getattr(packet, "toId", None)
    state.add_chat(dst, payload, sender_id=src)

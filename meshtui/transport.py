# meshtui/transport.py
import asyncio
import time
from typing import Any, Dict, Optional

try:
    from meshtui.core.meshtastic_io import MeshtasticIO, BROADCAST
    from meshtui.core.ack_registry import ack_registry
except Exception:
    # Fallback relative imports if package layout differs
    from .core.meshtastic_io import MeshtasticIO, BROADCAST  # type: ignore
    from .core.ack_registry import ack_registry  # type: ignore

# Minimal enum shim to avoid importing your whole state layer
class MsgStatus:
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACK = "ACK"
    NAK = "NAK"
    TIMEOUT = "TIMEOUT"

def _extract_tx_id(pkt: Any) -> Optional[int]:
    if pkt is None:
        return None
    if isinstance(pkt, dict):
        v = pkt.get("id")
        return int(v) if isinstance(v, int) else None
    v = getattr(pkt, "id", None)
    return int(v) if isinstance(v, int) else None

async def send_with_ack(
    state: Any,
    iface_or_io: Any,
    to: str,
    text: str,
    *,
    channelIndex: Optional[int] = None,
    portNum: Optional[int] = None,
    timeout_s: float = 20.0,
    msg: Optional[Any] = None  # Add msg parameter
) -> Dict[str, Any]:
    """
    Send a directed message and await protocol ACK/NAK.
    Returns a result dict with fields: {"status": "ACK"/"NAK"/"TIMEOUT", "tx_id": int|None, "from": int|None}
    Side-effects:
      - Calls state.bind_delivery_ids(msg, tx_id) if available.
      - Calls state.mark_acked(tx_id) or state.mark_nacked(tx_id) if available.
    """
    loop = asyncio.get_running_loop()

    # Normalize interface
    if isinstance(iface_or_io, MeshtasticIO):
        io = iface_or_io
    else:
        # Accept raw meshtastic interface and wrap
        io = MeshtasticIO(iface_or_io)

    # Build kwargs only when set to avoid TypeError on older libs
    kwargs = {"destinationId": to, "wantAck": True}
    if channelIndex is not None:
        kwargs["channelIndex"] = int(channelIndex)
    if portNum is not None:
        kwargs["portNum"] = int(portNum)

    # Offload blocking send
    pkt = await loop.run_in_executor(None, lambda: io.sendText(text=text, **kwargs))
    tx_id = _extract_tx_id(pkt)
    if isinstance(tx_id, int):
        ack_registry.register(tx_id)
        # optional: bind into your UI/state if method exists
        if hasattr(state, "bind_delivery_ids") and msg is not None:
            state.bind_delivery_ids(msg, tx_id)

    # Flip UI to SENT immediately if state has a message
    if hasattr(state, "set_current_status"):
        state.set_current_status(MsgStatus.SENT)

    # Wait for ACK/NAK
    result = None
    if isinstance(tx_id, int):
        result = await loop.run_in_executor(None, lambda: ack_registry.wait_for(tx_id, timeout_s))

    if not result:
        # timeout path
        if hasattr(state, "mark_timeout"):
            state.mark_timeout(tx_id)
        return {"status": MsgStatus.TIMEOUT, "tx_id": tx_id, "from": None}

    # reflect status into state if the helpers exist
    st = result.get("state")
    origin = result.get("from")
    if st == "ACK":
        if hasattr(state, "mark_acked"):
            state.mark_acked(tx_id, origin)
        return {"status": MsgStatus.ACK, "tx_id": tx_id, "from": origin}
    if st == "NAK":
        if hasattr(state, "mark_nacked"):
            state.mark_nacked(tx_id, origin)
        return {"status": MsgStatus.NAK, "tx_id": tx_id, "from": origin}

    # Unexpected state
    return {"status": MsgStatus.TIMEOUT, "tx_id": tx_id, "from": None}
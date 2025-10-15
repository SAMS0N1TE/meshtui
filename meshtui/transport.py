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
    loop = asyncio.get_running_loop()

    # Normalize interface
    if isinstance(iface_or_io, MeshtasticIO):
        io = iface_or_io
    else:
        # Accept raw meshtastic interface and wrap
        io = MeshtasticIO(iface_or_io)

    kwargs = {"destinationId": to, "wantAck": True}
    if channelIndex is not None:
        kwargs["channelIndex"] = int(channelIndex)
    if portNum is not None:
        kwargs["portNum"] = int(portNum)

    pkt = await loop.run_in_executor(None, lambda: io.sendText(text=text, **kwargs))
    tx_id = _extract_tx_id(pkt)
    if isinstance(tx_id, int):
        ack_registry.register(tx_id)
        # optional: bind into your UI/state if method exists
        if hasattr(state, "bind_delivery_ids") and msg is not None:
            state.bind_delivery_ids(msg, tx_id)

    if hasattr(state, "set_current_status"):
        state.set_current_status(MsgStatus.SENT)

    result = None
    if isinstance(tx_id, int):
        result = await loop.run_in_executor(None, lambda: ack_registry.wait_for(tx_id, timeout_s))

    if not result:
        # timeout path
        if hasattr(state, "mark_timeout"):
            state.mark_timeout(tx_id)
        return {"status": MsgStatus.TIMEOUT, "tx_id": tx_id, "from": None}

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

    return {"status": MsgStatus.TIMEOUT, "tx_id": tx_id, "from": None}

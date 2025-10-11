# meshtui/transport.py
import asyncio
from meshtui.model import MsgStatus
from meshtui.core.meshtastic_io import BROADCAST

ACK_TIMEOUT = 30.0

def _handle_resp(state, msg, fut, packet):
    """
    Callback for onResponse. Runs in the interface thread, so we
    use call_soon_threadsafe to update state in the main asyncio loop.
    """
    try:
        dec = packet.get("decoded", {})
        routing = dec.get("routing", {})
        # NAK if error is present and not "NONE"; else treat as ACK.
        err = routing.get("errorReason") or routing.get("error")
        if err and str(err) != "NONE":
            msg.status = MsgStatus.FAILED
        else:
            msg.status = MsgStatus.ACKED
    finally:
        if not fut.done():
            # Signal the waiting future that we have a result
            fut.set_result(True)

async def send_with_ack(state, iface, to: int, text: str):
    """
    Uses the Meshtastic library's built-in onResponse correlation.
    """
    loop = asyncio.get_running_loop()

    # Broadcast messages cannot be ACKed
    if to == BROADCAST:
        msg = state.add_outgoing(to, text)
        await loop.run_in_executor(None, lambda: iface.sendText(text=text, destinationId=to))
        msg.status = MsgStatus.SENT
        return msg

    msg = state.add_outgoing(to, text)
    # Create a future that the onResponse callback will resolve
    fut: asyncio.Future = loop.create_future()

    def on_resp(packet):
        # This callback is executed by the Meshtastic thread.
        # We need to bounce it over to our main asyncio event loop.
        loop.call_soon_threadsafe(_handle_resp, state, msg, fut, packet)

    # This synchronous call runs in a thread to avoid blocking the UI
    pkt = await loop.run_in_executor(None, lambda: iface.sendText(
        text=text,
        destinationId=to,
        wantAck=True,
        wantResponse=True,
        onResponse=on_resp
    ))

    tx_id = getattr(pkt, "id", None)
    state.bind_delivery_ids(msg, *(i for i in (tx_id,) if isinstance(i, int)))
    msg.status = MsgStatus.SENT

    try:
        # Wait for the future to be resolved by the on_resp callback
        await asyncio.wait_for(fut, timeout=ACK_TIMEOUT)
    except asyncio.TimeoutError:
        msg.status = MsgStatus.FAILED
    return msg
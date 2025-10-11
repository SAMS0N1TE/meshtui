# meshtui/main.py
import asyncio
from prompt_toolkit.patch_stdout import patch_stdout

from meshtui.core.state import AppState
from meshtui.core.bus import Bus
from meshtui.core.config import Config, apply_to_state
from meshtui.core.meshtastic_io import MeshtasticIO
from meshtui.core.mqtt_ptk import MQTTClient
from meshtui.core.reducer import apply_event
from meshtui.ui_ptk.layout import build_layout
from meshtui.ui_ptk import dialogs

async def bus_listener(state, bus):
    """Listen for events on the bus and apply them to the state."""
    async for ev in bus.listen():
        apply_event(state, ev)

async def main():
    # Setup
    cfg = Config.load()
    state = AppState()
    bus = Bus()
    loop = asyncio.get_event_loop()
    apply_to_state(cfg, state)

    # I/O Handlers
    meshtastic_io = MeshtasticIO(bus=bus, loop=loop, state=state)
    mqtt_client = MQTTClient(bus=bus, loop=loop)

    # Actions available to the UI
    actions = {
        "send_traceroute": meshtastic_io.send_traceroute,
    }

    # Build the UI
    app = build_layout(state=state, actions=actions, iface=meshtastic_io, bus=bus, initial_theme=cfg.theme, cfg=cfg)

    # Start background tasks
    listener_task = asyncio.create_task(bus_listener(state, bus))

    # Initial setup wizard if config is incomplete
    if not cfg.is_ready():
        await dialogs.setup_wizard(app, state, meshtastic_io, cfg)

    # Start Meshtastic & MQTT connections after potential setup
    if cfg.last_port:
        meshtastic_io.start(cfg.last_port)
    if cfg.mqtt_enabled:
        mqtt_client.connect(host=cfg.mqtt_host, port=cfg.mqtt_port, tls=cfg.mqtt_tls)

    # Run the application, capturing stdout
    try:
        with patch_stdout(raw=True):
            await app.run_async()
    finally:
        # Cleanup
        meshtastic_io.stop()
        mqtt_client.disconnect()
        listener_task.cancel()
        await asyncio.gather(listener_task, return_exceptions=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
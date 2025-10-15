# meshtui/main.py
import asyncio
from prompt_toolkit.patch_stdout import patch_stdout
from meshtui.core.state import AppState
from meshtui.core.bus import Bus
from meshtui.core.config import Config, apply_to_state
from meshtui.core.meshtastic_io import MeshtasticIO
from meshtui.core.mqtt_ptk import MQTTClient
from meshtui.core.reducer import apply_event
from meshtui.core.events_ext import ConnectionFailed
from meshtui.ui_ptk.layout import build_layout
from meshtui.ui_ptk import dialogs


async def bus_listener(state, bus, app, iface, cfg):
    """Listen for events on the bus and apply them to the state."""
    async for ev in bus.listen():
        apply_event(state, ev)
        if isinstance(ev, ConnectionFailed):
            await dialogs.show_connection_error_dialog(app, iface, cfg, ev.port, ev.error)
        app.invalidate()


async def main():
    # Load config and initialize core components
    cfg = Config.load()
    state = AppState()
    bus = Bus()
    loop = asyncio.get_event_loop()

    # Apply config to state
    apply_to_state(cfg, state)

    # Initialize I/O handlers
    meshtastic_io = MeshtasticIO(bus, loop, state, cfg)
    mqtt_client = MQTTClient(bus, loop)

    class Actions:
        pass
    actions = Actions()

    # Build the application UI
    app = build_layout(state, actions, meshtastic_io, bus, initial_theme=cfg.theme, cfg=cfg)

    # Start background tasks
    listener_task = loop.create_task(bus_listener(state, bus, app, meshtastic_io, cfg))

    if not cfg.is_ready():
        loop.create_task(dialogs.setup_wizard(app, state, meshtastic_io, cfg))
    else:
        meshtastic_io.start(port=cfg.last_port)
        if cfg.mqtt_enabled:
            mqtt_client.connect(host=cfg.mqtt_host, port=cfg.mqtt_port, tls=cfg.mqtt_tls)

    # Run the application
    with patch_stdout():
        try:
            await app.run_async()
        finally:
            # Cleanup
            meshtastic_io.stop()
            mqtt_client.disconnect()
            await asyncio.gather(listener_task, return_exceptions=True)
            listener_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
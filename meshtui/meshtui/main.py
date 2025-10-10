# meshtui/main.py
import asyncio, sys
from meshtui.core.bus import Bus
from meshtui.core.state import AppState
from meshtui.core.config import Config, apply_to_state
from meshtui.core.meshtastic_io import MeshtasticIO
from meshtui.core.mqtt_ptk import MQTTClient
from meshtui.core.reducer import apply_event
from meshtui.ui_ptk.layout import build_layout
from meshtui.ui_ptk import dialogs

async def main():
    cfg = Config.load()
    bus = Bus()
    state = AppState()
    apply_to_state(cfg, state)

    loop = asyncio.get_event_loop()
    iface = MeshtasticIO(bus, loop)
    mqtt_client = MQTTClient(bus, loop)

    async def bus_listener():
        async for ev in bus.listen():
            apply_event(state, ev)

    listener_task = asyncio.create_task(bus_listener())

    app = build_layout(state, actions={"send": iface.send_text, "traceroute": iface.send_traceroute},
                       iface=iface, bus=bus, initial_theme=cfg.theme, cfg=cfg)

    if not cfg.is_ready():
        await dialogs.setup_wizard(app, state, iface, cfg)

    if cfg.last_port:
        iface.start(cfg.last_port)
    if cfg.mqtt_enabled:
        mqtt_client.connect(cfg.mqtt_host, cfg.mqtt_port, tls=cfg.mqtt_tls)

    try:
        await app.run_async()
    finally:
        iface.stop()
        mqtt_client.disconnect()
        cfg.active_channels = list(state.active_channels)
        cfg.save()
        listener_task.cancel()
        await asyncio.gather(listener_task, return_exceptions=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)

# meshtui/main.py
import asyncio, sys
from prompt_toolkit.patch_stdout import patch_stdout

from meshtui.core.state import AppState
from meshtui.core.bus import Bus
from meshtui.core.config import Config, apply_to_state
from meshtui.core.reducer import apply_event
from meshtui.core.events_ext import ConnectionFailed
from meshtui.ui_ptk.layout import build_layout
from meshtui.ui_ptk import dialogs
from meshtui.core.meshtastic_io import MeshtasticIO
from meshtui.core.mqtt_ptk import MQTTClient

try:
    from meshtui.core.actions import build_actions
except Exception:
    def build_actions(*_a, **_k):
        class _A: ...
        return _A()

async def bus_listener(state, bus, app, iface, cfg):
    try:
        async for ev in bus.listen():
            try:
                apply_event(state, ev)
            except Exception as e:
                state.add_log(f"[reducer] error: {e!r}")
            if isinstance(ev, ConnectionFailed):
                if getattr(state, "in_wizard", False):
                    state.add_log(f"[connect] error during wizard: {ev.port} -> {ev.error}")
                else:
                    try:
                        await dialogs.show_connection_error_dialog(app, iface, cfg, ev.port, ev.error)
                    except Exception as e:
                        state.add_log(f"[dialog] error: {e!r}")
            app.invalidate()
    except asyncio.CancelledError:
        return


async def main():
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
        except Exception:
            pass

    loop = asyncio.get_running_loop()

    try:
        cfg = Config.load()
    except Exception:
        cfg = Config()
    state = AppState()
    apply_to_state(cfg, state)
    bus = Bus()

    # Constructors that match your real signatures
    iface = MeshtasticIO(bus, loop, state, cfg)
    mqtt = MQTTClient(bus, loop, state, cfg)

    actions = build_actions(state=state, bus=bus, iface=iface, cfg=cfg)
    app = build_layout(
        state=state,
        actions=actions,
        iface=iface,
        bus=bus,
        initial_theme=getattr(cfg, "theme", None),
        cfg=cfg,
    )

    async def _startup():
        try:
            if not getattr(cfg, "last_port", None):
                await dialogs.setup_wizard(app, state, iface, cfg)
            if getattr(cfg, "last_port", None):
                try:
                    iface.start(port=cfg.last_port)
                    state.add_log(f"[serial] connecting {cfg.last_port}")
                except Exception as e:
                    state.add_log(f"[serial] start error: {e!r}")
                    await dialogs.show_connection_error_dialog(app, iface, cfg, cfg.last_port, e)
            if getattr(cfg, "mqtt_enabled", False):
                try:
                    mqtt.connect(
                        host=getattr(cfg, "mqtt_host", "localhost"),
                        port=int(getattr(cfg, "mqtt_port", 1883)),
                        tls=bool(getattr(cfg, "mqtt_tls", False)),
                    )
                    state.add_log("[mqtt] connected")
                except Exception as e:
                    state.add_log(f"[mqtt] connect error: {e!r}")
        except Exception as e:
            state.add_log(f"[startup] error: {e!r}")
        app.invalidate()

    app.create_background_task(_startup())
    listener_task = asyncio.create_task(bus_listener(state, bus, app, iface, cfg))

    try:
        with patch_stdout():
            await app.run_async()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            app.exit()
        except Exception:
            pass
        try:
            iface.stop()
        except Exception:
            pass
        try:
            mqtt.disconnect()
        except Exception:
            pass
        if not listener_task.done():
            listener_task.cancel()
        await asyncio.gather(listener_task, return_exceptions=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

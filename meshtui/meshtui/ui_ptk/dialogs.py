# meshtui/ui_ptk/dialogs.py
from __future__ import annotations
from typing import List, Tuple, Optional
from prompt_toolkit.shortcuts import input_dialog, radiolist_dialog, yes_no_dialog, message_dialog
from meshtui.themes import ThemeManager

try:
    import serial.tools.list_ports as _list_ports
except Exception:
    _list_ports = None

def _available_ports() -> List[str]:
    if _list_ports is None:
        return []
    return sorted([p.device for p in _list_ports.comports()], key=str.lower)

async def pick_channel(app, state, iface) -> None:
    rc = getattr(getattr(iface, "iface", None), "radioConfig", None)
    chmap = getattr(rc, "channels", None)
    items: List[Tuple[int, str]] = []
    if isinstance(chmap, dict):
        for i, ch in sorted(chmap.items()):
            name = getattr(getattr(ch, "settings", None), "name", "") or f"ch{i}"
            items.append((int(i), name))
    if not items:
        message_dialog(title="Channels", text="No channels reported by the device.").run()
        return
    idx = await radiolist_dialog(title="Select Channel", text="Choose a primary channel:", values=items).run_async()
    if idx is None:
        return
    try:
        dev = getattr(iface, "iface", None)
        setter = getattr(dev, "setChannel", None)
        if callable(setter):
            setter(idx)
            state.add_log(f"Channel set to {dict(items).get(idx, f'ch{idx}')}")
    except Exception:
        state.add_log("Channel change not supported by this firmware/API")
    app.invalidate()

async def connect_port(app, state, iface) -> Optional[str]:
    ports = _available_ports()
    port = None
    if ports:
        sel = await radiolist_dialog(title="Connect", text="Select serial port:", values=[(p, p) for p in ports]).run_async()
        if sel:
            port = sel
    if not port:
        port = await input_dialog(title="Connect", text="Enter serial port (e.g., COM5 or /dev/ttyUSB0):").run_async()
    if not port:
        return None
    try:
        iface.set_port(port)
        iface.start()
        state.add_log(f"Connecting to {port}")
    except Exception as e:
        state.add_log(f"Connect error: {e!r}")
    app.invalidate()
    return port

async def edit_owner(app, state, iface) -> None:
    dev = getattr(iface, "iface", None)
    curr_long = curr_short = ""
    try:
        info = getattr(dev, "myInfo", None); user = getattr(info, "user", None)
        curr_long = getattr(user, "long_name", "") or getattr(user, "longName", "") or ""
        curr_short = getattr(user, "short_name", "") or getattr(user, "shortName", "") or ""
    except Exception:
        pass
    new_long = await input_dialog(title="Owner Long Name", text=f"Current: {curr_long}\nNew value:").run_async()
    if new_long is None: return
    new_short = await input_dialog(title="Owner Short Name", text=f"Current: {curr_short}\nNew value:").run_async()
    if new_short is None: return
    try:
        setter = getattr(dev, "setOwner", None)
        if callable(setter):
            setter(long_name=new_long, short_name=new_short)
            state.add_log("Owner updated")
        else:
            state.add_log("Owner update not supported by this device/API")
    except Exception:
        state.add_log("Owner update failed")
    app.invalidate()

async def confirm_reboot(app, state, iface) -> None:
    yes = await yes_no_dialog(title="Reboot Device", text="Send remote reboot?").run_async()
    if not yes: return
    try:
        dev = getattr(iface, "iface", None); reboot = getattr(dev, "reboot", None)
        if callable(reboot): reboot(); state.add_log("Reboot command sent")
        else: state.add_log("Reboot not supported")
    except Exception:
        state.add_log("Reboot failed")
    app.invalidate()

async def setup_wizard(app, state, iface, cfg) -> None:
    # Theme
    tm = ThemeManager()
    names = tm.names()
    theme = await radiolist_dialog(title="Meshtui Setup", text="Choose a theme:", values=[(n, n) for n in names]).run_async()
    if theme:
        cfg.theme = theme
        # apply immediately
        try:
            from meshtui.themes import _style_from_dict, THEMES
            app.style = _style_from_dict(THEMES[theme])
        except Exception:
            pass
        app.invalidate()

    # Port
    await connect_port(app, state, iface)
    cfg.last_port = getattr(iface, "_next_port", None) or getattr(getattr(iface, "iface", None), "port", None)

    # MQTT
    enable = await yes_no_dialog(title="MQTT", text="Enable MQTT integration?").run_async()
    cfg.mqtt_enabled = bool(enable)
    if cfg.mqtt_enabled:
        host = await input_dialog(title="MQTT Host", text=f"Host (current: {cfg.mqtt_host}):").run_async()
        port = await input_dialog(title="MQTT Port", text=f"Port (current: {cfg.mqtt_port}):").run_async()
        tls  = await yes_no_dialog(title="MQTT TLS", text=f"Use TLS? Current: {'on' if cfg.mqtt_tls else 'off'}").run_async()
        if host: cfg.mqtt_host = host
        if port:
            try: cfg.mqtt_port = int(port)
            except Exception: pass
        cfg.mqtt_tls = bool(tls)

    cfg.save()
    state.add_log("Setup saved")
    app.invalidate()
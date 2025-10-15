# meshtui/ui_ptk/dialogs.py  — top of file
from __future__ import annotations
import asyncio
from typing import List, Tuple, Optional, Any

from prompt_toolkit.application.current import get_app
from prompt_toolkit.layout import Float
from prompt_toolkit.widgets import Dialog, Button, Label, RadioList, TextArea
from prompt_toolkit.layout.containers import HSplit
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from meshtui.themes import ThemeManager


def _start_iface(iface, port):
    # 1) Normal instance method
    fn = getattr(iface, "start", None)
    if callable(fn):
        return fn(port=port)

    # 2) Unbound class method (covers weird proxies / attribute masking)
    tfn = getattr(type(iface), "start", None)
    if callable(tfn):
        return tfn(iface, port=port)

    # 3) Common wrappers hold the real engine
    inner = getattr(iface, "io", None) or getattr(iface, "iface", None)
    if inner:
        fn = getattr(inner, "start", None)
        if callable(fn):
            return fn(port=port)
        tfn = getattr(type(inner), "start", None)
        if callable(tfn):
            return tfn(inner, port=port)

    # 4) Last-resort fallbacks used by some codebases
    for name in ("connect", "run", "open"):
        fn = getattr(iface, name, None)
        if callable(fn):
            try:
                return fn(port)  # positional
            except TypeError:
                return fn(port=port)
        if inner:
            fn = getattr(inner, name, None)
            if callable(fn):
                try:
                    return fn(port)
                except TypeError:
                    return fn(port=port)

    raise AttributeError("No usable start/connect on iface")


# ---------------- Serial ports ----------------
try:
    import serial.tools.list_ports as _list_ports
except Exception:
    _list_ports = None

def _available_ports() -> List[str]:
    if _list_ports is None:
        return []
    return sorted([p.device for p in _list_ports.comports()], key=str.lower)

# ---------------- Generic float runner ----------------
async def _show_container(container, fut: asyncio.Future) -> Any:
    app = get_app()
    root = app.layout.container
    prev_modal = getattr(root, "modal", False)
    flt = Float(content=container, z_index=100)

    kb = KeyBindings()
    @kb.add("escape")
    def _(event):
        if not fut.done():
            fut.set_result(None)

    if hasattr(container, "container"):
        container = container
        container.key_bindings = kb

    prev_focus = app.layout.current_window
    root.floats.insert(0, flt)
    root.modal = True
    try:
        app.layout.focus(container)
        app.invalidate()
        result = await fut
        return result
    finally:
        if flt in root.floats:
            root.floats.remove(flt)
        root.modal = prev_modal
        if prev_focus:
            app.layout.focus(prev_focus)
        app.invalidate()

# ---------------- Dialog builders ----------------
def _radio_dialog(title: str, text: str, values: List[Tuple[Any, str]]) -> tuple[Dialog, asyncio.Future]:
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    radios = RadioList(values=values)
    msg = Label(text)

    def _ok():
        if not fut.done():
            fut.set_result(radios.current_value)

    def _cancel():
        if not fut.done():
            fut.set_result(None)

    dlg = Dialog(
        title=title,
        body=HSplit([msg, radios], padding=1),
        buttons=[Button(text="OK", handler=_ok), Button(text="Cancel", handler=_cancel)],
        width=None,
        with_background=True,
    )
    return dlg, fut

def _input_dialog(title: str, text: str, default: str = "") -> tuple[Dialog, asyncio.Future]:
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    ta = TextArea(text=default, height=1, multiline=False)
    msg = Label(text)

    def _ok():
        if not fut.done():
            fut.set_result(ta.text)

    def _cancel():
        if not fut.done():
            fut.set_result(None)

    # Enter submits, Esc handled by _show_container
    kb = KeyBindings()
    @kb.add(Keys.Enter)
    def _(event):
        _ok()

    ta.control.key_bindings = kb  # type: ignore[attr-defined]

    dlg = Dialog(
        title=title,
        body=HSplit([msg, ta], padding=1),
        buttons=[Button(text="OK", handler=_ok), Button(text="Cancel", handler=_cancel)],
        with_background=True,
    )
    return dlg, fut

def _yesno_dialog(title: str, text: str) -> tuple[Dialog, asyncio.Future]:
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    msg = Label(text)

    def _yes():
        if not fut.done():
            fut.set_result(True)

    def _no():
        if not fut.done():
            fut.set_result(False)

    dlg = Dialog(
        title=title,
        body=HSplit([msg]),
        buttons=[Button(text="Yes", handler=_yes), Button(text="No", handler=_no)],
        with_background=True,
    )
    return dlg, fut

def _message_dialog(title: str, text: str) -> tuple[Dialog, asyncio.Future]:
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    msg = Label(text)

    def _ok():
        if not fut.done():
            fut.set_result(None)

    dlg = Dialog(
        title=title,
        body=HSplit([msg]),
        buttons=[Button(text="OK", handler=_ok)],
        with_background=True,
    )
    return dlg, fut

# ---------------- Simple wrappers used below ----------------
async def _info(title: str, text: str) -> None:
    dlg, fut = _message_dialog(title, text)
    await _show_container(dlg, fut)

async def _confirm(title: str, text: str) -> bool:
    dlg, fut = _yesno_dialog(title, text)
    res = await _show_container(dlg, fut)
    return bool(res)

async def _ask(title: str, text: str, default: str = "") -> Optional[str]:
    dlg, fut = _input_dialog(title, text, default)
    return await _show_container(dlg, fut)

async def _radio(title: str, text: str, values: List[Tuple[Any, str]]) -> Any:
    dlg, fut = _radio_dialog(title, text, values)
    return await _show_container(dlg, fut)

# ---------------- Public API ----------------
async def connect_tcp(app, iface, cfg):
    host_default = (
        cfg.last_port if isinstance(getattr(cfg, "last_port", None), str)
        and (":" in cfg.last_port or "." in cfg.last_port) else "meshtastic.local"
    )
    host = await _ask("TCP Connection", "Enter hostname or IP[:port]:", host_default)
    if not host:
        return
    try:
        _start_iface(iface, host)
        st = getattr(iface, "state", None)
        if st: st.add_log(f"[tcp] connecting {host}")
        cfg.last_port = host
        cfg.save()
    except Exception as e:
        st = getattr(iface, "state", None)
        if st: st.add_log(f"[tcp] connect error: {e!r}")
    app.invalidate()

# meshtui/ui_ptk/dialogs.py — replace show_connection_error_dialog
async def show_connection_error_dialog(app, iface, cfg, port, error):
    st = getattr(iface, "state", None)
    if getattr(st, "in_wizard", False):
        if st: st.add_log(f"[connect] suppressed popup during wizard: {port} -> {error}")
        return
    choice = await _radio(
        "Connection Error",
        f"Failed to connect to '{port}'.\n\nError: {error}\n\nWhat next?",
        [("retry","Try Again"), ("reconfigure","Choose Different Port"), ("tcp","Connect via TCP/IP"), ("cancel","Cancel")],
    )
    if choice == "retry":
        try:
            _start_iface(iface, port)     # <-- use safe starter
        except Exception as e:
            if st: st.add_log(f"[retry] error: {e!r}")
    elif choice == "reconfigure":
        await connect_port(app, iface.state, iface, cfg)
    elif choice == "tcp":
        await connect_tcp(app, iface, cfg)
    app.invalidate()


async def pick_channel(app, state, iface) -> None:
    dev = getattr(iface, "iface", None)
    rc = getattr(dev, "radioConfig", None)
    chmap = getattr(rc, "channels", None)

    items: List[Tuple[int, str]] = []
    if isinstance(chmap, dict):
        for i, ch in sorted(chmap.items()):
            name = getattr(getattr(ch, "settings", None), "name", "") or f"ch{i}"
            items.append((int(i), name))

    if not items:
        await _info("Channels", "No channels reported by the device.")
        return

    idx = await _radio("Select Channel", "Choose a primary channel:", items)
    if idx is None:
        return

    try:
        setter = getattr(dev, "setChannel", None)
        if callable(setter):
            setter(idx)
            state.add_log(f"Channel set to {dict(items).get(idx, f'ch{idx}')}")
        else:
            state.add_log("Channel change not supported by this firmware/API")
    except Exception as e:
        state.add_log(f"Channel change failed: {e!r}")
    app.invalidate()

async def connect_port(app, state, iface, cfg):
    mode = await _radio(
        "Connection Type",
        "Choose how to connect:",
        [("serial", "Serial (COM/tty)"), ("tcp", "TCP/IP (hostname[:port])")],
    )
    if mode is None:
        return None
    if mode == "tcp":
        await connect_tcp(app, iface, cfg)
        return getattr(cfg, "last_port", None)

    ports = _available_ports()
    port = None
    if ports:
        sel = await _radio("Connect", "Select serial port:", [(p, p) for p in ports])
        if sel:
            port = sel
    if not port:
        typed = await _ask("Connect", "Enter serial port (e.g., COM5 or /dev/ttyUSB0):")
        if typed is None:
            return None
        port = typed

    baud_choice = await _radio(
        "Baud Rate", "Select baud rate setting:",
        [("auto", "Automatic"), ("manual", "Manual")]
    )
    if baud_choice is None:
        return None
    if baud_choice == "manual":
        baud_rate_str = await _ask("Manual Baud Rate", "Enter baud rate:")
        if baud_rate_str is None:
            return None
        try:
            cfg.baud_rate = int(baud_rate_str) if baud_rate_str else None
        except (ValueError, TypeError):
            cfg.baud_rate = None
    else:
        cfg.baud_rate = None

    try:
        if hasattr(iface, "set_port"):
            iface.set_port(port)
        state.add_log(f"Connecting to {port}")
        _start_iface(iface, port)
        cfg.last_port = port
        cfg.save()
    except Exception as e:
        state.add_log(f"Connect error: {e!r}")
        if not getattr(state, "in_wizard", False):
            await show_connection_error_dialog(app, iface, cfg, port, e)
    app.invalidate()
    return port

async def edit_owner(app, state, iface) -> None:
    dev = getattr(iface, "iface", None)
    curr_long = curr_short = ""
    try:
        info = getattr(dev, "myInfo", None)
        user = getattr(info, "user", None)
        curr_long = getattr(user, "long_name", "") or getattr(user, "longName", "") or ""
        curr_short = getattr(user, "short_name", "") or getattr(user, "shortName", "") or ""
    except Exception:
        pass

    new_long = await _ask("Owner Long Name", f"Current: {curr_long}\nNew value:", curr_long)
    if new_long is None:
        return
    new_short = await _ask("Owner Short Name", f"Current: {curr_short}\nNew value:", curr_short)
    if new_short is None:
        return

    try:
        setter = getattr(dev, "setOwner", None)
        if callable(setter):
            setter(long_name=new_long, short_name=new_short)
            state.add_log("Owner updated")
        else:
            state.add_log("Owner update not supported by this device/API")
    except Exception as e:
        state.add_log(f"Owner update failed: {e!r}")
    app.invalidate()

async def confirm_reboot(app, state, iface) -> None:
    yes = await _confirm("Reboot Device", "Send remote reboot?")
    if not yes:
        return
    try:
        dev = getattr(iface, "iface", None)
        reboot = getattr(dev, "reboot", None)
        if callable(reboot):
            res = reboot()
            if asyncio.iscoroutine(res):
                await res
            state.add_log("Reboot command sent")
        else:
            state.add_log("Reboot not supported")
    except Exception as e:
        state.add_log(f"Reboot failed: {e!r}")
    app.invalidate()

async def setup_wizard(app, state, iface, cfg) -> None:
    state.in_wizard = True
    try:
        tm = ThemeManager()
        names = tm.names()

        theme = await _radio("Meshtui Setup", "Choose a theme:", [(n, n) for n in names])
        if theme is None:
            return
        try:
            cfg.theme = theme
            app.style = ThemeManager(theme).style
            cfg.save()
        except Exception:
            pass
        app.invalidate()

        sel = await connect_port(app, state, iface, cfg)
        if sel is None:
            return

        enable = await _confirm("MQTT", "Enable MQTT integration?")
        cfg.mqtt_enabled = bool(enable)
        if cfg.mqtt_enabled:
            host = await _ask("MQTT Host", f"Host (current: {cfg.mqtt_host}):", str(cfg.mqtt_host or "localhost"))
            if host is None:
                return
            port = await _ask("MQTT Port", f"Port (current: {cfg.mqtt_port}):", str(cfg.mqtt_port or "1883"))
            if port is None:
                return
            tls = await _confirm("MQTT TLS", f"Use TLS? Current: {'on' if cfg.mqtt_tls else 'off'}")
            cfg.mqtt_host = host or cfg.mqtt_host
            try:
                cfg.mqtt_port = int(port) if port else cfg.mqtt_port
            except Exception:
                pass
            cfg.mqtt_tls = bool(tls)

        try:
            cfg.save()
        except Exception:
            pass
        state.add_log("Setup saved")
        app.invalidate()
    finally:
        state.in_wizard = False


def stop(self):
    self._stop.set()
    self._close()
    if self._thr:
        self._thr.join(timeout=3.0)  # was 1.0


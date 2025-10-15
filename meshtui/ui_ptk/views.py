# meshtui/ui_ptk/views.py
import time
from typing import Iterable, List, Tuple, Callable, Any, Optional
from prompt_toolkit.formatted_text import to_formatted_text, StyleAndTextTuples
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.widgets import Label, TextArea, Checkbox, Box
from prompt_toolkit.application import get_app
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.mouse_events import MouseEventType, MouseEvent
from meshtui.themes import ThemeManager
from meshtui.ui_ptk import dialogs
from meshtui.ui_ptk.controls import FlatButtonWindow
from meshtui.model import STATUS_SYMBOL, MsgStatus

# -------- Helpers ---------------------------------------------------------

MouseHandler = Callable[[MouseEvent], Optional[object]]

def _noop_handler(_: MouseEvent) -> object:
    return NotImplemented

def _as_fragment(style: str, text: str, handler: Optional[MouseHandler] = None) -> tuple:
    if callable(handler):
        return (style, text, handler)
    return (style, text)

def _safe_fragments(items: Iterable[Any]) -> StyleAndTextTuples:
    out: List[Tuple] = []
    for it in items:
        if isinstance(it, tuple):
            style = it[0] if len(it) >= 1 and isinstance(it[0], str) else ""
            text = it[1] if len(it) >= 2 and isinstance(it[1], str) else ""
            handler = it[2] if len(it) >= 3 else None
            if callable(handler):
                out.append((style, text, handler))
            else:
                out.append((style, text))
        else:
            out.append(("", "" if it is None else str(it)))
    return to_formatted_text(out)

class SafeFormattedTextControl(FormattedTextControl):
    def __init__(self, text: Callable[[], Iterable[Any]], **kwargs):
        super().__init__(text=lambda: _safe_fragments(text()), **kwargs)

# -------- Formatting ------------------------------------------------------

def format_age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60: return f"{seconds}s"
    if seconds < 3600: return f"{seconds // 60}m"
    if seconds < 86400: return f"{seconds // 3600}h"
    if seconds < 604800: return f"{seconds // 86400}d"
    return f"{seconds // 604800}w"

# -------- Views -----------------------------------------------------------

def combined_list_view(state, iface, on_pick: Optional[Callable[[int], None]] = None) -> Window:
    def _fragments():
        frags: List[Tuple] = []

        def _clear_dm_handler(mouse_event: MouseEvent):
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                state.set_dm(None)
                get_app().invalidate()
                return None  # handled
            return NotImplemented

        is_broadcast_selected = state.dm_target is None
        row_style = "class:list.item.selected" if is_broadcast_selected else "class:row"

        try:
            primary_channel_index = getattr(iface.iface.radioConfig, "primary_channel", 0)
            channel_name = dict(state.channels).get(primary_channel_index, f"CH{primary_channel_index}")
        except Exception:
            channel_name = "CH0"

        frags.append(_as_fragment(row_style, f" [*] Public ({channel_name})\n", _clear_dm_handler))
        frags.append(_as_fragment("", "\n"))

        nodes = getattr(state, "ordered_nodes", lambda: [])()
        if not nodes:
            frags.append(_as_fragment("class:text.muted", "No nodes found."))
        else:
            frags.append(_as_fragment("class:header", " # M SHORT NAME           NUM        AGE \n"))
            for i, n in enumerate(nodes, 1):
                def _node_handler(mouse_event: MouseEvent, _num=n.get("num", 0)):
                    if mouse_event.event_type == MouseEventType.MOUSE_UP:
                        if on_pick: on_pick(_num)
                        get_app().invalidate()
                        return None  # handled
                    return NotImplemented

                short = n.get("short", "?")
                num = n.get("num", 0)
                dm = "M" if n.get("dm") else " "
                age = format_age(time.time() - n.get("last", 0))
                style = "class:list.item.selected" if state.dm_target == num else "class:row"
                frags.append(_as_fragment(style, f"{i:2d} {dm} {short:<18.18} #{num:08x} {age:>4}\n", _node_handler))

        # Trim trailing newline to avoid extra blank line draw issues.
        if frags:
            last = frags[-1]
            if isinstance(last, tuple) and len(last) >= 2 and isinstance(last[1], str) and last[1].endswith("\n"):
                frags[-1] = (last[0], last[1][:-1]) if len(last) == 2 else (last[0], last[1][:-1], last[2])

        return frags

    return Window(
        content=SafeFormattedTextControl(text=_fragments, focusable=True),
        wrap_lines=False,
        right_margins=[ScrollbarMargin(display_arrows=True)],
    )

def log_view(state) -> Window:
    def _text():
        return [("", f" {line}\n") for line in state.log] if state.log else [("", " Log empty.")]
    return Window(
        content=SafeFormattedTextControl(_text),
        wrap_lines=True,
        always_hide_cursor=True,
        height=Dimension(weight=1, min=5),
        right_margins=[ScrollbarMargin(display_arrows=True)],
    )

def chat_view(state) -> Window:
    def _frags():
        to = state.dm_target if state.dm_target is not None else -1
        msgs = state.chats.get(to, [])
        if not msgs:
            return [("", " (No messages)\n")]
        out: List[Tuple] = []
        for m in msgs:
            sym = STATUS_SYMBOL.get(m.status, "?")
            style = {
                MsgStatus.PENDING: "class:msg.pending",
                MsgStatus.SENT: "class:msg.sent",
                MsgStatus.RETRYING: "class:msg.retry",
                MsgStatus.ACKED: "class:msg.acked",
                MsgStatus.FAILED: "class:msg.failed",
            }.get(m.status, "")
            out.append((style, f"{sym} "))
            out.append(("class:msg.body", m.text))
            out.append(("", "\n"))
        return out
    return Window(
        content=SafeFormattedTextControl(_frags),
        wrap_lines=True,
        always_hide_cursor=True,
        height=Dimension(weight=3, min=8),
        right_margins=[ScrollbarMargin(display_arrows=True)],
    )

def settings_view(state, iface, cfg) -> Box:
    tm = ThemeManager(cfg.theme)
    port_input = TextArea(text=str(cfg.last_port or ""), height=1, multiline=False)
    mqtt_host = TextArea(text=str(cfg.mqtt_host or "localhost"), height=1, multiline=False)
    mqtt_port = TextArea(text=str(cfg.mqtt_port or 1883), height=1, multiline=False)
    mqtt_on = Checkbox(text="Enable MQTT", checked=bool(cfg.mqtt_enabled))
    mqtt_tls = Checkbox(text="Use TLS", checked=bool(cfg.mqtt_tls))
    theme_box = TextArea(text=tm.name, height=1, multiline=False, read_only=True)

    def _select_port():
        async def _coro():
            port = await dialogs.connect_port(get_app(), state, iface, cfg)
            if port:
                port_input.text = port
        get_app().create_background_task(_coro())

    def do_save():
        try:
            cfg.last_port = port_input.text.strip() or None
            cfg.mqtt_host = mqtt_host.text.strip() or "localhost"
            try:
                cfg.mqtt_port = int(mqtt_port.text.strip())
            except Exception:
                pass
            cfg.mqtt_enabled = bool(mqtt_on.checked)
            cfg.mqtt_tls = bool(mqtt_tls.checked)
            cfg.theme = theme_box.text.strip() or None
            cfg.save()
            state.add_log("[settings] saved")
        except Exception as e:
            state.add_log(f"[settings] save error: {e}")

    def cycle_theme(direction: int):
        if direction > 0:
            tm.cycle_next()
        else:
            for _ in range(len(tm.names()) - 1):
                tm.cycle_next()
        theme_box.text = tm.name
        app = get_app()
        app.style = tm.style
        app.invalidate()

    form = HSplit([
        Label("Serial Port"),
        VSplit([port_input, FlatButtonWindow("Select Port", _select_port)], padding=1),
        Label("MQTT Host"), mqtt_host,
        Label("MQTT Port"), mqtt_port,
        VSplit([mqtt_on, mqtt_tls], padding=2),
        Label("Theme"),
        VSplit([
            FlatButtonWindow("-", lambda: cycle_theme(-1)),
            theme_box,
            FlatButtonWindow("+", lambda: cycle_theme(1)),
        ], padding=1, width=Dimension(weight=1)),
        Label("Device Settings"),
        VSplit([
            FlatButtonWindow("Edit Owner",
                             lambda: get_app().create_background_task(dialogs.edit_owner(get_app(), state, iface))),
            FlatButtonWindow("Reboot",
                             lambda: get_app().create_background_task(dialogs.confirm_reboot(get_app(), state, iface))),
        ], padding=1),
        VSplit([FlatButtonWindow("Save Settings", do_save)], padding=1),
        VSplit([FlatButtonWindow("Run Setup Wizard",
                                 lambda: get_app().create_background_task(
                                     dialogs.setup_wizard(get_app(), state, iface, cfg)))], padding=1),
    ], padding=1)

    return Box(body=form, padding=1)

# meshtui/ui_ptk/views.py
import time
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window, HSplit, VSplit
from prompt_toolkit.widgets import Label, TextArea, Checkbox, Box
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.application import get_app
from prompt_toolkit.layout.dimension import Dimension
from meshtui.themes import ThemeManager
from meshtui.ui_ptk import dialogs
from meshtui.ui_ptk.controls import FlatButtonWindow

def combined_list_view(state, iface, on_pick=None):
    def _fragments():
        frags = []
        app = get_app()

        def _get_primary_channel():
            try:
                idx = iface.iface.radioConfig.primary_channel
                name = dict(state.channels).get(idx, f"CH{idx}")
                return name
            except Exception:
                return "CH0"

        # Handler for clearing DM target
        def _clear_dm_handler(mouse_event):
            state.set_dm(None)
            app.invalidate()

        # Add broadcast/public channel item
        is_broadcast_selected = state.dm_target is None
        broadcast_style = "class:list.item.selected" if is_broadcast_selected else "class:row"
        channel_name = _get_primary_channel()
        frags.append((broadcast_style, f" [*] Public ({channel_name})\n", _clear_dm_handler))

        frags.append(("", "\n"))

        # Add Channels
        if state.channels:
            frags.append(("class:header", "CHANNELS\n"))
            primary_channel_index = getattr(getattr(iface.iface, "radioConfig", None), "primary_channel", 0)

            for i, name in state.channels:
                is_primary = (i == primary_channel_index)
                marker = "[*]" if is_primary else "[ ]"
                line = f" {marker} {name}"

                def _set_channel_handler(mouse_event, channel_index=i, channel_name=name):
                    try:
                        dev = getattr(iface, "iface", None)
                        setter = getattr(dev, "setChannel", None)
                        if callable(setter):
                            setter(channel_index)
                            state.add_log(f"Primary channel set to {channel_name}")
                            iface.iface.radioConfig.primary_channel = channel_index
                    except Exception as e:
                        state.add_log(f"Failed to set channel: {e}")
                    app.invalidate()

                frags.append(("class:row", f"{line}\n", _set_channel_handler))
            frags.append(("", "\n"))

        # Add Nodes
        nodes = state.ordered_nodes()
        if not nodes:
            frags.append(("", "No nodes detected."))
        else:
            frags.append(("class:header", "NODES\n"))
            frags.append(("class:header", " # M ENC CH SHORT      NUM        AGE \n"))
            for i, n in enumerate(nodes, 1):
                m = "M" if n.get("dm") else " "
                meta = n.get("meta") or {}
                enc = "🔒" if meta.get("encrypted") else " "
                ch = str(meta.get("channel")) if meta.get("channel") is not None else "-"
                short = f"{n.get('short',''):<10.10}"
                num = f"#{n.get('num', 0):08x}"
                age = f"{int(time.time() - n.get('last', 0))}s"
                line = f"{i:>2} {m}  {enc}  {ch:<2} {short} {num} {age:>4}"

                def _node_handler(mouse_event, _num=n["num"]):
                    if on_pick:
                        on_pick(_num)
                    app.invalidate()

                frags.append(("class:row", f"{line}\n", _node_handler))

        if frags and frags[-1][1] == "\n":
            frags.pop()
        return frags

    ctrl = FormattedTextControl(_fragments, focusable=True)
    return Window(content=ctrl, wrap_lines=False, always_hide_cursor=True)


def log_view(state):
    def _text():
        return "\n".join(f" {line}" for line in state.log) if state.log else " Log empty."
    return Window(content=FormattedTextControl(_text), wrap_lines=True, always_hide_cursor=True)

def chat_view(state):
    def _text():
        key = state.dm_target if state.dm_target is not None else -1
        msgs = state.chats.get(key, [])
        return "\n".join(f" {line}" for line in msgs) if msgs else " (No messages)"

    return Window(
        content=FormattedTextControl(_text),
        wrap_lines=True,
        always_hide_cursor=True,
    )

def settings_view(state, iface, cfg):
    tm = ThemeManager(cfg.theme)

    port_input = TextArea(text=str(cfg.last_port or ""), height=1, multiline=False)
    mqtt_host = TextArea(text=str(cfg.mqtt_host or "localhost"), height=1, multiline=False)
    mqtt_port = TextArea(text=str(cfg.mqtt_port or 1883), height=1, multiline=False)
    mqtt_on   = Checkbox(text="Enable MQTT", checked=bool(cfg.mqtt_enabled))
    mqtt_tls  = Checkbox(text="Use TLS", checked=bool(cfg.mqtt_tls))
    theme_box = TextArea(text=tm.name, height=1, multiline=False, read_only=True)

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

    def do_connect():
        try:
            p = port_input.text.strip()
            if p:
                iface.set_port(p)
                iface.start()
        except Exception as e:
            state.add_log(f"[connect] {e}")

    def cycle_theme(direction):
        if direction > 0:
            tm.cycle_next()
        else:
            for _ in range(len(tm.names()) - 1):
                tm.cycle_next()
        theme_box.text = tm.name
        app = get_app()
        app.style = tm.style
        app.invalidate()

    form = HSplit(
        [
            Label("Serial Port"),
            port_input,
            VSplit([FlatButtonWindow("Connect", do_connect), FlatButtonWindow("Save", do_save)], padding=1),
            Label("MQTT Host"),
            mqtt_host,
            Label("MQTT Port"),
            mqtt_port,
            VSplit([mqtt_on, mqtt_tls], padding=2),
            Label("Theme"),
            VSplit([
                FlatButtonWindow("-", lambda: cycle_theme(-1)),
                theme_box,
                FlatButtonWindow("-", lambda: cycle_theme(1)),
            ], padding=1, width=Dimension(weight=1)),
            Label("Device Settings"),
            VSplit([
                FlatButtonWindow("Edit Owner", lambda: get_app().create_background_task(dialogs.edit_owner(get_app(), state, iface))),
                FlatButtonWindow("Reboot", lambda: get_app().create_background_task(dialogs.confirm_reboot(get_app(), state, iface))),
            ], padding=1),
        ],
        padding=1,
    )

    boxed = Box(body=form, padding=1)
    return HSplit([boxed])
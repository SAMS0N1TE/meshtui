# meshtui/ui_ptk/app.py
import asyncio
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea, Label
from prompt_toolkit.styles import Style

def build_app(state, bus, actions, iface):
    def nodes_text():
        lines = []
        nodes = state.ordered_nodes()
        if not nodes:
            return "No nodes."
        for i, n in enumerate(nodes, 1):
            tag = "[M] " if n["dm"] else ""
            lines.append(f"{i:2d}. {tag}{n['short']}  #{n['num']}  last={int(n['last'])}")
        return "\n".join(lines)

    def log_text():
        return "\n".join(state.log) if state.log else "Log empty."

    nodes_ctl = FormattedTextControl(nodes_text)
    log_ctl = FormattedTextControl(log_text)
    nodes_win = Window(content=nodes_ctl, wrap_lines=False, always_hide_cursor=True)
    log_win = Window(content=log_ctl, wrap_lines=False, always_hide_cursor=True)
    input_box = TextArea(height=1, prompt="> ", multiline=False)
    status = Label(text="F2 DM select | F3 Clear DM | Enter Send | Ctrl-C Quit")

    kb = KeyBindings()

    @kb.add("c-c")
    def _(event):
        event.app.exit()

    @kb.add("enter")
    def _(event):
        text = input_box.text.strip()
        if text:
            actions.send_text(state, iface, bus, text)
            input_box.buffer.reset()
            event.app.invalidate()

    @kb.add("f2")
    def _(event):
        nodes = state.ordered_nodes()
        if not nodes:
            state.add_log("No nodes to select.")
            return
        state.set_dm(nodes[0]["num"])
        state.add_log(f"DM target set to #{nodes[0]['num']}")
        event.app.invalidate()

    @kb.add("f3")
    def _(event):
        state.set_dm(None)
        state.add_log("DM cleared")
        event.app.invalidate()

    root = HSplit([
        VSplit([
            HSplit([Label(text="Nodes"), nodes_win]),
            HSplit([Label(text="Log"), log_win]),
        ]),
        status,
        input_box,
    ])

    style = Style.from_dict({"label": "bold"})

    app = Application(
        layout=Layout(root, focused_element=input_box),
        key_bindings=kb,
        mouse_support=True,
        full_screen=True,
        style=style,
        refresh_interval=0.1,
    )
    return app

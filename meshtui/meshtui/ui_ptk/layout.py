# meshtui/ui_ptk/layout.py
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, VSplit
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.filters import Condition
from prompt_toolkit.widgets import Label, Frame, TextArea, Box

from meshtui.ui_ptk.views import combined_list_view, log_view, chat_view, settings_view
from meshtui.ui_ptk.bind import build_keybindings
from meshtui.ui_ptk.status import status_view
from meshtui.ui_ptk.map import build_map
from meshtui.ui_ptk.widgets import v_splitter, h_splitter
from meshtui.ui_ptk.controls import FlatButtonWindow
from meshtui.themes import ThemeManager


def build_layout(state, actions, iface, bus, initial_theme: str | None = None, cfg=None):
    theme = ThemeManager(initial_theme)

    left_ratio = {"v": (cfg.split_left if cfg else 0.60)}
    nodes_ratio = {"v": (cfg.split_nodes_log if cfg else 0.85)}
    bottom_tab = {"v": (cfg.last_tab if cfg and cfg.last_tab in ("Log", "Map", "Settings") else "Log")}

    input_box = TextArea(height=1, prompt="> ", multiline=False, style="class:text-area")
    kb = build_keybindings(state, actions, iface, bus, input_box)

    def on_pick_dm(num: int):
        state.set_dm(num)

    nodes_frame = Frame(combined_list_view(state, iface, on_pick=on_pick_dm), title="Nodes & Channels", style="class:frame")
    log_frame = Frame(log_view(state), title="Log", style="class:frame")
    map_frame = Frame(build_map(state), title="Map", style="class:frame")
    settings_frame = Frame(settings_view(state, iface, cfg), title="Settings", style="class:frame")

    tabs_bar = VSplit(
        [
            FlatButtonWindow("Log",      lambda: bottom_tab.__setitem__("v", "Log")),
            FlatButtonWindow("Map",      lambda: bottom_tab.__setitem__("v", "Map")),
            FlatButtonWindow("Settings", lambda: bottom_tab.__setitem__("v", "Settings")),
        ],
        padding=0,
        height=Dimension.exact(1),
    )

    bottom_stack = HSplit(
        [
            tabs_bar,
            ConditionalContainer(log_frame,      filter=Condition(lambda: bottom_tab["v"] == "Log")),
            ConditionalContainer(map_frame,      filter=Condition(lambda: bottom_tab["v"] == "Map")),
            ConditionalContainer(settings_frame, filter=Condition(lambda: bottom_tab["v"] == "Settings")),
        ]
    )

    left_column = HSplit([
        nodes_frame,
        h_splitter(lambda: nodes_ratio["v"], lambda r: nodes_ratio.__setitem__("v", r)),
        bottom_stack,
    ])

    chat_frame = Frame(chat_view(state), title="Chat", style="class:frame")

    header = Label("Meshtastic TUI", style="class:header")
    status = status_view(state, theme_name_provider=lambda: theme.name)

    left_box = Box(
        body=left_column,
        padding=0
    )
    chat_box = Box(
        body=chat_frame,
        padding=0
    )

    center = VSplit([
        left_box,
        v_splitter(lambda: left_ratio["v"], lambda r: left_ratio.__setitem__("v", r)),
        chat_box,
    ])

    def _container():
        lw = max(1, int(left_ratio["v"] * 100))
        rw = max(1, 100 - lw)
        nh = max(1, int(nodes_ratio["v"] * 100))
        lh = max(1, 100 - nh)

        nodes_frame.height = Dimension(weight=nh, min=4)
        bottom_stack.height = Dimension(weight=lh, min=8)

        left_box.width = Dimension(weight=lw)
        chat_box.width = Dimension(weight=rw)

        return HSplit([header, center, status, input_box])

    app = Application(
        layout=Layout(_container(), focused_element=input_box),
        key_bindings=kb,
        mouse_support=True,
        full_screen=True,
        style=theme.style,
        refresh_interval=0.1,
    )

    @kb.add("f6")
    def _(event):
        theme.cycle_next()
        app.style = theme.style
        app.invalidate()

    def _persist():
        if cfg:
            cfg.split_left = float(left_ratio["v"])
            cfg.split_nodes_log = float(nodes_ratio["v"])
            cfg.last_tab = bottom_tab["v"]
            try:
                cfg.save()
            except Exception:
                pass

    app.after_render += lambda _: _persist()
    return app

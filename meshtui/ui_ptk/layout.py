# meshtui/ui_ptk/layout.py
from prompt_toolkit.application import Application, get_app
from prompt_toolkit.layout import Layout, HSplit, VSplit
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.widgets import Label, Frame, TextArea, Box
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings

from meshtui.ui_ptk.views import combined_list_view, log_view, chat_view, settings_view
from meshtui.ui_ptk.bind import build_keybindings
from meshtui.ui_ptk.status import status_view
from meshtui.ui_ptk.map import build_map
from meshtui.ui_ptk.widgets import v_splitter, h_splitter
from meshtui.ui_ptk.controls import FlatButtonWindow
from meshtui.themes import ThemeManager


def build_layout(state, actions, iface, bus, initial_theme: str | None = None, cfg=None):
    theme = ThemeManager(initial_theme)

    bottom_tab = {"v": (cfg.last_tab if cfg and cfg.last_tab in ("Log", "Map", "Settings") else "Log")}

    input_box = TextArea(height=1, prompt="> ", multiline=False, style="class:text-area")
    main_kb = build_keybindings(state, actions, iface, bus, input_box)

    def on_pick_dm(num: int):
        state.set_dm(num)

    nodes_window = combined_list_view(state, iface, on_pick=on_pick_dm)
    nodes_frame = Frame(nodes_window, title="Nodes & Channels", style='class:frame')
    focused_nodes_frame = Frame(nodes_window, title="Nodes & Channels", style='class:frame.focused')

    scroll_kb = KeyBindings()
    is_nodes_window_focused = has_focus(nodes_window)

    def _clamp(v):
        return max(0, int(v))

    @scroll_kb.add("up", filter=is_nodes_window_focused)
    def _(event):
        nodes_window.vertical_scroll = _clamp(nodes_window.vertical_scroll - 1)
        event.app.invalidate()

    @scroll_kb.add("down", filter=is_nodes_window_focused)
    def _(event):
        nodes_window.vertical_scroll = _clamp(nodes_window.vertical_scroll + 1)
        event.app.invalidate()

    @main_kb.add("tab")
    def _(event):
        event.app.layout.focus_next()

    @main_kb.add("s-tab")
    def _(event):
        event.app.layout.focus_previous()


    log_frame = Frame(log_view(state), title="Log", style="class:frame")
    map_frame = Frame(build_map(state), title="Map", style="class:frame")
    settings_frame = Frame(settings_view(state, iface, cfg), title="Settings", style="class:frame")

    tabs_bar = VSplit([
        FlatButtonWindow("Log", lambda: bottom_tab.__setitem__("v", "Log")),
        FlatButtonWindow("Map", lambda: bottom_tab.__setitem__("v", "Map")),
        FlatButtonWindow("Settings", lambda: bottom_tab.__setitem__("v", "Settings")),
    ], padding=1, height=1)

    bottom_stack = HSplit([
        tabs_bar,
        ConditionalContainer(log_frame, filter=Condition(lambda: bottom_tab["v"] == "Log")),
        ConditionalContainer(map_frame, filter=Condition(lambda: bottom_tab["v"] == "Map")),
        ConditionalContainer(settings_frame, filter=Condition(lambda: bottom_tab["v"] == "Settings")),
    ])

    left_column = HSplit([
        ConditionalContainer(focused_nodes_frame, filter=has_focus(nodes_window)),
        ConditionalContainer(nodes_frame, filter=~has_focus(nodes_window)),
        bottom_stack,
    ], width=50)
    # Set the height of the nodes_frame to be a fraction of the total height, with a minimum
    nodes_frame.height = Dimension(weight=0.6, min=6)
    focused_nodes_frame.height = Dimension(weight=0.6, min=6)

    chat_frame = Frame(chat_view(state), title="Chat", style="class:frame")
    header = Label("Meshtastic TUI", style="class:header")
    status = status_view(state, theme_name_provider=lambda: theme.name)

    # Main layout using a VSplit for the two columns
    main_view = VSplit([
        # Left column
        left_column,
        # Right column
        chat_frame
    ])


    # The root container
    root_container = HSplit([
        header,
        main_view,
        status,
        input_box
    ])

    merged_kb = merge_key_bindings([main_kb, scroll_kb])

    app = Application(
        layout=Layout(root_container, focused_element=input_box),
        key_bindings=merged_kb,
        mouse_support=True,
        full_screen=True,
        style=theme.style,
        refresh_interval=0.1,
    )

    @main_kb.add("f6")
    def _(event):
        theme.cycle_next()
        app.style = theme.style
        app.invalidate()

    def _persist():
        if cfg:
            # Removed splitter persistence
            cfg.last_tab = bottom_tab["v"]
            try:
                cfg.save()
            except Exception:
                pass

    app.after_render += lambda _: _persist()
    return app
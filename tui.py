# goog/tui.py

import time
import logging
import queue
import datetime
from serial.tools import list_ports
import meshtastic

from prompt_toolkit import Application
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, ConditionalContainer, AnyContainer, FloatContainer, \
    Float, WindowAlign
from prompt_toolkit.layout.scrollable_pane import ScrollablePane
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import Frame, TextArea, Label
from prompt_toolkit.styles import Style, DynamicStyle
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.formatted_text import ANSI

from app_state import AppState, TuiState, Panel, Event


class ButtonControl(FormattedTextControl):
    def __init__(self, text, on_click):
        self._text = text
        self.handler = on_click
        super().__init__(text=self._get_text, focusable=True)

    def _get_text(self):
        return [("class:button", f" {self._text} ")]

    def mouse_handler(self, mouse_event):
        if mouse_event.event_type == MouseEventType.MOUSE_UP:
            self.handler()
            return None
        return NotImplemented


def get_time_ago(timestamp):
    if not timestamp or timestamp == 0: return "never"
    try:
        delta = datetime.datetime.now() - datetime.datetime.fromtimestamp(timestamp)
        if delta.days > 0: return f"{delta.days}d ago"
        if delta.seconds > 3600: return f"{delta.seconds // 3600}h ago"
        if delta.seconds > 60: return f"{delta.seconds // 60}m ago"
        return f"{delta.seconds}s ago"
    except (TypeError, ValueError):
        return "invalid"


class NodesControl(FormattedTextControl):
    def __init__(self, tui_instance, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tui = tui_instance

    def mouse_handler(self, mouse_event):
        if mouse_event.event_type == MouseEventType.MOUSE_UP:
            line_index = mouse_event.position.y
            node_list = self.tui.state.get_node_list()
            if line_index < len(node_list):
                self.tui.state.nodes_selected_line = line_index
                if self.tui.state.tui_state == TuiState.CHAT:
                    selected_node = node_list[line_index]
                    self.tui.state.dm_target_id = selected_node.get('id')
                    self.tui.state.active_panel = Panel.INPUT
                    self.tui.app.layout.focus(self.tui.input_field)
            return None
        return NotImplemented


class SettingsControl(FormattedTextControl):
    def __init__(self, tui_instance, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tui = tui_instance

    def mouse_handler(self, mouse_event):
        if mouse_event.event_type == MouseEventType.MOUSE_UP:
            line_index = mouse_event.position.y - 2
            if 0 <= line_index < len(self.tui.state.available_ports):
                self.tui.state.settings_selected_line = line_index
                port_device = self.tui.state.available_ports[line_index].device
                self.tui.command_queue.put((Event.SET_PORT, port_device))
                self.tui.state.tui_state = TuiState.CHAT
                self.tui.app.layout.focus(self.tui.input_field)
            return None
        return NotImplemented


class MeshtasticTUI:
    def __init__(self, state: AppState, command_queue: queue.Queue, update_queue: queue.Queue):
        logging.info("Initializing TUI.")
        self.state = state
        self.command_queue = command_queue
        self.update_queue = update_queue
        self.app_is_running = True
        self._create_ui_elements()
        self.app = self._create_application()

    def _create_ui_elements(self):
        self.chat_control = FormattedTextControl(text=[], focusable=False)
        self.nodes_control = NodesControl(
            self, text=[], focusable=True,
            get_cursor_position=lambda: Point(x=0, y=self.state.nodes_selected_line)
        )
        self.status_control = FormattedTextControl(text=[], focusable=False)
        self.settings_control = SettingsControl(
            self, text=[], focusable=True,
            get_cursor_position=lambda: Point(x=0, y=self.state.settings_selected_line + 2)
        )
        self.map_control = FormattedTextControl(text=[], focusable=False)
        self.input_field = TextArea(height=1, multiline=False, wrap_lines=False, prompt=">> ")

        # Map Buttons
        self.zoom_in_button = ButtonControl("[ + Zoom In ]", lambda: self.update_queue.put((Event.MAP_ZOOM_IN, None)))
        self.zoom_out_button = ButtonControl("[ - Zoom Out]", lambda: self.update_queue.put((Event.MAP_ZOOM_OUT, None)))

        def center_on_selection():
            node_list = self.state.get_node_list()
            if self.state.nodes_selected_line < len(node_list):
                node_id = node_list[self.state.nodes_selected_line].get('id')
                self.update_queue.put((Event.MAP_CENTER_ON_NODE, node_id))

        self.center_button = ButtonControl("[ Center on Selection ]", center_on_selection)
        self.recenter_all_button = ButtonControl("[ Recenter All ]",
                                                 lambda: self.update_queue.put((Event.MAP_RECENTER, None)))
        self.pan_up_button = ButtonControl("  ^ (W)  ", lambda: self.update_queue.put((Event.MAP_MOVE_CURSOR_UP, None)))
        self.pan_down_button = ButtonControl("  v (S)  ",
                                             lambda: self.update_queue.put((Event.MAP_MOVE_CURSOR_DOWN, None)))
        self.pan_left_button = ButtonControl("< (A)", lambda: self.update_queue.put((Event.MAP_MOVE_CURSOR_LEFT, None)))
        self.pan_right_button = ButtonControl("(D) >",
                                              lambda: self.update_queue.put((Event.MAP_MOVE_CURSOR_RIGHT, None)))
        self.charset_button = ButtonControl("[ Cycle Charset (F9) ]",
                                            lambda: self.update_queue.put((Event.MAP_CYCLE_CHARSET, None)))

        self.map_info_control = FormattedTextControl(text=[], focusable=False)

    def _create_application(self):
        root_container = HSplit([
            Label(text=" Meshtastic TUI - F6:Theme | F7:Map | F8:Settings | F9:Charset | Ctrl+C:Quit",
                  style="class:header"),
            ConditionalContainer(content=self._create_chat_layout(),
                                 filter=Condition(lambda: self.state.tui_state == TuiState.CHAT)),
            ConditionalContainer(content=self._create_settings_layout(),
                                 filter=Condition(lambda: self.state.tui_state == TuiState.SETTINGS)),
            ConditionalContainer(content=self._create_map_layout(),
                                 filter=Condition(lambda: self.state.tui_state == TuiState.MAP)),
        ])
        dynamic_style = DynamicStyle(lambda: Style.from_dict(self.state.get_current_theme()))
        return Application(layout=Layout(root_container, focused_element=self.settings_control),
                           key_bindings=self._get_key_bindings(),
                           full_screen=True, style=dynamic_style, before_render=self._before_render, mouse_support=True)

    def _create_chat_layout(self):
        nodes_pane = ScrollablePane(Window(self.nodes_control, always_hide_cursor=True))
        return HSplit([
            VSplit([Frame(title=self._get_chat_title, body=Window(self.chat_control, wrap_lines=True)),
                    Frame(title=self._get_nodes_title, body=nodes_pane, width=40)]),
            Window(height=1, content=self.status_control, style="class:statusbar"),
            Frame(title=self._get_input_title, body=self.input_field, height=3)])

    def _create_settings_layout(self):
        settings_pane = ScrollablePane(Window(self.settings_control, always_hide_cursor=True))
        return HSplit([Frame(title="Settings: Select a Port", body=settings_pane),
                       Label(text="Use UP/DOWN arrows or Click to select. F8 to return to chat.")])

    def _create_map_layout(self):
        nodes_pane = Frame(
            title="Nodes",
            body=ScrollablePane(Window(self.nodes_control, always_hide_cursor=True)),
            width=30
        )
        map_window = Window(
            self.map_control,
            width=70,
            height=22,
            dont_extend_width=True,
            dont_extend_height=True
        )
        map_pane = Frame(title="Map (WASD to move cursor, Enter to center)", body=map_window)

        d_pad = HSplit([
            Window(content=self.pan_up_button, height=1, align=WindowAlign.CENTER),
            VSplit([
                Window(content=self.pan_left_button),
                Window(content=self.pan_right_button),
            ], height=1, align=WindowAlign.CENTER),
            Window(content=self.pan_down_button, height=1, align=WindowAlign.CENTER),
        ])

        controls_pane = Frame(
            title="Controls",
            body=HSplit([
                Window(height=1, content=self.zoom_in_button),
                Window(height=1, content=self.zoom_out_button),
                Window(height=1, content=self.center_button),
                Window(height=1, content=self.recenter_all_button),
                Window(height=1, content=self.charset_button),
                Frame(title="Move Cursor", body=d_pad),
                Frame(title="Info", body=Window(self.map_info_control, height=5)),
            ]),
            width=28
        )
        return VSplit([nodes_pane, map_pane, controls_pane])

    def _get_key_bindings(self):
        kb = KeyBindings()

        @kb.add("c-c", eager=True)
        @kb.add("c-q", eager=True)
        def _(event):
            self.app_is_running = False
            self.command_queue.put((Event.TUI_EXIT, None))
            event.app.exit()

        @kb.add("f6")
        def _(event):
            self.state.cycle_theme()

        @kb.add("f7")
        def _(event):
            self.update_queue.put((Event.TOGGLE_MAP, None))

        @kb.add("f8")
        def _(event):
            if self.state.tui_state == TuiState.SETTINGS:
                self.state.tui_state = TuiState.CHAT
                event.app.layout.focus(self.input_field)
            else:
                self.state.tui_state = TuiState.SETTINGS
                event.app.layout.focus(self.settings_control)

        @kb.add("f9")
        def _(event):
            self.update_queue.put((Event.MAP_CYCLE_CHARSET, None))

        is_chat = Condition(lambda: self.state.tui_state == TuiState.CHAT)
        is_input = Condition(lambda: self.state.active_panel == Panel.INPUT and is_chat())
        is_nodes = Condition(lambda: self.state.active_panel == Panel.NODES and is_chat())
        is_map = Condition(lambda: self.state.tui_state == TuiState.MAP)

        @kb.add("w", filter=is_map)
        def _(event):
            self.update_queue.put((Event.MAP_MOVE_CURSOR_UP, None))

        @kb.add("s", filter=is_map)
        def _(event):
            self.update_queue.put((Event.MAP_MOVE_CURSOR_DOWN, None))

        @kb.add("a", filter=is_map)
        def _(event):
            self.update_queue.put((Event.MAP_MOVE_CURSOR_LEFT, None))

        @kb.add("d", filter=is_map)
        def _(event):
            self.update_queue.put((Event.MAP_MOVE_CURSOR_RIGHT, None))

        @kb.add("enter", filter=is_map)
        def _(event):
            self.update_queue.put((Event.MAP_CENTER_ON_CURSOR, None))

        @kb.add("tab", filter=is_chat)
        def _(event):
            self.state.active_panel = Panel.NODES if self.state.active_panel == Panel.INPUT else Panel.INPUT
            event.app.layout.focus(self.nodes_control if self.state.active_panel == Panel.NODES else self.input_field)

        @kb.add("enter", filter=is_input)
        def _(event):
            text = self.input_field.text.strip()
            if text:
                destination_id = self.state.dm_target_id if self.state.dm_target_id else meshtastic.BROADCAST_NUM
                self.command_queue.put((Event.SEND_TEXT, (text, destination_id)))
                self.input_field.text = ""

        @kb.add("escape", filter=is_chat)
        def _(event):
            self.state.dm_target_id = None; self.state.active_panel = Panel.INPUT; event.app.layout.focus(
                self.input_field)

        @kb.add("f5", filter=is_nodes)
        def _(event):
            node_list = self.state.get_node_list()
            if self.state.nodes_selected_line < len(node_list):
                selected_node_id = node_list[self.state.nodes_selected_line].get('id')
                if selected_node_id: self.command_queue.put((Event.SEND_TRACEROUTE, selected_node_id))

        @kb.add("up", filter=is_nodes | is_map)
        def _(event):
            self.state.nodes_selected_line = max(0, self.state.nodes_selected_line - 1)

        @kb.add("down", filter=is_nodes | is_map)
        def _(event):
            self.state.nodes_selected_line = min(len(self.state.get_node_list()) - 1,
                                                 self.state.nodes_selected_line + 1)

        @kb.add("enter", filter=is_nodes)
        def _(event):
            node_list = self.state.get_node_list()
            if self.state.nodes_selected_line < len(node_list):
                self.state.dm_target_id = node_list[self.state.nodes_selected_line]['id']
                self.state.active_panel = Panel.INPUT;
                event.app.layout.focus(self.input_field)

        is_settings = Condition(lambda: self.state.tui_state == TuiState.SETTINGS)

        @kb.add("up", filter=is_settings)
        def _(event):
            self.state.settings_selected_line = max(0, self.state.settings_selected_line - 1)

        @kb.add("down", filter=is_settings)
        def _(event):
            if self.state.available_ports: self.state.settings_selected_line = min(len(self.state.available_ports) - 1,
                                                                                   self.state.settings_selected_line + 1)

        @kb.add("enter", filter=is_settings)
        def _(event):
            if self.state.settings_selected_line < len(self.state.available_ports):
                port = self.state.available_ports[self.state.settings_selected_line].device
                self.command_queue.put((Event.SET_PORT, port))
                self.state.tui_state = TuiState.CHAT;
                event.app.layout.focus(self.input_field)

        return kb

    def _get_chat_title(self):
        return f" DM: {self.state.get_dm_target_name()} " if self.state.dm_target_id else " Broadcast (All) "

    def _get_nodes_title(self):
        return [("", " "),
                (f"class:frame.label{' reverse' if self.state.active_panel == Panel.NODES else ''}", "Nodes"),
                ("", " ")]

    def _get_input_title(self):
        return [("", " "),
                (f"class:frame.label{' reverse' if self.state.active_panel == Panel.INPUT else ''}", "Input"),
                ("", " ")]

    def _handle_events(self):
        while True:
            try:
                event, data = self.update_queue.get_nowait(); self.state.process_event(event, data)
            except queue.Empty:
                break

    def _update_ui_text(self):
        try:
            if self.state.tui_state == TuiState.CHAT:
                messages = self.state.get_current_messages()
                chat_fragments = []
                for msg in messages:
                    status_map = {'SENDING': '[?]', 'DELIVERED': '[✓]', 'FAILED': '[X]'}
                    sender_id = msg['sender_id']
                    if sender_id == self.state.my_node_num:
                        sender_name = "You"
                    elif isinstance(sender_id, int):
                        sender_name = self.state.nodes.get(sender_id, {}).get('name', f"!{sender_id:x}")
                    else:
                        sender_name = str(sender_id)
                    style = "class:message.local" if sender_name == "You" else (
                        "class:message.dm" if msg['is_dm'] else "class:message.remote")
                    if msg['status'] == 'SYSTEM': style = 'class:message.error'
                    status_indicator = status_map.get(msg['status'], '')
                    chat_fragments.append(
                        (style, f"[{msg['timestamp']}] <{sender_name}> {status_indicator} {msg['text']}\n"))
                self.chat_control.text = chat_fragments

            node_fragments = []
            for i, node in enumerate(self.state.get_node_list()):
                is_selected = i == self.state.nodes_selected_line
                style = "class:list.item.selected" if is_selected else ""
                prefix = "> " if is_selected else "  "
                if node['id'] is None: node_fragments.append((style, f"{prefix}{node['name']}\n")); continue
                notif = "* " if node.get('id') in self.state.unread_dm_senders else ""
                name = node.get('name', 'N/A')[:16];
                snr_val = node.get('snr');
                ago = get_time_ago(node.get('lastHeard'))
                snr_str = f"{snr_val:.1f}" if isinstance(snr_val, (int, float)) else str(snr_val)
                map_button = " [M]" if node.get('latitude') else "    "
                node_fragments.append((style, f"{prefix}{notif}{name:<16} {snr_str:>4}db {ago:>8}{map_button}\n"))
            self.nodes_control.text = node_fragments

            if self.state.tui_state == TuiState.MAP:
                self.map_control.text = self.state.get_ascii_map()
                lat = self.state.map_center_lat or 0
                lon = self.state.map_center_lon or 0
                zoom = self.state.map_zoom or 'N/A'
                char_set_name, _ = self.state.map_char_sets[self.state.map_char_set_index]
                self.map_info_control.text = f"Lat: {lat:.4f}\nLon: {lon:.4f}\nZoom: {zoom}\nCharset: {char_set_name}"

            status_color = "bold" if self.state.is_connected else "class:message.error"
            self.status_control.text = [(status_color, f" {self.state.connection_status} "), ("",
                                                                                              f" {self.state.connection_details} | Theme: {self.state.get_current_theme_name()}")]

            self.state.available_ports = list_ports.comports()
            settings_fragments = [("", "Detected Serial Ports:\n\n")]
            if not self.state.available_ports:
                settings_fragments.append(("", "  No serial ports found."))
            else:
                for i, port in enumerate(self.state.available_ports):
                    style = "class:list.item.selected" if i == self.state.settings_selected_line else ""
                    settings_fragments.append((style, f" {port.device}: {port.description}\n"))
            self.settings_control.text = settings_fragments
        except Exception as e:
            logging.error(f"Error during UI update: {e}", exc_info=True)

    def _before_render(self, app):
        self._handle_events(); self._update_ui_text()

    def run(self):
        try:
            self.app.run()
        finally:
            logging.info("TUI run loop finished."); self.app_is_running = False

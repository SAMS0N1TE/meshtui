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
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, ConditionalContainer
from prompt_toolkit.layout.scrollable_pane import ScrollablePane
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import Frame, TextArea, Label
from prompt_toolkit.styles import Style, DynamicStyle
from prompt_toolkit.mouse_events import MouseEventType

from app_state import AppState, TuiState, Panel, Event

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
        self.input_field = TextArea(height=1, multiline=False, wrap_lines=False, prompt=">> ")

    def _create_application(self):
        root_container = HSplit([
            Label(text=" Meshtastic TUI - F5:Traceroute | F6:Theme | F8:Settings | Tab:Switch Panel | Ctrl+C:Quit", style="class:header"),
            ConditionalContainer(content=self._create_chat_layout(), filter=Condition(lambda: self.state.tui_state == TuiState.CHAT)),
            ConditionalContainer(content=self._create_settings_layout(), filter=Condition(lambda: self.state.tui_state == TuiState.SETTINGS))
        ])
        dynamic_style = DynamicStyle(lambda: Style.from_dict(self.state.get_current_theme()))
        return Application(layout=Layout(root_container, focused_element=self.settings_control), key_bindings=self._get_key_bindings(),
                           full_screen=True, style=dynamic_style, before_render=self._before_render, mouse_support=True)

    def _create_chat_layout(self):
        nodes_pane = ScrollablePane(Window(self.nodes_control, always_hide_cursor=True))
        return HSplit([
            VSplit([Frame(title=self._get_chat_title, body=Window(self.chat_control, wrap_lines=True)),
                    Frame(title=self._get_nodes_title, body=nodes_pane, width=35)]),
            Window(height=1, content=self.status_control, style="class:statusbar"),
            Frame(title=self._get_input_title, body=self.input_field, height=3)])

    def _create_settings_layout(self):
        settings_pane = ScrollablePane(Window(self.settings_control, always_hide_cursor=True))
        return HSplit([Frame(title="Settings: Select a Port", body=settings_pane),
                       Label(text="Use UP/DOWN arrows or Click to select. F8 to return to chat.")])

    def _get_key_bindings(self):
        kb = KeyBindings()

        # FIX: Split the decorators onto separate lines.
        @kb.add("c-c", eager=True)
        @kb.add("c-q", eager=True)
        def _(event):
            self.app_is_running = False
            self.command_queue.put((Event.TUI_EXIT, None))
            event.app.exit()

        @kb.add("f6")
        def _(event): self.state.cycle_theme()
        @kb.add("f8")
        def _(event):
            self.state.tui_state = TuiState.CHAT if self.state.tui_state == TuiState.SETTINGS else TuiState.SETTINGS
            event.app.layout.focus(self.input_field if self.state.tui_state == TuiState.CHAT else self.settings_control)
        is_chat = Condition(lambda: self.state.tui_state == TuiState.CHAT)
        is_input = Condition(lambda: self.state.active_panel == Panel.INPUT and is_chat())
        is_nodes = Condition(lambda: self.state.active_panel == Panel.NODES and is_chat())
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
        def _(event): self.state.dm_target_id = None; self.state.active_panel = Panel.INPUT; event.app.layout.focus(self.input_field)
        @kb.add("f5", filter=is_nodes)
        def _(event):
            node_list = self.state.get_node_list()
            if self.state.nodes_selected_line < len(node_list):
                selected_node_id = node_list[self.state.nodes_selected_line].get('id')
                if selected_node_id: self.command_queue.put((Event.SEND_TRACEROUTE, selected_node_id))
        @kb.add("up", filter=is_nodes)
        def _(event): self.state.nodes_selected_line = max(0, self.state.nodes_selected_line - 1)
        @kb.add("down", filter=is_nodes)
        def _(event): self.state.nodes_selected_line = min(len(self.state.get_node_list()) - 1, self.state.nodes_selected_line + 1)
        @kb.add("enter", filter=is_nodes)
        def _(event):
            node_list = self.state.get_node_list()
            if self.state.nodes_selected_line < len(node_list):
                self.state.dm_target_id = node_list[self.state.nodes_selected_line]['id']
                self.state.active_panel = Panel.INPUT; event.app.layout.focus(self.input_field)
        is_settings = Condition(lambda: self.state.tui_state == TuiState.SETTINGS)
        @kb.add("up", filter=is_settings)
        def _(event): self.state.settings_selected_line = max(0, self.state.settings_selected_line - 1)
        @kb.add("down", filter=is_settings)
        def _(event):
            if self.state.available_ports: self.state.settings_selected_line = min(len(self.state.available_ports) - 1, self.state.settings_selected_line + 1)
        @kb.add("enter", filter=is_settings)
        def _(event):
            if self.state.settings_selected_line < len(self.state.available_ports):
                port = self.state.available_ports[self.state.settings_selected_line].device
                self.command_queue.put((Event.SET_PORT, port))
                self.state.tui_state = TuiState.CHAT; event.app.layout.focus(self.input_field)
        return kb

    def _get_chat_title(self): return f" DM: {self.state.get_dm_target_name()} " if self.state.dm_target_id else " Broadcast (All) "
    def _get_nodes_title(self): return [("", " "), (f"class:frame.label{' reverse' if self.state.active_panel == Panel.NODES else ''}", "Nodes"), ("", " ")]
    def _get_input_title(self): return [("", " "), (f"class:frame.label{' reverse' if self.state.active_panel == Panel.INPUT else ''}", "Input"), ("", " ")]

    def _handle_events(self):
        while True:
            try: event, data = self.update_queue.get_nowait(); self.state.process_event(event, data)
            except queue.Empty: break

    def _update_ui_text(self):
        try:
            messages = self.state.get_current_messages()
            chat_fragments = []
            for msg in messages:
                status_map = {'SENDING': '[?]', 'DELIVERED': '[✓]', 'FAILED': '[X]'}
                sender_id = msg['sender_id']
                if sender_id == self.state.my_node_num: sender_name = "You"
                elif isinstance(sender_id, int): sender_name = self.state.nodes.get(sender_id, {}).get('name', f"!{sender_id:x}")
                else: sender_name = str(sender_id)
                style = "class:message.local" if sender_name == "You" else ("class:message.dm" if msg['is_dm'] else "class:message.remote")
                if msg['status'] == 'SYSTEM': style = 'class:message.error'
                status_indicator = status_map.get(msg['status'], '')
                chat_fragments.append((style, f"[{msg['timestamp']}] <{sender_name}> {status_indicator} {msg['text']}\n"))
            self.chat_control.text = chat_fragments

            node_fragments = []
            for i, node in enumerate(self.state.get_node_list()):
                is_selected = self.state.active_panel == Panel.NODES and i == self.state.nodes_selected_line
                style = "class:list.item.selected" if is_selected else ""
                prefix = "> " if is_selected else "  "
                if node['id'] is None: node_fragments.append((style, f"{prefix}{node['name']}\n")); continue
                notif = "* " if node.get('id') in self.state.unread_dm_senders else ""
                name = node.get('name', 'N/A')[:16]; snr_val = node.get('snr'); ago = get_time_ago(node.get('lastHeard'))
                snr_str = f"{snr_val:.1f}" if isinstance(snr_val, (int, float)) else str(snr_val)
                node_fragments.append((style, f"{prefix}{notif}{name:<16} {snr_str:>4}db {ago:>8}\n"))
            self.nodes_control.text = node_fragments

            status_color = "bold" if self.state.is_connected else "class:message.error"
            self.status_control.text = [ (status_color, f" {self.state.connection_status} "), ("", f" {self.state.connection_details} | Theme: {self.state.get_current_theme_name()}")]

            self.state.available_ports = list_ports.comports()
            settings_fragments = [("", "Detected Serial Ports:\n\n")]
            if not self.state.available_ports: settings_fragments.append(("", "  No serial ports found."))
            else:
                for i, port in enumerate(self.state.available_ports):
                    style = "class:list.item.selected" if i == self.state.settings_selected_line else ""
                    settings_fragments.append((style, f" {port.device}: {port.description}\n"))
            self.settings_control.text = settings_fragments
        except Exception as e:
            logging.error(f"Error during UI update: {e}", exc_info=True)

    def _before_render(self, app): self._handle_events(); self._update_ui_text()
    def run(self):
        try: self.app.run()
        finally: logging.info("TUI run loop finished."); self.app_is_running = False

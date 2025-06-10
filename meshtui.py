import curses
import meshtastic
import meshtastic.serial_interface
from pubsub import pub
import time
import threading
import queue
from serial.tools import list_ports
import logging
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
    filename='debug.log',
    filemode='w'
)

STATE_CHAT, STATE_SETTINGS = 0, 1
PANEL_INPUT, PANEL_NODES = 0, 1
EVENT_MSG, EVENT_CONN, EVENT_CHANNEL_UPDATE = 1, 2, 3
NOTIFICATION_DURATION = 5

class MeshtasticTUI:
    def __init__(self, stdscr):
        logging.info("Starting MeshtasticTUI. This node id will be set when connected.")
        self.stdscr = stdscr
        self.state = STATE_CHAT
        self.active_panel = PANEL_INPUT
        self.is_running = True
        self.event_queue = queue.Queue()
        self.messages, self.nodes, self.channels = [], {}, []
        self.dm_threads = {}  # Dict: node_id -> list of DM messages
        self.connection_status, self.connection_details = "Initializing...", ""
        self.dm_target, self.current_channel_index, self.my_node_num = None, 0, None
        self.input_text, self.settings_selected_line, self.nodes_selected_line = "", 0, 0
        self.interface, self.meshtastic_thread, self.next_port = None, None, None
        self.connected = False
        self.setup_curses()
        self.create_windows()
        self.start_meshtastic_thread()

    def setup_curses(self):
        self.stdscr.nodelay(True)
        curses.start_color()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE)
        curses.init_pair(5, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(6, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
        curses.init_pair(7, curses.COLOR_GREEN, curses.COLOR_BLACK)

    def create_windows(self):
        h, w = self.stdscr.getmaxyx()
        nodes_w = max(30, w // 4)
        chat_w = w - nodes_w
        self.win_chat = curses.newwin(h - 2, chat_w, 0, 0)
        self.win_nodes = curses.newwin(h - 2, nodes_w, 0, chat_w)
        self.win_status = curses.newwin(1, w, h - 2, 0)
        self.win_input = curses.newwin(1, w, h - 1, 0)
        self.win_chat.scrollok(True)

    def meshtastic_loop(self, port=None):
        while self.is_running:
            try:
                if not port:
                    self.set_connection_status("Disconnected", "Select port (F8)", connected=False)
                    time.sleep(2)
                    port = self.next_port
                    continue
                self.set_connection_status("Connecting...", f"to {port}", connected=False)
                self.interface = meshtastic.serial_interface.SerialInterface(port)
                try:
                    details = f"as {self.interface.myInfo.user.long_name}"
                except AttributeError:
                    details = "as Unknown"
                self.set_connection_status("Connected", details, connected=True)
                pub.subscribe(self.on_message_received, "meshtastic.receive")
                pub.subscribe(self.on_connection_event, "meshtastic.connection")
                pub.subscribe(self.on_node_updated, "meshtastic.node")
                if hasattr(self.interface, "radioConfig") and self.interface.radioConfig is not None:
                    channels = getattr(self.interface.radioConfig, "channels", None)
                    if channels:
                        channel_list = list(channels.values())
                    else:
                        channel_list = []
                    self.event_queue.put((EVENT_CHANNEL_UPDATE, (channel_list, self.interface.myInfo.my_node_num)))
                else:
                    self.event_queue.put((EVENT_CHANNEL_UPDATE, ([], self.interface.myInfo.my_node_num)))
                for node in self.interface.nodes.values():
                    self.on_node_updated(node)
                while self.is_running and self.next_port is None:
                    time.sleep(1)
            except Exception as e:
                logging.error(f"Exception in Meshtastic loop: {e}", exc_info=True)
                self.set_connection_status("Connection Error", "", connected=False)
                time.sleep(5)
            if self.interface:
                self.interface.close()
            if self.next_port:
                port = self.next_port
                self.next_port = None
            elif not self.is_running:
                break
        logging.info("Meshtastic thread is shutting down.")

    def set_connection_status(self, status, details, connected):
        self.connected = connected
        self.event_queue.put((EVENT_CONN, (status, details)))

    def on_connection_event(self, **kwargs):
        if kwargs.get("event_name") == "disconnected":
            self.set_connection_status("Connection Lost", "", connected=False)

    def on_message_received(self, packet, interface):
        logging.info(f"PACKET: {packet}")
        try:
            sender_id = packet.get('from')
            to_id = packet.get('to')
            decoded = packet.get('decoded', {})
            text = decoded.get('text', None)
            logging.info(f"Decoded text: {text}, Top-level to: {to_id}, Sender: {sender_id}, MyNode: {self.my_node_num}")

            if text is None:
                logging.info("No text found in decoded packet. Skipping.")
                return

            timestamp = time.strftime('%H:%M:%S')
            # Correct DM detection:
            if to_id == self.my_node_num and sender_id != self.my_node_num:
                # This is an incoming DM to me
                other_id = sender_id
                sender_name = self.nodes.get(sender_id, {}).get('name', f"!{sender_id}")
                formatted = f"[{timestamp}] <{sender_name} (DM)> {text}"
                self.event_queue.put((EVENT_MSG, (sender_id, formatted, True, other_id)))
                logging.info(f"Identified as incoming DM from {other_id}")
            elif sender_id == self.my_node_num and to_id != meshtastic.BROADCAST_NUM:
                # Outgoing DM sent by me
                other_id = to_id
                sender_name = self.nodes.get(sender_id, {}).get('name', f"!{sender_id}")
                formatted = f"[{timestamp}] <You (DM)> {text}"
                self.event_queue.put((EVENT_MSG, (sender_id, formatted, True, other_id)))
                logging.info(f"Identified as outgoing DM to {other_id}")
            else:
                # Broadcast message or group message
                sender_name = self.nodes.get(sender_id, {}).get('name', f"!{sender_id}")
                formatted = f"[{timestamp}] <{sender_name}> {text}"
                self.event_queue.put((EVENT_MSG, (sender_id, formatted, False, None)))
                logging.info("Identified as broadcast/general message")
        except Exception as e:
            logging.error(f"Error in on_message_received: {e}", exc_info=True)


    def on_node_updated(self, node):
        node_id = node.get('num')
        if not node_id:
            return
        last_heard = self.nodes.get(node_id, {}).get('last_heard')
        self.nodes[node_id] = {'id': node_id, 'name': node.get('user', {}).get('longName', f"Node {node_id}"), 'snr': node.get('snr', 'N/A'), 'last_heard': last_heard}

    def start_meshtastic_thread(self, port=None):
        if self.meshtastic_thread and self.meshtastic_thread.is_alive():
            self.next_port = port
            if self.interface:
                self.interface.close()
        else:
            self.meshtastic_thread = threading.Thread(target=self.meshtastic_loop, args=(port,), name="MeshtasticThread", daemon=True)
            self.meshtastic_thread.start()

    def handle_events(self):
        try:
            event_type, data = self.event_queue.get_nowait()
            if event_type == EVENT_MSG:
                sender_id, message_text, is_dm, other_id = data
                if is_dm and other_id:
                    if other_id not in self.dm_threads:
                        self.dm_threads[other_id] = []
                    self.dm_threads[other_id].append(message_text)
                elif not is_dm:
                    self.messages.append(message_text)
                if sender_id in self.nodes:
                    self.nodes[sender_id]['last_heard'] = time.time()
                return True
            elif event_type == EVENT_CONN:
                status, details = data
                if status == "Connected":
                    self.connection_status, self.connection_details = status, details
                elif not self.connected:
                    self.connection_status, self.connection_details = status, details
                return True
            elif event_type == EVENT_CHANNEL_UPDATE:
                self.channels, self.my_node_num = data
                logging.info(f"Set my_node_num: {self.my_node_num}")
                return True
        except queue.Empty:
            return False


    def handle_input(self):
        try:
            key = self.stdscr.getch()
        except curses.error:
            return False
        if key == -1:
            return False
        if key == curses.KEY_F8:
            self.state = STATE_SETTINGS if self.state == STATE_CHAT else STATE_CHAT
            return True
        if self.state == STATE_CHAT and not self.input_text and key == ord('q'):
            self.is_running = False
            return True
        if self.state == STATE_CHAT:
            return self.handle_chat_view_input(key)
        elif self.state == STATE_SETTINGS:
            return self.handle_settings_input(key)
        return False

    def handle_chat_view_input(self, key):
        if key == 14:
            self.cycle_channel(1)
            return True
        if key == 16:
            self.cycle_channel(-1)
            return True
        if key == 9:
            self.active_panel = PANEL_NODES if self.active_panel == PANEL_INPUT else PANEL_INPUT
            return True
        if self.active_panel == PANEL_INPUT:
            return self.handle_chat_input(key)
        elif self.active_panel == PANEL_NODES:
            return self.handle_nodes_input(key)
        return False

    def handle_chat_input(self, key):
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.input_text = self.input_text[:-1]
        elif key == ord('\n'):
            if self.input_text and self.interface:
                if self.dm_target and self.dm_target.get('id') is not None:
                    dest = self.dm_target['id']
                    formatted = f"[{time.strftime('%H:%M:%S')}] <You (DM)> {self.input_text}"
                    if dest not in self.dm_threads:
                        self.dm_threads[dest] = []
                    self.dm_threads[dest].append(formatted)
                    try:
                        self.interface.sendText(self.input_text, destinationId=dest)
                    except Exception as e:
                        self.dm_threads[dest].append(f"[{time.strftime('%H:%M:%S')}] [ERROR] {e}")
                else:
                    dest = meshtastic.BROADCAST_NUM
                    formatted = f"[{time.strftime('%H:%M:%S')}] <You> {self.input_text}"
                    self.messages.append(formatted)
                    try:
                        self.interface.sendText(self.input_text, destinationId=dest)
                    except Exception as e:
                        self.messages.append(f"[{time.strftime('%H:%M:%S')}] [ERROR] {e}")
                self.input_text = ""
        elif 32 <= key <= 126:
            self.input_text += chr(key)
        return True

    def handle_nodes_input(self, key):
        broadcast_option = {'id': None, 'name': '[ Broadcast (All) ]'}
        sorted_nodes = sorted([n for n in self.nodes.values() if n.get('id') != self.my_node_num], key=lambda x: x['name'])
        panel_items = [broadcast_option] + sorted_nodes
        if not panel_items:
            return True
        if key == curses.KEY_UP:
            self.nodes_selected_line = max(0, self.nodes_selected_line - 1)
        elif key == curses.KEY_DOWN:
            self.nodes_selected_line = min(len(panel_items) - 1, self.nodes_selected_line + 1)
        elif key == 27:
            self.dm_target = None
            self.active_panel = PANEL_INPUT
        elif key == ord('\n'):
            selected_item = panel_items[self.nodes_selected_line]
            self.dm_target = None if selected_item['id'] is None else selected_item
            self.active_panel = PANEL_INPUT
        return True

    def handle_settings_input(self, key):
        detected_ports = list_ports.comports()
        num_options = len(detected_ports) + 1
        if key == curses.KEY_UP:
            self.settings_selected_line = max(0, self.settings_selected_line - 1)
        elif key == curses.KEY_DOWN:
            self.settings_selected_line = min(num_options - 1, self.settings_selected_line + 1)
        elif key == ord('\n'):
            self.state = STATE_CHAT
            if self.settings_selected_line < len(detected_ports):
                self.start_meshtastic_thread(detected_ports[self.settings_selected_line].device)
            else:
                self.win_status.erase()
                self.win_status.addstr(0,1, "Enter port path: ")
                curses.echo()
                path = self.win_status.getstr(0, 19).decode("utf-8")
                curses.noecho()
                if path:
                    self.start_meshtastic_thread(path)
        return True

    def cycle_channel(self, direction):
        if not self.channels or not self.interface:
            return
        self.current_channel_index = (self.current_channel_index + direction) % len(self.channels)
        self.interface.radioConfig.channel_index = self.current_channel_index
        self.interface.writeConfig("radio")
        self.messages.append(f"--> Switched to channel '{self.channels[self.current_channel_index].settings.name}'")

    def draw(self):
        if self.state == STATE_CHAT:
            self.draw_chat_layout()
        elif self.state == STATE_SETTINGS:
            self.draw_settings_layout()
        curses.doupdate()

    def draw_message_line(self, window, y, message):
        try:
            timestamp_match = re.match(r"(\[\d{2}:\d{2}:\d{2}\])\s(.*)", message)
            if timestamp_match:
                timestamp, rest = timestamp_match.groups()
                window.addstr(y, 1, timestamp, curses.color_pair(2))
                message_body = rest
            else:
                message_body = message
                window.move(y, 1)
            sender_match = re.match(r"(<.+?>)\s(.*)", message_body)
            if sender_match:
                sender, text = sender_match.groups()
                color = curses.color_pair(6) if sender.startswith("<You") else curses.color_pair(5)
                window.addstr(sender, color | curses.A_BOLD)
                window.addstr(f" {text}")
            else:
                window.addstr(message_body, curses.color_pair(2) | curses.A_BOLD)
        except curses.error:
            pass

    def draw_chat_layout(self):
        self.win_chat.erase()
        self.win_nodes.erase()
        self.win_status.erase()
        self.win_input.erase()
        h, w = self.stdscr.getmaxyx()
        chat_lines = self.win_chat.getmaxyx()[0]
        if self.dm_target and self.dm_target.get('id') is not None:
            node_id = self.dm_target['id']
            msgs = self.dm_threads.get(node_id, [])
            title = f" DM: {self.dm_target['name']} "
            color = curses.color_pair(6)
        else:
            msgs = self.messages
            title = " Broadcast (All) "
            color = curses.color_pair(5)
        self.win_chat.box()
        self.win_chat.addstr(0, 2, title, color | curses.A_BOLD)
        for i, msg in enumerate(msgs[-(chat_lines - 2):]):
            self.draw_message_line(self.win_chat, i + 1, msg)
        nodes_color = curses.color_pair(5) if self.active_panel == PANEL_NODES else curses.A_NORMAL
        self.win_nodes.box()
        self.win_nodes.addstr(0, 2, " Nodes ", nodes_color | curses.A_BOLD)
        broadcast_option = {'id': None, 'name': '[ Broadcast (All) ]'}
        sorted_nodes = sorted([n for n in self.nodes.values() if n.get('id') != self.my_node_num], key=lambda x: x['name'])
        panel_items = [broadcast_option] + sorted_nodes
        for i, item in enumerate(panel_items):
            if i >= h-3:
                break
            is_broadcast = item['id'] is None
            node_str = item['name'] if is_broadcast else f"{item['name']} (SNR:{item['snr']})"
            notification = ""
            if not is_broadcast and item.get('id') in self.dm_threads and self.dm_threads[item['id']]:
                notification = "* "
            line_to_draw = f"{notification}{node_str}"
            if i == self.nodes_selected_line and self.active_panel == PANEL_NODES:
                self.win_nodes.addstr(i + 1, 2, line_to_draw, curses.color_pair(4))
            else:
                self.win_nodes.addstr(i + 1, 2, notification, curses.color_pair(2) | curses.A_BOLD)
                self.win_nodes.addstr(node_str)
        status_color = curses.color_pair(7) if self.connection_status == "Connected" else curses.color_pair(3)
        self.win_status.bkgd(' ', curses.color_pair(1))
        self.win_status.addstr(0,1, " ")
        self.win_status.addstr(0, 2, self.connection_status, status_color | curses.A_BOLD)
        ch_name = self.channels[self.current_channel_index].settings.name if self.channels else "N/A"
        self.win_status.addstr(f" | Ch: {ch_name}")
        key_text = "F8|Tab|Arrows|Enter|Esc|q"
        self.win_status.addstr(0, w - len(key_text) - 1, key_text)
        input_color = curses.color_pair(5) if self.active_panel == PANEL_INPUT else curses.A_NORMAL
        prompt = f"DM to {self.dm_target['name']}" if self.dm_target and self.dm_target.get('id') is not None else "Broadcast"
        self.win_input.addstr(0, 0, f"[{prompt}]", input_color | curses.A_BOLD)
        self.win_input.addstr(" > ")
        self.win_input.addstr(self.input_text)
        self.win_chat.noutrefresh()
        self.win_nodes.noutrefresh()
        self.win_status.noutrefresh()
        self.win_input.noutrefresh()

    def draw_settings_layout(self):
        self.stdscr.erase()
        self.stdscr.box()
        self.stdscr.addstr(1, 2, "--- Settings: Select a Port ---", curses.color_pair(5) | curses.A_BOLD)
        detected_ports = list_ports.comports()
        for i, port in enumerate(detected_ports):
            line = f"{port.device}: {port.description}"
            if i == self.settings_selected_line:
                self.stdscr.addstr(i + 3, 2, line, curses.color_pair(4))
            else:
                self.stdscr.addstr(i + 3, 2, line)
        manual_text = "Manual Entry..."
        manual_line_idx = len(detected_ports)
        if manual_line_idx == self.settings_selected_line:
            self.stdscr.addstr(manual_line_idx + 3, 2, manual_text, curses.color_pair(4))
        else:
            self.stdscr.addstr(manual_line_idx + 3, 2, manual_text)
        self.stdscr.addstr(self.stdscr.getmaxyx()[0] - 2, 2, "Use UP/DOWN and Enter. F8 to return.")
        self.stdscr.noutrefresh()

    def run(self):
        curses.curs_set(0)
        curses.cbreak()
        curses.noecho()
        self.draw()
        while self.is_running:
            has_changed = self.handle_input() or self.handle_events()
            if has_changed:
                self.draw()
            time.sleep(0.05)

    def shutdown(self):
        self.is_running = False
        if self.meshtastic_thread:
            self.meshtastic_thread.join(timeout=2)

def main(stdscr):
    app = MeshtasticTUI(stdscr)
    try:
        app.run()
    finally:
        app.shutdown()

if __name__ == "__main__":
    curses.wrapper(main)

import time
import logging
from enum import Enum, auto
from collections import deque
import google.protobuf.json_format
from meshtastic.protobuf import mesh_pb2, portnums_pb2

import meshtastic


class TuiState(Enum):
    CHAT, SETTINGS = auto(), auto()


class Panel(Enum):
    INPUT, NODES = auto(), auto()


class Event(Enum):
    SET_PORT, SEND_TEXT, SEND_TRACEROUTE, TUI_EXIT = auto(), auto(), auto(), auto()
    PACKET_RECEIVED, MY_INFO_UPDATE, NODES_UPDATE = auto(), auto(), auto()
    SINGLE_NODE_UPDATE, CONNECTION_STATUS, LOG_ERROR = auto(), auto(), auto()
    MESSAGE_SENT, MESSAGE_DELIVERY_STATUS, TRACEROUTE_RESPONSE_RECEIVED = auto(), auto(), auto()


class AppState:
    """A centralized class to hold and process the application's state."""

    def __init__(self, max_messages=200):
        self.tui_state = TuiState.SETTINGS
        self.active_panel = Panel.INPUT
        self.settings_selected_line = 0
        self.nodes_selected_line = 0
        self.available_ports = []
        self.is_connected = False
        self.connection_status = "Disconnected"
        self.connection_details = "Use F8 to select port"
        self.my_node_num = None
        self.nodes = {}
        self.dm_target_id = None
        self.broadcast_messages = deque(maxlen=max_messages)
        self.dm_threads = {}
        self.unread_dm_senders = set()
        self.message_states = {}  # message_id -> {'text':, 'status':, ...}

    def _update_node(self, node_data):
        node_num = node_data.get('num')
        if not node_num: return
        user = node_data.get('user', {})
        self.nodes[node_num] = {
            'id': node_num,
            'name': user.get('longName', f"Node {node_num:x}"),
            'lastHeard': node_data.get('lastHeard'),
            'snr': node_data.get('snr', 'N/A')
        }

    def _format_traceroute(self, packet):
        """Parses a traceroute packet and returns a formatted string."""
        try:
            route_discovery = mesh_pb2.RouteDiscovery()
            route_discovery.ParseFromString(packet["decoded"]["payload"])
            msg_dict = google.protobuf.json_format.MessageToDict(route_discovery)

            from_node = self.nodes.get(packet["from"], {}).get("name", f"!{packet['from']:x}")
            to_node = self.nodes.get(packet["to"], {}).get("name", f"!{packet['to']:x}")

            route_parts = [from_node]
            if "route" in msg_dict:
                for hop_num in msg_dict["route"]:
                    hop_name = self.nodes.get(hop_num, {}).get("name", f"!{hop_num:x}")
                    route_parts.append(hop_name)
            route_parts.append(to_node)

            return f"Traceroute from {from_node}: {' --> '.join(route_parts)}"
        except Exception as e:
            logging.error(f"Failed to parse traceroute: {e}", exc_info=True)
            return "Failed to parse traceroute."

    def process_event(self, event_type, data):
        """Processes events from the handler to update state."""
        if event_type == Event.MESSAGE_SENT:
            msg_id, text, dest_id = data
            is_dm = dest_id != meshtastic.BROADCAST_NUM
            self.message_states[msg_id] = {'text': text, 'status': 'SENDING', 'is_dm': is_dm, 'dest_id': dest_id,
                                           'sender_id': self.my_node_num, 'timestamp': time.strftime('%H:%M:%S')}
        elif event_type == Event.MESSAGE_DELIVERY_STATUS:
            msg_id, status = data
            if msg_id in self.message_states:
                self.message_states[msg_id]['status'] = status
        elif event_type == Event.TRACEROUTE_RESPONSE_RECEIVED:
            formatted_route = self._format_traceroute(data)
            self._add_system_message(formatted_route)
        elif event_type == Event.CONNECTION_STATUS:
            self.connection_status, self.connection_details, self.is_connected = data
            if not self.is_connected: self.nodes.clear(); self.my_node_num = None
        elif event_type == Event.MY_INFO_UPDATE:
            self.my_node_num = data.get('num');
            self._update_node(data)
        elif event_type == Event.NODES_UPDATE:
            for node_info in data.values(): self._update_node(node_info)
        elif event_type == Event.SINGLE_NODE_UPDATE:
            self._update_node(data)
        elif event_type == Event.LOG_ERROR:
            self._add_system_message(data)
        elif event_type == Event.PACKET_RECEIVED:
            self._process_packet(data)
        else:
            return False
        return True

    def _add_system_message(self, text):
        """Adds a system message to the message store."""
        msg_id = f"sys_{time.time_ns()}"
        self.message_states[msg_id] = {'text': text, 'status': 'SYSTEM', 'is_dm': False, 'sender_id': 'SYSTEM',
                                       'timestamp': time.strftime('%H:%M:%S')}

    def _process_packet(self, packet):
        """Processes a single incoming Meshtastic packet."""
        decoded = packet.get('decoded', {})
        portnum = decoded.get('portnum')

        # FIX: Removed the debugging log that displayed all incoming packets.
        # debug_msg = f"Packet IN: from='{packet.get('from')}', port='{portnum}', snr='{packet.get('rxSnr')}'"
        # self._add_system_message(debug_msg)
        # logging.info(debug_msg)

        sender_id = packet.get('from')
        if sender_id and sender_id in self.nodes:
            self.nodes[sender_id]['lastHeard'] = packet.get('rxTime')
            self.nodes[sender_id]['snr'] = packet.get('rxSnr')

        if portnum == "TEXT_MESSAGE_APP":
            text = decoded.get('text')
            if not text:
                payload = decoded.get('payload')
                if payload:
                    text = payload.decode('utf-8', 'ignore')

            if not text:
                logging.debug("Ignoring TEXT_MESSAGE_APP packet with no text content.")
                return

            to_id = packet.get('to')
            is_dm = to_id != meshtastic.BROADCAST_NUM

            msg_id = f"rx_{time.time_ns()}"
            self.message_states[msg_id] = {
                'text': text,
                'status': 'RECEIVED',
                'is_dm': is_dm,
                'dest_id': to_id,
                'sender_id': sender_id,
                'timestamp': time.strftime('%H:%M:%S')
            }

            if is_dm and sender_id != self.my_node_num and (sender_id != self.dm_target_id):
                self.unread_dm_senders.add(sender_id)

    def get_node_list(self):
        """Returns a sorted list of nodes for the UI, with Broadcast at the top."""
        broadcast = {'id': None, 'name': '[ Broadcast (All) ]'}
        other_nodes = [n for n in self.nodes.values() if n.get('id') != self.my_node_num]

        def sort_key(node):
            last_heard = node.get('lastHeard') or 0
            name = node.get('name', '').lower()
            return (-last_heard, name)

        return [broadcast] + sorted(other_nodes, key=sort_key)

    def get_current_messages(self):
        """Returns the message list for the currently active view (Broadcast or DM)."""
        if self.dm_target_id:
            self.unread_dm_senders.discard(self.dm_target_id)
            target_ids = {self.my_node_num, self.dm_target_id}
            messages = [m for m in self.message_states.values() if
                        m['is_dm'] and m['sender_id'] in target_ids and m['dest_id'] in target_ids]
        else:
            messages = [m for m in self.message_states.values() if not m['is_dm'] or m['status'] == 'SYSTEM']

        return sorted(messages, key=lambda m: m['timestamp'])

    def get_dm_target_name(self):
        """Returns the name of the current DM target, if any."""
        if self.dm_target_id:
            return self.nodes.get(self.dm_target_id, {}).get('name', f"!{self.dm_target_id:x}")
        return None

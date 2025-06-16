# goog/app_state.py

import time
import logging
import random
import math
import requests
from io import BytesIO
from enum import Enum, auto
from collections import deque

import google.protobuf.json_format
from meshtastic.protobuf import mesh_pb2, portnums_pb2
from PIL import Image, ImageDraw, ImageFont

import meshtastic
from themes import THEMES

# --- Character Sets ---
CHAR_SETS = {
    "Simple": {"water": '≈', "land": '.', "park": '"', "road": '=', "building": '#'},
    "Blocks": {"water": '█', "land": '░', "park": '▒', "road": '▓', "building": '█'},
    "Lines & Curves": {"water": '~', "land": '`', "park": ';', "road": '-', "building": '+'},
    "High Contrast": {"water": ' ', "land": '░', "park": '▒', "road": '▓', "building": '█'}
}


# --- Helper functions for map tile calculations ---

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)


def num2deg(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)


# --- End Helper Functions ---


class TuiState(Enum):
    CHAT, SETTINGS, MAP = auto(), auto(), auto()


class Panel(Enum):
    INPUT, NODES = auto(), auto()


class Event(Enum):
    SET_PORT, SEND_TEXT, SEND_TRACEROUTE, TUI_EXIT = auto(), auto(), auto(), auto()
    PACKET_RECEIVED, MY_INFO_UPDATE, NODES_UPDATE = auto(), auto(), auto()
    SINGLE_NODE_UPDATE, CONNECTION_STATUS, LOG_ERROR = auto(), auto(), auto()
    MESSAGE_SENT, MESSAGE_DELIVERY_STATUS, TRACEROUTE_RESPONSE_RECEIVED = auto(), auto(), auto()
    GPS_UPDATE, TOGGLE_MAP = auto(), auto()
    MAP_ZOOM_IN, MAP_ZOOM_OUT, MAP_CENTER_ON_NODE, MAP_RECENTER = auto(), auto(), auto(), auto()
    MAP_MOVE_CURSOR_UP, MAP_MOVE_CURSOR_DOWN, MAP_MOVE_CURSOR_LEFT, MAP_MOVE_CURSOR_RIGHT = auto(), auto(), auto(), auto()
    MAP_PAN_FROM_CURSOR, MAP_CYCLE_CHARSET, MAP_CENTER_ON_CURSOR = auto(), auto(), auto()


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
        self.message_states = {}
        self.unread_dm_senders = set()
        self._map_cache = {}
        # Default to a view of the USA
        self.map_zoom = 4
        self.map_center_lat = 39.8283
        self.map_center_lon = -98.5795
        self.map_cursor_x = 35
        self.map_cursor_y = 11
        self.initial_recenter_done = False  # Flag to track if we've centered on live data yet

        self.map_char_sets = list(CHAR_SETS.items())
        self.map_char_set_index = 0
        self.map_visible = False

        # FIX: Restore the missing attribute
        self.available_themes = list(THEMES.keys())
        self.current_theme_index = 0

    def cycle_theme(self):
        """Cycles to the next available theme."""
        self.current_theme_index = (self.current_theme_index + 1) % len(self.available_themes)
        logging.info(f"Cycled theme to: {self.get_current_theme_name()}")

    def get_current_theme_name(self):
        """Gets the name of the currently active theme."""
        return self.available_themes[self.current_theme_index]

    def get_current_theme(self):
        """Gets the style dictionary for the currently active theme."""
        theme_name = self.get_current_theme_name()
        return THEMES[theme_name]

    def _update_node(self, node_data):
        node_num = node_data.get('num')
        if not node_num: return
        user = node_data.get('user', {})
        # Preserve existing GPS data if not in this update
        existing_node = self.nodes.get(node_num, {})
        lat = node_data.get('latitude', existing_node.get('latitude'))
        lon = node_data.get('longitude', existing_node.get('longitude'))

        self.nodes[node_num] = {
            'id': node_num,
            'name': user.get('longName', f"Node {node_num:x}"),
            'lastHeard': node_data.get('lastHeard', time.time()),
            'snr': node_data.get('snr', 10.0),
            'latitude': lat,
            'longitude': lon
        }

    def _format_traceroute(self, packet):
        try:
            route_discovery = mesh_pb2.RouteDiscovery()
            route_discovery.ParseFromString(packet["decoded"]["payload"])
            msg_dict = google.protobuf.json_format.MessageToDict(route_discovery)
            from_node = self.nodes.get(packet["from"], {}).get("name", f"!{packet['from']:x}")
            to_node = self.nodes.get(packet["to"], {}).get("name", f"!{packet['to']:x}")
            route_parts = [from_node]
            if "route" in msg_dict:
                for hop_num in msg_dict.get("route", []):
                    hop_name = self.nodes.get(hop_num, {}).get("name", f"!{hop_num:x}")
                    route_parts.append(hop_name)
            route_parts.append(to_node)
            return f"Traceroute from {from_node}: {' --> '.join(route_parts)}"
        except Exception as e:
            logging.error(f"Failed to parse traceroute: {e}", exc_info=True)
            return "Failed to parse traceroute response."

    def process_event(self, event_type, data):
        # Invalidate map cache for any map-changing event that requires a new tile
        if event_type.name in ["MAP_ZOOM_IN", "MAP_ZOOM_OUT", "MAP_CENTER_ON_NODE", "MAP_RECENTER",
                               "MAP_PAN_FROM_CURSOR", "MAP_CYCLE_CHARSET", "MAP_CENTER_ON_CURSOR"]:
            self._map_cache = {}

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
        elif event_type == Event.GPS_UPDATE:
            node_num, lat, lon = data
            if node_num in self.nodes:
                self.nodes[node_num]['latitude'] = lat
                self.nodes[node_num]['longitude'] = lon
                # If we haven't done the first recenter yet, do it now.
                if not self.initial_recenter_done:
                    self.process_event(Event.MAP_RECENTER, None)
                    self.initial_recenter_done = True
        elif event_type == Event.TOGGLE_MAP:
            self.map_visible = not self.map_visible
            if self.map_visible and not self.initial_recenter_done:
                self.process_event(Event.MAP_RECENTER, None)
            self.tui_state = TuiState.MAP if self.map_visible else TuiState.CHAT
        elif event_type == Event.MAP_MOVE_CURSOR_UP:
            if self.map_cursor_y > 0:
                self.map_cursor_y -= 1
            else:
                self.process_event(Event.MAP_PAN_FROM_CURSOR, 'up')
        elif event_type == Event.MAP_MOVE_CURSOR_DOWN:
            if self.map_cursor_y < 22 - 1:
                self.map_cursor_y += 1
            else:
                self.process_event(Event.MAP_PAN_FROM_CURSOR, 'down')
        elif event_type == Event.MAP_MOVE_CURSOR_LEFT:
            if self.map_cursor_x > 0:
                self.map_cursor_x -= 1
            else:
                self.process_event(Event.MAP_PAN_FROM_CURSOR, 'left')
        elif event_type == Event.MAP_MOVE_CURSOR_RIGHT:
            if self.map_cursor_x < 70 - 1:
                self.map_cursor_x += 1
            else:
                self.process_event(Event.MAP_PAN_FROM_CURSOR, 'right')
        elif event_type == Event.MAP_PAN_FROM_CURSOR:
            if self.map_zoom and self.map_center_lat and self.map_center_lon:
                direction = data
                xtile, ytile = deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom)
                if direction == 'up': ytile -= 1
                if direction == 'down': ytile += 1
                if direction == 'left': xtile -= 1
                if direction == 'right': xtile += 1

                self.map_center_lat, self.map_center_lon = num2deg(xtile + 0.5, ytile + 0.5, self.map_zoom)

                if direction == 'up': self.map_cursor_y = 22 - 2
                if direction == 'down': self.map_cursor_y = 1
                if direction == 'left': self.map_cursor_x = 70 - 2
                if direction == 'right': self.map_cursor_x = 1

        elif event_type == Event.MAP_CENTER_ON_CURSOR:
            if self.map_zoom and self.map_center_lat and self.map_center_lon:
                xtile, ytile = deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom)
                top_lat, top_lon = num2deg(xtile, ytile, self.map_zoom)
                bottom_lat, right_lon = num2deg(xtile + 1, ytile + 1, self.map_zoom)

                lat_range = abs(top_lat - bottom_lat)
                lon_range = abs(right_lon - top_lon)

                lat_offset = (self.map_cursor_y / 21.0) * lat_range
                lon_offset = (self.map_cursor_x / 69.0) * lon_range

                self.map_center_lat = top_lat - lat_offset
                self.map_center_lon = top_lon + lon_offset
                self.map_cursor_x = 70 // 2
                self.map_cursor_y = 22 // 2
        elif event_type == Event.MAP_ZOOM_IN:
            if self.map_zoom is not None:
                self.map_zoom = min(18, self.map_zoom + 1)
        elif event_type == Event.MAP_ZOOM_OUT:
            if self.map_zoom is not None:
                self.map_zoom = max(1, self.map_zoom - 1)
        elif event_type == Event.MAP_CENTER_ON_NODE:
            node_id = data
            if node_id and node_id in self.nodes and self.nodes[node_id].get('latitude'):
                self.map_center_lat = self.nodes[node_id]['latitude']
                self.map_center_lon = self.nodes[node_id]['longitude']
                self.map_cursor_x = 70 // 2
                self.map_cursor_y = 22 // 2
        elif event_type == Event.MAP_RECENTER:
            nodes_with_gps = [n for n in self.nodes.values() if n.get('latitude') and n.get('longitude')]
            if nodes_with_gps:
                min_lat = min(n['latitude'] for n in nodes_with_gps)
                max_lat = max(n['latitude'] for n in nodes_with_gps)
                min_lon = min(n['longitude'] for n in nodes_with_gps)
                max_lon = max(n['longitude'] for n in nodes_with_gps)

                self.map_center_lat, self.map_center_lon = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2

                lat_diff = abs(max_lat - min_lat)
                lon_diff = abs(max_lon - min_lon)
                if lat_diff < 0.001 and lon_diff < 0.001:
                    self.map_zoom = 15
                else:
                    self.map_zoom = int(min(18, max(1, 8 - math.log2(max(lat_diff, lon_diff)))))
                self.map_cursor_x = 70 // 2
                self.map_cursor_y = 22 // 2
        elif event_type == Event.MAP_CYCLE_CHARSET:
            self.map_char_set_index = (self.map_char_set_index + 1) % len(self.map_char_sets)
        else:
            return False
        return True

    def _add_system_message(self, text):
        msg_id = f"sys_{time.time_ns()}"
        self.message_states[msg_id] = {'text': text, 'status': 'SYSTEM', 'is_dm': False, 'sender_id': 'SYSTEM',
                                       'timestamp': time.strftime('%H:%M:%S')}

    def _process_packet(self, packet):
        decoded = packet.get('decoded', {})
        portnum = decoded.get('portnum')
        sender_id = packet.get('from')
        if sender_id and sender_id in self.nodes:
            self.nodes[sender_id]['lastHeard'] = packet.get('rxTime')
            self.nodes[sender_id]['snr'] = packet.get('rxSnr')

        if portnum == "POSITION_APP" and decoded.get('payload'):
            try:
                position = mesh_pb2.Position()
                position.ParseFromString(decoded.get('payload'))
                if position.latitude_i != 0 and position.longitude_i != 0:
                    lat = position.latitude_i / 1e7
                    lon = position.longitude_i / 1e7
                    self.process_event(Event.GPS_UPDATE, (sender_id, lat, lon))
            except Exception as e:
                logging.error(f"Failed to parse position packet: {e}")

        if portnum == "TEXT_MESSAGE_APP":
            text = decoded.get('text')
            if not text: text = decoded.get('payload', b'').decode('utf-8', 'ignore')
            if not text: logging.debug("Ignoring TEXT_MESSAGE_APP packet with no text content."); return
            to_id = packet.get('to')
            is_dm = to_id != meshtastic.BROADCAST_NUM
            msg_id = f"rx_{time.time_ns()}"
            self.message_states[msg_id] = {'text': text, 'status': 'RECEIVED', 'is_dm': is_dm, 'dest_id': to_id,
                                           'sender_id': sender_id, 'timestamp': time.strftime('%H:%M:%S')}
            if is_dm and sender_id != self.my_node_num and (sender_id != self.dm_target_id):
                self.unread_dm_senders.add(sender_id)

    def get_node_list(self):
        broadcast = {'id': None, 'name': '[ Broadcast (All) ]'}
        other_nodes = [n for n in self.nodes.values() if n.get('id') != self.my_node_num]

        def sort_key(node):
            last_heard = node.get('lastHeard') or 0
            name = node.get('name', '').lower()
            return (-last_heard, name)

        return [broadcast] + sorted(other_nodes, key=sort_key)

    def get_current_messages(self):
        if self.dm_target_id:
            self.unread_dm_senders.discard(self.dm_target_id)
            target_ids = {self.my_node_num, self.dm_target_id}
            messages = [m for m in self.message_states.values() if
                        m['is_dm'] and m['sender_id'] in target_ids and m['dest_id'] in target_ids]
        else:
            messages = [m for m in self.message_states.values() if not m['is_dm'] or m['status'] == 'SYSTEM']
        return sorted(messages, key=lambda m: m['timestamp'])

    def get_dm_target_name(self):
        if self.dm_target_id:
            return self.nodes.get(self.dm_target_id, {}).get('name', f"!{self.dm_target_id:x}")
        return None

    def _get_char_for_pixel(self, r, g, b, char_set):
        intensity = 0.299 * r + 0.587 * g + 0.114 * b
        if b > r and b > g and b > 120: return ('class:map.water', char_set["water"])
        if g > r and g > b and g > 100: return ('class:map.land', char_set["park"])
        if r > 200 and g > 150 and b < 100: return ('class:map.structure', char_set["road"])
        if abs(r - g) < 20 and abs(g - b) < 20 and intensity > 50: return ('class:map.structure', char_set["building"])
        return ('class:text-area', char_set["land"])

    def get_ascii_map(self):
        map_cols, map_rows = 70, 22

        if self.map_zoom is None or self.map_center_lat is None:
            return [("class:message.error", "Calculating map center...")]

        char_set_name, char_set = self.map_char_sets[self.map_char_set_index]
        cache_key = (self.map_zoom, round(self.map_center_lat, 4), round(self.map_center_lon, 4), char_set_name)
        if cache_key in self._map_cache:
            grid = self._map_cache[cache_key]
        else:
            try:
                xtile, ytile = deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom)

                url = f"https://tile.openstreetmap.org/{self.map_zoom}/{xtile}/{ytile}.png"
                logging.info(f"Fetching map tile: {url}")
                response = requests.get(url, headers={'User-Agent': 'Meshtastic-TUI/1.0'}, timeout=10)
                response.raise_for_status()
                tile_img = Image.open(BytesIO(response.content)).convert("RGB")

                resized_img = tile_img.resize((map_cols, map_rows), Image.Resampling.LANCZOS)
                pixels = resized_img.load()

                grid = []
                for y in range(map_rows):
                    row = []
                    for x in range(map_cols):
                        style, char = self._get_char_for_pixel(*pixels[x, y], char_set)
                        row.append((style, char))
                    grid.append(row)

                self._map_cache[cache_key] = grid

            except Exception as e:
                logging.error(f"Failed to generate map: {e}", exc_info=True)
                return [("class:message.error", f"Could not generate map: {e}")]

        display_grid = [row[:] for row in grid]

        nodes_with_gps = [n for n in self.nodes.values() if n.get('latitude') and n.get('longitude')]
        top_left_lat, top_left_lon = num2deg(*deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom),
                                             self.map_zoom)
        bottom_right_lat, bottom_right_lon = num2deg(
            deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom)[0] + 1,
            deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom)[1] + 1, self.map_zoom)
        tile_lat_range = abs(top_left_lat - bottom_right_lat)
        tile_lon_range = abs(bottom_right_lon - top_left_lon)

        for node in nodes_with_gps:
            if tile_lon_range == 0 or tile_lat_range == 0: continue

            char_x = int(((node['longitude'] - top_left_lon) / tile_lon_range) * map_cols)
            char_y = int(((top_left_lat - node['latitude']) / tile_lat_range) * map_rows)

            if 0 <= char_y < map_rows and 0 <= char_x < map_cols:
                style = "class:node.notification" if node['id'] == self.my_node_num else "class:message.error"
                marker = '★' if node['id'] == self.my_node_num else '●'
                display_grid[char_y][char_x] = (style, marker)

        if self.map_cursor_x is not None and self.map_cursor_y is not None:
            display_grid[self.map_cursor_y][self.map_cursor_x] = ('class:statusbar reverse', '+')

        result = []
        for row in display_grid:
            result.extend(row)
            result.append(('', '\n'))

        return result

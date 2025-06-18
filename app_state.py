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
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

import meshtastic
from themes import THEMES

# --- Character Sets ---
CHAR_SETS = {
    "Simple": {"water": '≈', "land": '.', "park": '"', "road": '=', "building": '#'},
    "Blocks": {"water": '█', "land": '░', "park": '▒', "road": '▓', "building": '█'},
    "Lines & Curves": {"water": '~', "land": '`', "park": ';', "road": '-', "building": '+'},
    "High Contrast": {"water": ' ', "land": '░', "park": '▒', "road": '▓', "building": '█'}
}

# --- Map Tile Sources ---
MAP_SOURCES = {
    "OpenStreetMap": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "Toner": "https://tile.openstreetmap.org/{z}/{x}/{y}.png", # Will be filtered to B&W
}

# --- Constants for conceptual map grid size for cursor logic ---
CONCEPTUAL_MAP_WIDTH = 70
CONCEPTUAL_MAP_HEIGHT = 38 # Approx 0.55 aspect ratio of width

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
    MAP_PAN_FROM_CURSOR, MAP_CYCLE_CHARSET, MAP_CENTER_ON_CURSOR, MAP_CYCLE_TILE_SOURCE = auto(), auto(), auto(), auto()


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
        self.map_cursor_x = CONCEPTUAL_MAP_WIDTH // 2
        self.map_cursor_y = CONCEPTUAL_MAP_HEIGHT // 2
        self.initial_recenter_done = False 
        
        self.map_char_sets = list(CHAR_SETS.items())
        self.map_char_set_index = 0
        self.map_sources = list(MAP_SOURCES.items())
        self.map_source_index = 0
        self.map_visible = False
        
        self.available_themes = list(THEMES.keys())
        self.current_theme_index = 0

    def cycle_theme(self):
        self.current_theme_index = (self.current_theme_index + 1) % len(self.available_themes)
        logging.info(f"Cycled theme to: {self.get_current_theme_name()}")

    def get_current_theme_name(self):
        return self.available_themes[self.current_theme_index]

    def get_current_theme(self):
        theme_name = self.get_current_theme_name()
        return THEMES[theme_name]

    def _update_node(self, node_data):
        node_num = node_data.get('num')
        if not node_num: return
        user = node_data.get('user', {})
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

    def process_event(self, event_type, data):
        # This check for map events and clearing the cache is good. Keep it.
        if event_type.name.startswith("MAP_"): self._map_cache = {}

        # --- Start of new/missing logic ---

        if event_type == Event.CONNECTION_STATUS:
            self.is_connected, self.connection_status, self.connection_details = data[2], data[0], data[1]
            if not self.is_connected:
                # When disconnected, clear node-specific data
                self.nodes.clear()
                self.my_node_num = None
                self.message_states.clear()

        elif event_type == Event.MY_INFO_UPDATE:
            self.my_node_num = data.get('num')
            # Add self to node list
            self._update_node(data)

        elif event_type == Event.NODES_UPDATE:
            self.nodes.clear()
            for node_data in data.values():
                self._update_node(node_data)

        elif event_type == Event.SINGLE_NODE_UPDATE:
            self._update_node(data)

        elif event_type == Event.MESSAGE_SENT:
            message_id, text, destination_id = data
            is_dm = destination_id != meshtastic.BROADCAST_NUM
            self.message_states[message_id] = {
                'text': text, 'timestamp': time.strftime('%H:%M:%S'), 'status': 'SENDING',
                'sender_id': self.my_node_num, 'is_dm': is_dm
            }

        elif event_type == Event.MESSAGE_DELIVERY_STATUS:
            message_id, status = data
            if message_id in self.message_states:
                self.message_states[message_id]['status'] = status

        elif event_type == Event.LOG_ERROR:
            # Add errors as system messages
            system_message = {
                'text': data, 'timestamp': time.strftime('%H:%M:%S'), 'status': 'SYSTEM',
                'sender_id': 'System', 'is_dm': True
            }
            # Use a unique ID for system messages
            self.message_states[f"sys_{time.time_ns()}"] = system_message

        elif event_type == Event.PACKET_RECEIVED:
            packet = data
            if packet.get('decoded') and 'text' in packet['decoded']:
                from_node = packet.get('from')
                message_id = f"recv_{packet.get('id', time.time_ns())}"
                self.message_states[message_id] = {
                    'text': packet['decoded']['text'], 'timestamp': time.strftime('%H:%M:%S'), 'status': 'DELIVERED',
                    'sender_id': from_node, 'is_dm': packet.get('channel') == 0 # DMs are on the private channel
                }
                # Track unread messages if it's a DM from another node
                if self.dm_target_id != from_node:
                    self.unread_dm_senders.add(from_node)

        # --- End of new/missing logic ---

        elif event_type == Event.GPS_UPDATE:
            node_num, lat, lon = data
            if node_num in self.nodes:
                self.nodes[node_num]['latitude'] = lat
                self.nodes[node_num]['longitude'] = lon
                if not self.initial_recenter_done:
                    self.process_event(Event.MAP_RECENTER, None)
                    self.initial_recenter_done = True
        elif event_type == Event.TOGGLE_MAP:
            self.map_visible = not self.map_visible
            if self.map_visible and not self.initial_recenter_done:
                self.process_event(Event.MAP_RECENTER, None)
            self.tui_state = TuiState.MAP if self.map_visible else TuiState.CHAT
        elif event_type == Event.MAP_MOVE_CURSOR_UP:
            if self.map_cursor_y > 0: self.map_cursor_y -= 1
            else: self.process_event(Event.MAP_PAN_FROM_CURSOR, 'up')
        elif event_type == Event.MAP_MOVE_CURSOR_DOWN:
            if self.map_cursor_y < CONCEPTUAL_MAP_HEIGHT - 1: self.map_cursor_y += 1
            else: self.process_event(Event.MAP_PAN_FROM_CURSOR, 'down')
        elif event_type == Event.MAP_MOVE_CURSOR_LEFT:
            if self.map_cursor_x > 0: self.map_cursor_x -= 1
            else: self.process_event(Event.MAP_PAN_FROM_CURSOR, 'left')
        elif event_type == Event.MAP_MOVE_CURSOR_RIGHT:
             if self.map_cursor_x < CONCEPTUAL_MAP_WIDTH - 1: self.map_cursor_x += 1
             else: self.process_event(Event.MAP_PAN_FROM_CURSOR, 'right')
        elif event_type == Event.MAP_PAN_FROM_CURSOR:
            if self.map_zoom and self.map_center_lat and self.map_center_lon:
                direction = data
                xtile, ytile = deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom)
                if direction == 'up': ytile -= 1
                if direction == 'down': ytile += 1
                if direction == 'left': xtile -= 1
                if direction == 'right': xtile += 1
                
                self.map_center_lat, self.map_center_lon = num2deg(xtile + 0.5, ytile + 0.5, self.map_zoom)
                
                if direction == 'up': self.map_cursor_y = CONCEPTUAL_MAP_HEIGHT - 2
                if direction == 'down': self.map_cursor_y = 1
                if direction == 'left': self.map_cursor_x = CONCEPTUAL_MAP_WIDTH - 2
                if direction == 'right': self.map_cursor_x = 1
        elif event_type == Event.MAP_CENTER_ON_CURSOR:
             if self.map_zoom and self.map_center_lat and self.map_center_lon:
                xtile, ytile = deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom)
                top_lat, top_lon = num2deg(xtile, ytile, self.map_zoom)
                bottom_lat, right_lon = num2deg(xtile + 1, ytile + 1, self.map_zoom)
                
                lat_range = abs(top_lat - bottom_lat)
                lon_range = abs(right_lon - top_lon)

                lat_offset = (self.map_cursor_y / CONCEPTUAL_MAP_HEIGHT) * lat_range
                lon_offset = (self.map_cursor_x / CONCEPTUAL_MAP_WIDTH) * lon_range

                self.map_center_lat = top_lat - lat_offset
                self.map_center_lon = top_lon + lon_offset
                self.map_cursor_x = CONCEPTUAL_MAP_WIDTH // 2
                self.map_cursor_y = CONCEPTUAL_MAP_HEIGHT // 2
        elif event_type == Event.MAP_ZOOM_IN:
            if self.map_zoom is not None: self.map_zoom = min(18, self.map_zoom + 1)
        elif event_type == Event.MAP_ZOOM_OUT:
            if self.map_zoom is not None: self.map_zoom = max(1, self.map_zoom - 1)
        elif event_type == Event.MAP_CENTER_ON_NODE:
            node_id = data
            if node_id and node_id in self.nodes and self.nodes[node_id].get('latitude'):
                self.map_center_lat = self.nodes[node_id]['latitude']
                self.map_center_lon = self.nodes[node_id]['longitude']
                self.map_cursor_x = CONCEPTUAL_MAP_WIDTH // 2
                self.map_cursor_y = CONCEPTUAL_MAP_HEIGHT // 2
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
                if lat_diff < 0.001 and lon_diff < 0.001: self.map_zoom = 15
                else: self.map_zoom = int(min(18, max(1, 8 - math.log2(max(lat_diff, lon_diff)))))
                self.map_cursor_x = CONCEPTUAL_MAP_WIDTH // 2
                self.map_cursor_y = CONCEPTUAL_MAP_HEIGHT // 2
        elif event_type == Event.MAP_CYCLE_CHARSET:
            self.map_char_set_index = (self.map_char_set_index + 1) % len(self.map_char_sets)
        elif event_type == Event.MAP_CYCLE_TILE_SOURCE:
            self.map_source_index = (self.map_source_index + 1) % len(self.map_sources)

        return True
        
    def get_node_list(self):
        """
        Return a list of current nodes for display in the TUI.
        """
        return list(self.nodes.values())
        
    def _get_char_for_pixel(self, r, g, b, char_set):
        if b > r and b > g and b > 120: return ('class:map.water', char_set["water"])
        if g > r and g > b and g > 100: return ('class:map.land', char_set["park"])
        if r > 200 and g > 150 and b < 100: return ('class:map.structure', char_set["road"])
        if abs(r - g) < 20 and abs(g - b) < 20 and r > 50: return ('class:map.structure', char_set["building"])
        return ('class:text-area', char_set["land"])

    def get_ascii_map(self, width, height):
        if self.map_zoom is None or self.map_center_lat is None:
             return [("class:message.error", "Initializing map...")]

        char_set_name, char_set = self.map_char_sets[self.map_char_set_index]
        map_source_name, map_url_template = self.map_sources[self.map_source_index]
        
        cache_key = (self.map_zoom, round(self.map_center_lat, 4), round(self.map_center_lon, 4), char_set_name, map_source_name, width, height)
        if cache_key in self._map_cache:
            grid = self._map_cache[cache_key]
        else:
            try:
                xtile, ytile = deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom)
                
                url = map_url_template.format(z=self.map_zoom, x=xtile, y=ytile)
                logging.info(f"Fetching map tile: {url}")
                response = requests.get(url, headers={'User-Agent': 'Meshtastic-TUI/1.0'}, timeout=10)
                response.raise_for_status()
                tile_img = Image.open(BytesIO(response.content)).convert("RGB")
                
                if map_source_name == "Toner":
                    tile_img = ImageEnhance.Contrast(tile_img.convert('L')).enhance(2.0).convert("RGB")

                resized_img = tile_img.resize((width, height), Image.Resampling.LANCZOS)
                pixels = resized_img.load()

                grid = []
                for y in range(height):
                    row = []
                    for x in range(width):
                        style, char = self._get_char_for_pixel(*pixels[x, y], char_set)
                        if char == ' ' and style != 'class:map.water': style = 'class:map.water'
                        row.append((style, char))
                    grid.append(row)
                
                self._map_cache[cache_key] = grid

            except Exception as e:
                logging.error(f"Failed to generate map: {e}", exc_info=True)
                return [("class:message.error", f"Could not generate map: {e}")]
        
        display_grid = [row[:] for row in grid]
        
        nodes_with_gps = [n for n in self.nodes.values() if n.get('latitude') and n.get('longitude')]
        top_left_lat, top_left_lon = num2deg(*deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom), self.map_zoom)
        bottom_right_lat, bottom_right_lon = num2deg(deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom)[0] + 1, deg2num(self.map_center_lat, self.map_center_lon, self.map_zoom)[1] + 1, self.map_zoom)
        tile_lat_range = abs(top_left_lat - bottom_right_lat)
        tile_lon_range = abs(bottom_right_lon - top_left_lon)

        for node in nodes_with_gps:
            if tile_lon_range == 0 or tile_lat_range == 0: continue
            
            char_x = int(((node['longitude'] - top_left_lon) / tile_lon_range) * width)
            char_y = int(((top_left_lat - node['latitude']) / tile_lat_range) * height)

            if 0 <= char_y < height and 0 <= char_x < width:
                style = "class:node.notification" if node['id'] == self.my_node_num else "class:message.error"
                marker = '★' if node['id'] == self.my_node_num else '●'
                display_grid[char_y][char_x] = (style, marker)
        
        if self.map_cursor_x is not None and self.map_cursor_y is not None:
            cursor_x_clamped = min(self.map_cursor_x, width - 1)
            cursor_y_clamped = min(self.map_cursor_y, height - 1)
            if cursor_y_clamped < len(display_grid) and cursor_x_clamped < len(display_grid[0]):
                display_grid[cursor_y_clamped][cursor_x_clamped] = ('class:statusbar reverse', '+')

        result = []
        for row in display_grid:
            result.extend(row)
            result.append(('', '\n'))
        
        return result

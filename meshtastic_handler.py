import time
import logging
import queue
from enum import Enum, auto

import meshtastic
import meshtastic.serial_interface
from meshtastic.protobuf import mesh_pb2, portnums_pb2
from pubsub import pub

from app_state import Event

class HandlerState(Enum):
    """Represents the internal state of the Meshtastic handler."""
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()

class MeshtasticHandler:
    """Handles all interactions with the Meshtastic device in a separate thread."""

    def __init__(self, command_queue: queue.Queue, update_queue: queue.Queue, app):
        logging.info("Meshtastic handler initialized.")
        self.command_queue = command_queue
        self.update_queue = update_queue
        self.app = app # Store the prompt_toolkit Application object
        self.interface = None
        self._is_running = True
        self._handler_state = HandlerState.DISCONNECTED
        self.ack_nak_requests = {}

    def stop(self):
        """Signals the handler's main loop to exit."""
        self._is_running = False

    def _trigger_redraw(self):
        """Thread-safely tells the UI that it needs to redraw."""
        if self.app:
            self.app.invalidate()

    def run(self):
        """The main loop for the handler thread. Processes commands from the TUI."""
        logging.info("Meshtastic handler thread started.")
        while self._is_running:
            try:
                event_type, data = self.command_queue.get(timeout=1.0)
                if event_type == Event.SET_PORT: self._connect_to_device(data)
                elif event_type == Event.SEND_TEXT: self._send_text_message(data[0], data[1])
                elif event_type == Event.SEND_TRACEROUTE: self._send_traceroute(data)
                elif event_type == Event.TUI_EXIT: self.stop()
            except queue.Empty:
                continue
            except Exception as e:
                logging.critical(f"Unhandled exception in handler command loop: {e}", exc_info=True)
        self._cleanup_connection()
        logging.info("Meshtastic handler thread terminated.")

    def _connect_to_device(self, port: str):
        if self._handler_state != HandlerState.DISCONNECTED: return
        self._cleanup_connection()
        self._handler_state = HandlerState.CONNECTING
        self.update_queue.put((Event.CONNECTION_STATUS, ("Connecting...", f"to {port}", False)))
        self._trigger_redraw()
        try:
            pub.subscribe(self._on_connection_change, "meshtastic.connection.established")
            pub.subscribe(self._on_connection_change, "meshtastic.connection.lost")
            self.interface = meshtastic.serial_interface.SerialInterface(port)
        except Exception as e:
            self._handle_error(f"Failed to create SerialInterface on '{port}': {e}",
                               (Event.CONNECTION_STATUS, ("Connection Failed", str(e), False)))
            self._cleanup_connection()

    def _cleanup_connection(self):
        if self.interface:
            try: pub.unsubAll(); self.interface.close()
            except Exception as e: logging.error(f"Error during interface cleanup: {e}", exc_info=True)
            finally: self.interface = None
        self._handler_state = HandlerState.DISCONNECTED
        self.update_queue.put((Event.CONNECTION_STATUS, ("Disconnected", "Select port", False)))
        self._trigger_redraw()

    def _send_text_message(self, text: str, destination_id: int):
        if self._handler_state != HandlerState.CONNECTED:
            self.update_queue.put((Event.LOG_ERROR, "Cannot send: Not connected.")); self._trigger_redraw(); return
        message_id = f"msg_{time.time_ns()}"
        self.update_queue.put((Event.MESSAGE_SENT, (message_id, text, destination_id))); self._trigger_redraw()
        try:
            sent_packet = self.interface.sendText(text=text, destinationId=destination_id, wantAck=True, onResponse=self._on_ack_nak)
            if sent_packet and sent_packet.id: self.ack_nak_requests[sent_packet.id] = message_id
        except Exception as e: self._handle_error(f"Failed to send message: {e}", (Event.MESSAGE_DELIVERY_STATUS, (message_id, "FAILED")))

    def _send_traceroute(self, destination_id: int):
        if self._handler_state != HandlerState.CONNECTED:
            self.update_queue.put((Event.LOG_ERROR, "Cannot send traceroute: Not connected.")); self._trigger_redraw(); return
        try:
            request = mesh_pb2.RouteDiscovery()
            self.interface.sendData(request, destinationId=destination_id, portNum=portnums_pb2.PortNum.TRACEROUTE_APP,
                                    wantResponse=True, onResponse=self._on_traceroute_response)
        except Exception as e: self._handle_error(f"Failed to send traceroute: {e}")

    def _handle_error(self, log_message, update_event=None):
        logging.error(log_message, exc_info=True)
        self.update_queue.put((Event.LOG_ERROR, log_message.split(":")[-1].strip()))
        if update_event: self.update_queue.put(update_event)
        self._trigger_redraw()

    def _on_receive(self, packet, interface): self.update_queue.put((Event.PACKET_RECEIVED, packet)); self._trigger_redraw()
    def _on_node_update(self, node): self.update_queue.put((Event.SINGLE_NODE_UPDATE, node)); self._trigger_redraw()
    def _on_traceroute_response(self, packet): self.update_queue.put((Event.TRACEROUTE_RESPONSE_RECEIVED, packet)); self._trigger_redraw()

    def _on_ack_nak(self, packet):
        request_id = packet.get("requestId")
        if request_id in self.ack_nak_requests:
            message_id = self.ack_nak_requests.pop(request_id)
            status = "DELIVERED" if packet.get("decoded", {}).get("routing", {}).get("errorReason", "NONE") == "NONE" else "FAILED"
            self.update_queue.put((Event.MESSAGE_DELIVERY_STATUS, (message_id, status))); self._trigger_redraw()

    def _on_connection_change(self, interface, topic=pub.AUTO_TOPIC):
        topic_name = topic.getName()
        logging.info(f"Connection event from device on topic: {topic_name}")
        if "established" in topic_name:
            try:
                pub.subscribe(self._on_receive, "meshtastic.receive")
                pub.subscribe(self._on_node_update, "meshtastic.node.updated")
                my_info = interface.getMyNodeInfo()
                nodes = interface.nodes
                self.update_queue.put((Event.MY_INFO_UPDATE, my_info))
                self.update_queue.put((Event.NODES_UPDATE, nodes))
                self._handler_state = HandlerState.CONNECTED
                details = f"as {my_info.get('user', {}).get('longName', 'Unknown')}"
                self.update_queue.put((Event.CONNECTION_STATUS, ("Connected", details, True)))
                self._trigger_redraw()
            except Exception as e: self._handle_error(f"Error post-connection: {e}"); self._cleanup_connection()
        elif "lost" in topic_name:
            self.update_queue.put((Event.LOG_ERROR, "Device disconnected unexpectedly.")); self._cleanup_connection()

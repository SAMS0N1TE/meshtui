import time
import logging
import queue
from enum import Enum, auto
import platform
import subprocess
import serial

# Conditional import for termios, as it's Unix-specific
if platform.system() != "Windows":
    import termios
else:
    # On Windows, define a dummy termios error for consistent error handling
    class TermiosError(Exception):
        pass
    termios = type('termios', (object,), {'error': TermiosError})()


import meshtastic
import meshtastic.serial_interface
import meshtastic.mesh_interface
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
        self.app = app
        self.interface = None
        self._is_running = True
        self._handler_state = HandlerState.DISCONNECTED
        self.ack_nak_requests = {}

    def stop(self):
        self._is_running = False

    def _trigger_redraw(self):
        if self.app:
            self.app.invalidate()

    def run(self):
        logging.info("Meshtastic handler thread started.")
        while self._is_running:
            try:
                event_type, data = self.command_queue.get(timeout=1.0)
                logging.info(f"[HANDLER] Received command: {event_type.name} with data: {data}")
                if event_type == Event.SET_PORT:
                    self._connect_to_device(data)
                elif event_type == Event.SEND_TEXT:
                    self._send_text_message(data[0], data[1])
                elif event_type == Event.SEND_TRACEROUTE:
                    self._send_traceroute(data)
                elif event_type == Event.TUI_EXIT:
                    self.stop()
            except queue.Empty:
                continue
            except Exception as e:
                logging.critical(f"Unhandled exception in handler command loop: {e}", exc_info=True)
        self._cleanup_connection()
        logging.info("Meshtastic handler thread terminated.")

    def _connect_to_device(self, port: str):
        if self._handler_state != HandlerState.DISCONNECTED:
            logging.warning(f"Connection requested while in state {self._handler_state}. Ignoring.")
            return

        self._cleanup_connection()
        self._handler_state = HandlerState.CONNECTING
        self.update_queue.put((Event.CONNECTION_STATUS, ("Connecting...", f"to {port}", False)))
        self._trigger_redraw()
        try:
            pub.subscribe(self._on_connection_change, "meshtastic.connection.established")
            pub.subscribe(self._on_connection_change, "meshtastic.connection.lost")
            self.interface = meshtastic.serial_interface.SerialInterface(port)
        except meshtastic.mesh_interface.MeshInterface.MeshInterfaceError as e:
            error_msg = f"Timed out connecting to {port}. Check cable or reboot device."
            self._handle_error(error_msg, (Event.CONNECTION_STATUS, ("Timeout", "Device not responding", False)))
            self._cleanup_connection()
        except termios.error as e: # This will now only be caught on Unix-like systems
            error_msg = f"OS Error on port {port}: {e}. Check permissions (are you in the 'dialout' group?) or if the device is valid."
            self._handle_error(error_msg,
                               (Event.CONNECTION_STATUS, ("OS Error", "Check permissions", False)))
            self._cleanup_connection()
        except serial.serialutil.SerialException as e:
            self._handle_serial_error(port, e)
            self._cleanup_connection()
        except Exception as e:
            self._handle_error(f"Failed to create SerialInterface on '{port}': {e}",
                               (Event.CONNECTION_STATUS, ("Connection Failed", str(e), False)))
            self._cleanup_connection()

    def _cleanup_connection(self):
        if self.interface:
            try:
                pub.unsubAll()
                self.interface.close()
                # FIX: Add a small delay to give the OS time to release the serial port lock.
                # This prevents a race condition where the app tries to reconnect to a port
                # that it just closed but which the OS hasn't fully released yet.
                time.sleep(0.25)
                logging.info("Interface closed and OS given time to release lock.")
            except Exception as e:
                logging.error(f"Error during interface cleanup: {e}", exc_info=True)
            finally:
                self.interface = None

        # This should only be done once after cleanup is complete.
        if self._handler_state != HandlerState.DISCONNECTED:
            self._handler_state = HandlerState.DISCONNECTED
            self.update_queue.put((Event.CONNECTION_STATUS, ("Disconnected", "Select port", False)))
            self._trigger_redraw()

    def _send_text_message(self, text: str, destination_id: int):
        if self._handler_state != HandlerState.CONNECTED:
            self.update_queue.put((Event.LOG_ERROR, "Cannot send: Not fully connected.")); self._trigger_redraw(); return
        message_id = f"msg_{time.time_ns()}"
        self.update_queue.put((Event.MESSAGE_SENT, (message_id, text, destination_id))); self._trigger_redraw()
        try:
            sent_packet = self.interface.sendText(text=text, destinationId=destination_id, wantAck=True, onResponse=self._on_ack_nak)
            if sent_packet and sent_packet.id: self.ack_nak_requests[sent_packet.id] = message_id
        except Exception as e: self._handle_error(f"Failed to send message: {e}", (Event.MESSAGE_DELIVERY_STATUS, (message_id, "FAILED")))

    def _send_traceroute(self, destination_id: int):
        if self._handler_state != HandlerState.CONNECTED:
            self.update_queue.put((Event.LOG_ERROR, "Cannot send traceroute: Not fully connected.")); self._trigger_redraw(); return
        logging.info(f"[HANDLER] Sending traceroute request to node {destination_id}")
        self.update_queue.put((Event.LOG_ERROR, f"Sending traceroute to node !{destination_id:x}...")); self._trigger_redraw()
        try:
            request = mesh_pb2.RouteDiscovery()
            self.interface.sendData(request, destinationId=destination_id, portNum=portnums_pb2.PortNum.TRACEROUTE_APP,
                                    wantResponse=True, onResponse=self._on_traceroute_response, hopLimit=7)
        except Exception as e: self._handle_error(f"Failed to send traceroute data: {e}")

    def _handle_error(self, log_message, update_event=None):
        logging.error(log_message, exc_info=True)
        self.update_queue.put((Event.LOG_ERROR, log_message.split(":")[-1].strip()))
        if update_event: self.update_queue.put(update_event)
        self._trigger_redraw()

    def _handle_serial_error(self, port, e):
        if "Could not exclusively lock port" in str(e) and platform.system() == "Linux":
            try:
                pid_proc = subprocess.run(["fuser", port], capture_output=True, text=True)
                pids = pid_proc.stdout.strip().split()
                if pids:
                    pid = pids[0]
                    name_proc = subprocess.run(["ps", "-p", pid, "-o", "comm="], capture_output=True, text=True)
                    p_name = name_proc.stdout.strip()
                    error_msg = f"Port {port} is locked by '{p_name}' (PID: {pid}). Run: sudo kill {pid}"
                    self.update_queue.put((Event.LOG_ERROR, error_msg))
                    self.update_queue.put((Event.CONNECTION_STATUS, ("Port Locked", p_name, False)))
                    self._trigger_redraw()
                    return
            except (FileNotFoundError, Exception) as cmd_err: logging.error(f"Could not run 'fuser' or 'ps': {cmd_err}")
        self._handle_error(f"Serial Error on '{port}': {e}", (Event.CONNECTION_STATUS, ("Serial Error", str(e), False)))

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
                self._handler_state = HandlerState.CONNECTED
                logging.info("Handler state is now CONNECTED.")
                pub.subscribe(self._on_receive, "meshtastic.receive")
                pub.subscribe(self._on_node_update, "meshtastic.node.updated")
                my_info = interface.getMyNodeInfo()
                self.update_queue.put((Event.MY_INFO_UPDATE, my_info))
                self.update_queue.put((Event.NODES_UPDATE, interface.nodes))
                details = f"as {my_info.get('user', {}).get('longName', 'Unknown')}"
                self.update_queue.put((Event.CONNECTION_STATUS, ("Connected", details, True)))
                self._trigger_redraw()
            except Exception as e: self._handle_error(f"Error post-connection: {e}"); self._cleanup_connection()
        elif "lost" in topic_name:
            self.update_queue.put((Event.LOG_ERROR, "Device disconnected unexpectedly.")); self._cleanup_connection()

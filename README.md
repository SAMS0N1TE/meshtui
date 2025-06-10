# meshtui

A terminal-based interactive chat interface for Meshtastic LoRa devices. `meshtui` provides a curses-powered UI for real-time messaging, device discovery, and per-node direct messaging, all within the Linux terminal. I made this to help in the devlopment process when I realized I needed a nice and easy way to send messages over SSH from other devices.

---

## Features

- Real-time chat over Meshtastic LoRa mesh networks
- Automatically discovers nearby nodes and channels
- Broadcast and direct messaging (DM)
- Channel switching via keyboard shortcuts
- Dynamic serial port detection and connection management
- Logfile-based debug output
- Responsive TUI layout with panels for messages, nodes, status, and input

---

## Screenshot

![Screenshot](screenshots/meshtui-preview.png)

---

## Installation

### Requirements

- Python 3.7+
- Meshtastic Python API
- `pyserial`
- `pubsub`
- `curses` (built-in for Unix/Linux platforms)

### Install with `pip`

```bash
pip install meshtastic pyserial pypubsub

![Screenshot](screenshots/uconsole.jpg)

# Meshtastic TUI

A cross-platform terminal user interface (TUI) for Meshtastic radios, written in Python using `prompt_toolkit`.  
Control, chat, and manage nodes on your Meshtastic mesh network. Features dynamic serial port detection, node monitoring, and direct messaging.


![Screenshot](screenshots/theme2.png)
---

## Features

- **Real-Time Meshtastic Chat:** Send/receive broadcast and direct (DM) messages.
- **Dynamic Serial Port Selection:** Auto-detect all available serial ports, switch via TUI.
- **Node List Monitoring:** View nodes, SNR, last-heard, and select for DM or traceroute.
- **Message Status:** Shows delivery and error status.
- **Custom Theme/Keybinds:** Color scheme and efficient navigation.

---
![Screenshot](screenshots/theme3.png)


# Meshtui Installation Guide

This guide will walk you through the steps to install and run **meshtui**, a terminal user interface for Meshtastic.

---

## Prerequisites

Before you begin, make sure you have the following installed on your system:

* **Python 3.8 or higher:**
  Check your Python version:

  ```bash
  python3 --version
  ```

* **Git:**
  Required to clone the project repository.

---

## Installation Steps

Follow these instructions to get **meshtui** set up:

### 1. Clone the Repository

Open your terminal and run:

```bash
git clone https://github.com/SAMS0N1TE/meshtui.git
cd meshtui
```

---

### 2. Create a Virtual Environment (Recommended)

Use a virtual environment to keep dependencies isolated:

```bash
python3 -m venv .venv
```

---

### 3. Activate the Virtual Environment

**On Linux/macOS:**

```bash
source .venv/bin/activate
```

**On Windows (Command Prompt):**

```dos
.venv\Scripts\activate.bat
```

**On Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
```

---

### 4. Install Meshtui

With your virtual environment active, install the project:

```bash
pip install .
```

---

## Running Meshtui

After installation, launch meshtui by running:

```bash
meshtui
```

(Ensure your virtual environment is active.)

---

## Deactivating the Virtual Environment

When finished, deactivate the virtual environment:

```bash
deactivate
```


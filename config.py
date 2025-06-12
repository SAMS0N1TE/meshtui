import logging
from prompt_toolkit.styles import Style

def setup_logging():
    """Configures application-wide logging."""
    logging.basicConfig(
        level=logging.INFO, # Change to DEBUG for more verbose output
        format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
        filename='meshtastic_tui.log',
        filemode='w'
    )

# Defines the color scheme and styles for the TUI
TUI_STYLE = Style.from_dict({
    "frame": "bg:#2b2b2b fg:ansiwhite",
    "frame.border": "fg:ansiwhite",
    "frame.label": "fg:ansired bold",
    "header": "bg:ansired fg:ansiblack",
    "statusbar": "bg:#c9c9c9 fg:ansiblack",
    "text-area": "bg:ansiwhite fg:ansiblack",
    "text-area.prompt": "fg:ansicyan",
    "list.item.selected": "bg:ansiwhite fg:ansiblack",
    "message.local": "fg:ansicyan",
    "message.remote": "fg:ansiwhite",
    "message.dm": "fg:ansibrightmagenta",
    "message.error": "fg:ansired bold",
    "node.notification": "fg:ansiyellow bold",
})

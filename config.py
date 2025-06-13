import logging

def setup_logging():
    """Configures application-wide logging."""
    logging.basicConfig(
        level=logging.DEBUG, # Use DEBUG for detailed troubleshooting
        format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
        filename='meshtastic_tui.log',
        filemode='w'
    )

# The static TUI_STYLE dictionary has been removed from here.
# Themes are now loaded dynamically from themes.py.

import logging

def setup_logging():
    """Configures application-wide logging."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
        filename='meshtastic_tui.log',
        filemode='w'
    )

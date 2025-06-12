import queue
import logging
from threading import Thread

from config import setup_logging
from app_state import AppState
from tui import MeshtasticTUI
from meshtastic_handler import MeshtasticHandler

def main():
    """Initializes and runs the Meshtastic TUI application."""
    setup_logging()
    logging.info("Application starting up.")

    command_queue = queue.Queue()  # For TUI -> Handler commands
    update_queue = queue.Queue()   # For Handler -> TUI state updates
    app_state = AppState()

    # The TUI must be created first so we have access to its app object.
    tui = MeshtasticTUI(app_state, command_queue, update_queue)

    # The handler is now given the TUI's app object so it can trigger redraws.
    handler = MeshtasticHandler(command_queue, update_queue, tui.app)

    # Start the Meshtastic handler in a background thread
    meshtastic_thread = Thread(
        target=handler.run,
        name="MeshtasticThread",
        daemon=True
    )
    meshtastic_thread.start()

    # Run the TUI. This is a blocking call.
    tui.run()

    # TUI has exited, so we should stop the handler
    logging.info("TUI exited. Shutting down Meshtastic handler.")
    handler.stop()
    meshtastic_thread.join(timeout=2)
    logging.info("Application shut down.")

if __name__ == "__main__":
    main()

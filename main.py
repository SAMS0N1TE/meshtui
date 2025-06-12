import queue
import logging
from threading import Thread

from config import setup_logging
from app_state import AppState
from tui import MeshtasticTUI
from meshtastic_handler import MeshtasticHandler

def main():
    setup_logging()
    logging.info("Application starting up.")

    command_queue = queue.Queue()  # For TUI -> Handler commands
    update_queue = queue.Queue()   # For Handler -> TUI state updates
    app_state = AppState()

    tui = MeshtasticTUI(app_state, command_queue, update_queue)

    handler = MeshtasticHandler(command_queue, update_queue, tui.app)

    # Start the Meshtastic handler in a background thread
    meshtastic_thread = Thread(
        target=handler.run,
        name="MeshtasticThread",
        daemon=True
    )
    meshtastic_thread.start()

    tui.run()

    logging.info("TUI exited. Shutting down Meshtastic handler.")
    handler.stop()
    meshtastic_thread.join(timeout=2)
    logging.info("Application shut down.")

if __name__ == "__main__":
    main()

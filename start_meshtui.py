#!/usr/bin/env python3
import asyncio, os, sys, logging
from pathlib import Path

# Always run from the executable/script directory
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)).resolve()
os.chdir(BASE)
sys.path.insert(0, str(BASE))

# Minimal logfile next to the exe
logging.basicConfig(
    filename=str(BASE / "meshtui.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# Fix common Win asyncio issues (serial etc.)
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
    except Exception:
        pass

from meshtui.main import main  # your async entrypoint

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.exception("Fatal error")
        print(f"Fatal error: {e}")
        if not sys.stdin.closed:
            input("Press ENTER to exit...")
        raise

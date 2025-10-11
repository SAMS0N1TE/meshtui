# meshtui/main.py
from meshtui.core.state import AppState
from meshtui.core.bus import Bus
from meshtui.ui_ptk.app import build_app  # or whatever your app factory is named

def main():
    state = AppState()
    bus = Bus()
    app = build_app(state, bus)
    import asyncio
    asyncio.run(app.run_async())

if __name__ == "__main__":
    main()

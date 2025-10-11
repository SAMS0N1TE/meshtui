# meshtui/ui_ptk/bind.py
from prompt_toolkit.key_binding import KeyBindings
from meshtui.ui_ptk.selectors import choose_dm_node
from meshtui.ui_ptk import dialogs
from meshtui.core.meshtastic_io import BROADCAST
from meshtui.transport import send_with_ack


def build_keybindings(state, actions, iface, bus, input_box):
    kb = KeyBindings()

    @kb.add("c-c")
    def _(event):
        event.app.exit()

    @kb.add("enter")
    def _(event):
        text = input_box.text.strip()
        if not text:
            return
        dest = state.dm_target if state.dm_target is not None else BROADCAST

        async def send_task():
            await send_with_ack(state, iface, dest, text)
            event.app.invalidate()

        event.app.create_background_task(send_task())
        input_box.buffer.reset()
        event.app.invalidate()


    @kb.add("f2")
    def _(event):
        event.app.create_background_task(choose_dm_node(event.app, state))

    @kb.add("f3")
    def _(event):
        state.set_dm(None)
        state.add_log("DM cleared")
        event.app.invalidate()

    @kb.add("f8")
    def _(event):
        event.app.create_background_task(dialogs.connect_port(event.app, state, iface))

    # This keybinding is not used, but is kept for reference
    @kb.add("c-n")
    def _(event):
        # Placeholder for a future node settings dialog
        pass

    # helper to schedule callables from buttons
    def call_from_executor(fn, *args):
        event = getattr(kb, "_last_event", None)
        app = event.app if event else None
        if app:
            app.create_background_task(fn(*args))

    kb.call_from_executor = call_from_executor  # attach helper

    return kb
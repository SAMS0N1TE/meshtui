# meshtui/ui_ptk/selectors.py
from prompt_toolkit.shortcuts.dialogs import radiolist_dialog, checkboxlist_dialog, message_dialog

async def choose_dm_node(app, state):
    nodes = state.ordered_nodes()
    if not nodes:
        await message_dialog(title="No Nodes", text="No nodes available.").run_async()
        return
    values = [(n["num"], f"{n['short']}  #{n['num']}") for n in nodes]
    sel = await radiolist_dialog(title="Select DM Node", text="Choose a node:", values=values).run_async()
    if sel is None:
        return
    state.set_dm(int(sel))
    state.add_log(f"DM target set to #{sel}")
    app.invalidate()

async def choose_channels(app, state):
    if not state.channels:
        await message_dialog(title="No Channels", text="No channels configured.").run_async()
        return
    values = [(i, name) for i, name in state.channels]
    chosen = await checkboxlist_dialog(title="Active Channels", text="Enable channels:", values=values).run_async()
    if chosen is None:
        return
    state.set_active_channels([int(i) for i in chosen])
    state.add_log("Active channels: " + ",".join(str(i) for i in sorted(state.active_channels)))
    app.invalidate()
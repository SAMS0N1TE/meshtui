# meshtui/ui_ptk/status.py
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window

def status_view(state, theme_name_provider):
    def _line():
        dm = f"DM: #{state.dm_target:x}" if state.dm_target is not None else "DM: BROADCAST"
        ch = "CH: " + (",".join(str(i) for i in sorted(state.active_channels)) if state.active_channels else "-")
        tn = f"Theme: {theme_name_provider()}"
        return f"{dm}   {ch}   {tn}"
    return Window(content=FormattedTextControl(_line), height=1, always_hide_cursor=True, style="class:statusbar")
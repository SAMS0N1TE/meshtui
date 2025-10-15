# meshtui/ui_ptk/controls.py
from prompt_toolkit.layout import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.application import get_app
from prompt_toolkit.mouse_events import MouseEventType


class FlatButtonWindow(Window):
    def __init__(self, label: str, on_click):
        self.label = label
        self.on_click = on_click
        self._hover = False
        self._pressed = False

        def _fragments():
            style = "class:btn"
            if self._hover:
                style = "class:btn.hover"
            if self._pressed:
                style = "class:btn.active"
            return [(style, f" {self.label} ", _handler)]

        def _handler(me):
            t = me.event_type

            # Ignore wheel events so containers can scroll without crashing.
            if t in (MouseEventType.SCROLL_UP, MouseEventType.SCROLL_DOWN):
                return NotImplemented

            if t == MouseEventType.MOUSE_MOVE:
                if not self._hover:
                    self._hover = True
                    get_app().invalidate()
                return None

            if t == MouseEventType.MOUSE_DOWN:
                self._pressed = True
                get_app().invalidate()
                return None

            if t == MouseEventType.MOUSE_UP:
                was_pressed = self._pressed
                self._pressed = False
                # Best-effort hover reset when mouse up occurs outside.
                self._hover = False
                get_app().invalidate()
                if was_pressed and callable(self.on_click):
                    self.on_click()
                return None

            # For any other mouse events, don't handle.
            return NotImplemented

        super().__init__(
            content=FormattedTextControl(_fragments, focusable=True),
            height=1,
            dont_extend_width=True,  # keep button compact; VSplit won't stretch it
        )


def FlatButton(label: str, on_click):
    """Backward-compat alias used by layout code."""
    return FlatButtonWindow(label, on_click)
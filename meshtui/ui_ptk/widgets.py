# meshtui/ui_ptk/widgets.py
from prompt_toolkit.layout import Window
from prompt_toolkit.layout.controls import UIControl, UIContent
from prompt_toolkit.data_structures import Point
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.application import get_app

class _SplitterControl(UIControl):
    def __init__(self, is_vertical: bool, getter, setter):
        self.is_vertical = is_vertical
        self.getter = getter
        self.setter = setter

    def create_content(self, width: int, height: int) -> UIContent:
        ch = "│" if self.is_vertical else "─"
        if self.is_vertical:
            # height lines, 1 column
            def get_line(i: int):
                return [("class:frame.border", ch)]
            return UIContent(get_line=get_line, line_count=max(1, height), cursor_position=Point(0, 0))
        else:
            # one line, width chars
            line_text = ch * max(1, width)
            def get_line(i: int):
                return [("class:frame.border", line_text)]
            return UIContent(get_line=get_line, line_count=1, cursor_position=Point(0, 0))

    def mouse_handler(self, mouse_event: MouseEvent):
        r = float(self.getter())
        t = mouse_event.event_type
        if t == MouseEventType.SCROLL_UP:
            self.setter(min(0.9, r + 0.02))
            get_app().invalidate()
            return None
        if t == MouseEventType.SCROLL_DOWN:
            self.setter(max(0.1, r - 0.02))
            get_app().invalidate()
            return None
        if t == MouseEventType.MOUSE_DOWN:
            presets = [0.25, 0.35, 0.5, 0.65, 0.75]
            try:
                idx = presets.index(min(presets, key=lambda x: abs(x - r)))
                self.setter(presets[(idx + 1) % len(presets)])
            except Exception:
                self.setter(0.5)
            get_app().invalidate()
            return None
        return NotImplemented


def v_splitter(getter, setter):
    return Window(width=1, content=_SplitterControl(True, getter, setter))

def h_splitter(getter, setter):
    return Window(height=1, content=_SplitterControl(False, getter, setter))
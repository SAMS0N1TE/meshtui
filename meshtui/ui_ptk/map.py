# meshtui/ui_ptk/map.py
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window
from typing import Dict, Tuple

def _project(lat: float, lon: float) -> Tuple[int, int]:
    x = int((lon + 180) * 0.25)
    y = int((90 - lat) * 0.25)
    return x, y

def build_map(state):
    def _render() -> str:
        width, height = 80, 24
        canvas = [[" " for _ in range(width)] for _ in range(height)]
        for node in state.ordered_nodes():
            pos = node.get("pos")
            if not pos:
                continue
            x, y = _project(pos.get("lat", 0.0), pos.get("lon", 0.0))
            if 0 <= x < width and 0 <= y < height:
                canvas[min(height - 1, y)][min(width - 1, x)] = "*"
        return "\n".join("".join(r) for r in canvas)
    return Window(content=FormattedTextControl(_render), wrap_lines=False, always_hide_cursor=True)

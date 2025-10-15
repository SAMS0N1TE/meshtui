# meshtui/core/config.py
import os, json
from dataclasses import dataclass, asdict

DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".meshtui.json")

@dataclass
class Config:
    theme: str | None = None
    last_port: str | None = None
    baud_rate: int | None = None
    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_tls: bool = False
    active_channels: list[int] = None
    split_left: float = 0.35           # 0..1 width of left column
    split_nodes_log: float = 0.65      # 0..1 height of nodes vs log in left column, i hate you nodes window
    last_tab: str = "Chat"

    @staticmethod
    def load(path: str = DEFAULT_PATH) -> "Config":
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        return Config(
            theme=data.get("theme"),
            last_port=data.get("last_port"),
            baud_rate=data.get("baud_rate"),
            mqtt_enabled=bool(data.get("mqtt_enabled", False)),
            mqtt_host=data.get("mqtt_host", "localhost"),
            mqtt_port=int(data.get("mqtt_port", 1883)),
            mqtt_tls=bool(data.get("mqtt_tls", False)),
            active_channels=[int(x) for x in data.get("active_channels", [])],
            split_left=float(data.get("split_left", 0.35)),
            split_nodes_log=float(data.get("split_nodes_log", 0.65)),
            last_tab=str(data.get("last_tab", "Chat")),
        )

    def save(self, path: str = DEFAULT_PATH) -> None:
        data = asdict(self)
        data["active_channels"] = list(self.active_channels or [])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def is_ready(self) -> bool:
        return bool(self.last_port)

def apply_to_state(cfg: "Config", state) -> None:
    if getattr(cfg, "active_channels", None):
        state.set_active_channels(cfg.active_channels)
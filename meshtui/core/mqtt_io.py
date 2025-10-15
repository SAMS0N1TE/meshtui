# meshtui/core/mqtt_io.py
import asyncio
from meshtui.core.events import Log

async def run_mqtt(bus, client):
    loop = asyncio.get_running_loop()

    def on_connect(client, userdata, flags, rc):
        txt = f"MQTT connected rc={rc}"
        asyncio.run_coroutine_threadsafe(bus.emit(Log(text=txt)), loop)

    def on_message(client, userdata, msg):
        txt = f"MQTT {msg.topic}: {msg.payload.decode(errors='ignore')[:200]}"
        asyncio.run_coroutine_threadsafe(bus.emit(Log(text=txt)), loop)

    def on_disconnect(client, userdata, rc):
        txt = f"MQTT disconnected rc={rc}"
        asyncio.run_coroutine_threadsafe(bus.emit(Log(text=txt)), loop)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.loop_start()

    while True:
        await asyncio.sleep(1)

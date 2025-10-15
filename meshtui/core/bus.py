# meshtui/core/bus.py
import asyncio
from typing import Any, AsyncGenerator

class Bus:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()

    async def emit(self, event: Any):
        await self._queue.put(event)

    async def listen(self) -> AsyncGenerator[Any, None]:
        while True:
            ev = await self._queue.get()
            yield ev

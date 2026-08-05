import asyncio
from typing import Optional


class FloorManager:
    def __init__(self):
        self.floor_holder: Optional[str] = None
        self._lock = asyncio.Lock()

    async def request_floor(self, requester_pubkey: str):
        async with self._lock:
            if self.floor_holder is None:
                self.floor_holder = requester_pubkey

    async def yield_floor(self):
        async with self._lock:
            self.floor_holder = None

    async def has_floor(self, pubkey: str) -> bool:
        return self.floor_holder == pubkey

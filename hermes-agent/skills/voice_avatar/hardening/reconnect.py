import asyncio


class ReconnectionManager:
    def __init__(self, pc, sfu_client, nostr_client, max_retries=3):
        self.pc = pc
        self.sfu = sfu_client
        self.nostr = nostr_client
        self.max_retries = max_retries
        self._retry_count = 0

    def attach(self):
        self.pc.on("connectionstatechange", self._on_pc_state_change)
        self.sfu.on("disconnected", self._on_sfu_disconnect)
        self.nostr.on("relay_drop", self._on_relay_drop)

    async def _on_pc_state_change(self, state: str):
        if state == "failed":
            await self._ice_restart()
        elif state == "disconnected":
            await asyncio.sleep(5)
            if self.pc.connectionState == "disconnected":
                await self._ice_restart()

    async def _ice_restart(self):
        if self._retry_count >= self.max_retries:
            await self._fallback_to_data_only()
            return
        self._retry_count += 1
        try:
            offer = await self.pc.createOffer(ice_restart=True)
            await self.pc.setLocalDescription(offer)
        except Exception:
            await self._fallback_to_data_only()

    async def _fallback_to_data_only(self):
        for sender in self.pc.getTransceivers():
            if sender.direction == "sendrecv":
                sender.direction = "inactive"

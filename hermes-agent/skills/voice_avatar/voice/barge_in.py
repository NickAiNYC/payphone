import time


class BargeInCoordinator:
    def __init__(self, tts_provider, vad_provider, avatar_state_machine):
        self.tts = tts_provider
        self.vad = vad_provider
        self.avatar = avatar_state_machine

    async def on_vad_speech_start(self):
        start_time = time.time()
        await self.tts.cancel()
        latency_ms = (time.time() - start_time) * 1000
        if latency_ms < 150:
            self.avatar.barge_in()

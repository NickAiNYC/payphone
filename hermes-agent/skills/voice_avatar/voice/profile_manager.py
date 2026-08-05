class VoiceProfileManager:
    def __init__(self, nostr_client, skill_ctx):
        self.nostr = nostr_client
        self.ctx = skill_ctx
        self.current_profile = self._load_defaults()

    def _load_defaults(self):
        return {
            "stt": {"provider": "faster-whisper", "model": "large-v3"},
            "tts": {"provider": "piper", "voice": "en_US-ryan-high"},
            "vad": {"provider": "silero", "threshold": 0.5},
        }

    async def get_stt_config(self):
        return self.current_profile["stt"]

    async def get_tts_config(self):
        return self.current_profile["tts"]

    async def get_vad_config(self):
        return self.current_profile["vad"]

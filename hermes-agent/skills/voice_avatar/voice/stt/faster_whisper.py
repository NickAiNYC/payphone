# hermes-agent/skills/voice_avatar/voice/stt/faster_whisper.py
import numpy as np
from faster_whisper import WhisperModel
from .base import STTProvider


class FasterWhisperSTT(STTProvider):
    def __init__(self, config: dict):
        model_size = config.get("model", "large-v3")
        # Run on CPU with int8 precision for local-first privacy and compatibility
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print(f"[STT] Loaded faster-whisper model: {model_size}")

    @staticmethod
    def load(config: dict) -> "FasterWhisperSTT":
        return FasterWhisperSTT(config)

    async def transcribe(self, audio_bytes: bytes) -> str:
        # Convert raw WebRTC PCM bytes (s16le) to numpy float32 for Whisper
        audio_np = (
            np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        )

        # Transcribe (VAD filter helps ignore silence)
        segments, _ = self.model.transcribe(audio_np, vad_filter=True)
        text = "".join([segment.text for segment in segments]).strip()
        return text

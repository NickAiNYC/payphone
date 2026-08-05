from abc import ABC, abstractmethod


class STTProvider(ABC):
    @staticmethod
    def load(config: dict) -> "STTProvider":
        if config["provider"] == "faster-whisper":
            from .faster_whisper import FasterWhisperSTT

            return FasterWhisperSTT(config)
        raise ValueError(f"Unknown STT provider: {config['provider']}")

    @abstractmethod
    async def transcribe(self, audio: bytes) -> str:
        pass

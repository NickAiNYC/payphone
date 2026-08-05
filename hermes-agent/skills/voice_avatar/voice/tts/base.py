from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TTSEvent:
    kind: str
    payload: any


class TTSProvider(ABC):
    @staticmethod
    def load(config: dict) -> "TTSProvider":
        if config["provider"] == "piper":
            from .piper import PiperTTS

            return PiperTTS(config)
        raise ValueError(f"Unknown TTS provider: {config['provider']}")

    @abstractmethod
    async def synthesize(self, text: str):
        pass

    @abstractmethod
    async def cancel(self):
        pass

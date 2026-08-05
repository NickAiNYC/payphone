# hermes-agent/skills/voice_avatar/voice/tts/piper.py
import io
import wave
import asyncio
import os
from dataclasses import dataclass
from piper.voice import PiperVoice
from .base import TTSProvider


@dataclass
class TTSEvent:
    kind: str  # "audio" or "viseme"
    payload: any


class PiperTTS(TTSProvider):
    def __init__(self, config: dict):
        model_name = config.get("model_path", "en_US-ryan-high.onnx")
        piper_cache = os.environ.get("PIPER_CACHE", "/app/models/piper")

        # Resolve candidate file locations
        candidates = [
            model_name,
            os.path.join(piper_cache, model_name),
            os.path.join(piper_cache, os.path.basename(model_name)),
            os.path.join("models", "piper", os.path.basename(model_name)),
            os.path.join("/app", "models", "piper", os.path.basename(model_name)),
            os.path.join("hermes-agent", os.path.basename(model_name)),
            os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__),
                    "..",
                    "..",
                    "..",
                    "..",
                    os.path.basename(model_name),
                )
            ),
        ]

        resolved_path = model_name
        for candidate in candidates:
            if os.path.exists(candidate):
                resolved_path = candidate
                break

        try:
            self.voice = PiperVoice.load(resolved_path)
            print(f"[TTS] Loaded Piper voice model from: {resolved_path}")
        except Exception as e:
            print(
                f"[TTS] Failed to load Piper model ({resolved_path}). Download one first! Error: {e}"
            )
            self.voice = None

    @staticmethod
    def load(config: dict) -> "PiperTTS":
        return PiperTTS(config)

    async def synthesize(self, text: str):
        if not self.voice:
            return

        # Synthesize to an in-memory WAV buffer
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            self.voice.synthesize_wav(text, wav_file)

        # Get raw PCM audio bytes (16-bit, 16kHz, mono)
        buffer.seek(0)
        wav_file = wave.open(buffer, "rb")
        audio_bytes = wav_file.readframes(wav_file.getnframes())

        # Yield the audio chunk so the pipeline can send it to WebRTC
        yield TTSEvent(kind="audio", payload=audio_bytes)

        # Generate estimated visemes corresponding to the text to synchronize mouth shapes
        words = text.lower().split()
        duration_per_char = 70  # Est. 70ms per character speech rate

        for word in words:
            for char in word:
                viseme = "rest"
                if char == "a":
                    viseme = "A"
                elif char == "e":
                    viseme = "E"
                elif char == "i":
                    viseme = "I"
                elif char == "o":
                    viseme = "O"
                elif char == "u":
                    viseme = "U"
                elif char in ["m", "b", "p"]:
                    viseme = "MBP"
                elif char in ["f", "v"]:
                    viseme = "FV"
                elif char in ["s", "z", "c"]:
                    viseme = "wide"
                elif char == "w":
                    viseme = "narrow"

                yield TTSEvent(
                    kind="viseme",
                    payload={"viseme": viseme, "duration_ms": duration_per_char},
                )
                await asyncio.sleep(0.005)

            # Add a rest frame between words
            yield TTSEvent(kind="viseme", payload={"viseme": "rest", "duration_ms": 30})
            await asyncio.sleep(0.005)

    async def cancel(self):
        pass

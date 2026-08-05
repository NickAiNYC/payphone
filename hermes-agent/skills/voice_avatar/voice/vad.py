import time
import logging
from typing import Callable, Optional, Awaitable

logger = logging.getLogger(__name__)


class SileroVAD:
    """Continuous Voice Activity Detection engine for 16kHz 16-bit mono PCM streams.
    Buffers audio frames, evaluates energy & speech probabilities, and triggers
    speech start / stop events.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.threshold = float(self.config.get("threshold", 0.5))
        self.sample_rate = int(self.config.get("sample_rate", 16000))
        self.frame_duration_ms = int(self.config.get("frame_duration_ms", 30))
        self.frame_bytes = int(self.sample_rate * (self.frame_duration_ms / 1000.0) * 2)

        self.is_speaking = False
        self.speech_bytes_buffer = bytearray()
        self.on_speech_start: Optional[Callable[[], Awaitable[None]]] = None
        self.on_speech_end: Optional[Callable[[bytes], Awaitable[None]]] = None

    def process_chunk(self, pcm_data: bytes) -> Optional[str]:
        """Process incoming raw PCM bytes chunk and return VAD state ('speech_start', 'speech_end', or None)."""
        if not pcm_data:
            return None

        # Simple RMS energy / speech probability estimator
        samples = [
            int.from_bytes(pcm_data[i : i + 2], byteorder="little", signed=True)
            for i in range(0, len(pcm_data) - 1, 2)
        ]
        if not samples:
            return None

        rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
        normalized_probability = min(1.0, rms / 4000.0)

        if normalized_probability >= self.threshold:
            self.speech_bytes_buffer.extend(pcm_data)
            if not self.is_speaking:
                self.is_speaking = True
                logger.debug("[SileroVAD] Speech boundary START detected")
                return "speech_start"
        else:
            if self.is_speaking:
                self.is_speaking = False
                logger.debug("[SileroVAD] Speech boundary END detected")
                return "speech_end"

        return None


# Export VAD alias for backward compatibility
VAD = SileroVAD

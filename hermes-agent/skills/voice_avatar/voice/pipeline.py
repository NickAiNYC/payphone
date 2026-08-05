import asyncio
from typing import AsyncIterator, Callable, Awaitable, Optional
from dataclasses import dataclass
from .stt.base import STTProvider
from .tts.base import TTSProvider
from .vad import VAD
from .barge_in import BargeInCoordinator
from ..consent.policy import RawMediaPolicy
from ..avatar.state_machine import AvatarStateMachine
from .llm.base import LLMProvider


@dataclass
class EmotionTag:
    name: str
    intensity: float


@dataclass
class VoiceConfig:
    stt: dict
    tts: dict
    vad: dict


class VoicePipeline:
    def __init__(
        self,
        config: VoiceConfig,
        llm_stream: LLMProvider,
        avatar: AvatarStateMachine,
        policy: RawMediaPolicy,
        human_pubkey: str,
        agent_pubkey: str,
    ):
        self.config = config
        self.llm_stream = llm_stream
        self.avatar = avatar
        self.policy = policy
        self.human_pubkey = human_pubkey
        self.agent_pubkey = agent_pubkey
        self._stop_speaking = asyncio.Event()
        self._speaking_task = None
        self.on_emotion = None
        self.on_state = None
        self.on_viseme = None

    async def start(self):
        can_process_cloud = await self.policy.can_process_raw_media(
            self.human_pubkey, self.agent_pubkey
        )
        if (
            self.config.stt["provider"] not in ["faster-whisper", "whisper-local"]
            and not can_process_cloud
        ):
            raise PermissionError(f"STT provider requires server_processing_opt_in")
        if (
            self.config.tts["provider"] not in ["piper", "coqui"]
            and not can_process_cloud
        ):
            raise PermissionError(f"TTS provider requires server_processing_opt_in")

        self.stt = STTProvider.load(self.config.stt)
        self.tts = TTSProvider.load(self.config.tts)
        self.vad = VAD(self.config.vad)
        self.barge = BargeInCoordinator(self.tts, self.vad, self.avatar)

    async def handle_audio_stream(self, audio_stream: AsyncIterator[bytes]):
        # Mock/VAD activity detection yielding utterances
        # In a real system, the VAD handles the stream activity detection
        pass

    async def process_utterance(self, audio_bytes: bytes):
        """Processes a single utterance: STT -> LLM -> TTS."""
        self.avatar.transition("thinking")
        if self.on_state:
            self.on_state("thinking")

        # Offload CPU-bound STT transcription to thread
        text = await asyncio.to_thread(self._run_stt_sync, audio_bytes)
        if not text.strip():
            self.avatar.transition("idle")
            if self.on_state:
                self.on_state("idle")
            return

        self.avatar.transition("thinking")

        async for chunk in self._llm_with_emotion(text):
            if isinstance(chunk, EmotionTag):
                self.avatar.set_emotion(chunk.name, chunk.intensity)
                if self.on_emotion:
                    self.on_emotion(chunk.name, chunk.intensity)
            elif isinstance(chunk, str):
                await self._speak(chunk)

        self.avatar.transition("idle")
        if self.on_state:
            self.on_state("idle")

    def _run_stt_sync(self, audio_bytes: bytes) -> str:
        # Helper to execute stt transcription synchronously inside a thread
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.stt.transcribe(audio_bytes))
        finally:
            loop.close()

    async def _llm_with_emotion(self, text: str) -> AsyncIterator[any]:
        buffer = ""
        in_tag = False
        tag_buffer = ""

        async for chunk in self.llm_stream.generate_stream(text):
            for char in chunk:
                if char == "<":
                    in_tag = True
                    tag_buffer = ""
                    if buffer:
                        yield buffer
                        buffer = ""
                elif char == ">":
                    if in_tag:
                        in_tag = False
                        if tag_buffer.startswith("emotion:"):
                            try:
                                parts = tag_buffer[8:].split("|")
                                name = parts[0]
                                intensity = float(parts[1])
                                yield EmotionTag(name=name, intensity=intensity)
                            except Exception:
                                yield f"<{tag_buffer}>"
                        else:
                            yield f"<{tag_buffer}>"
                        tag_buffer = ""
                    else:
                        buffer += char
                else:
                    if in_tag:
                        tag_buffer += char
                    else:
                        buffer += char
                        # Yield early on natural breaks to reduce latency
                        if len(buffer) > 20 and char in [".", ",", "!", "?", " "]:
                            yield buffer
                            buffer = ""

        if buffer:
            yield buffer

    async def _speak(self, text: str):
        self._stop_speaking.clear()
        self.avatar.start_speaking()
        if self.on_state:
            self.on_state("speaking")

        # Offload TTS synthesis to a thread
        async for ev in self._synthesize_in_thread(text):
            if self._stop_speaking.is_set():
                await self.tts.cancel()
                self.avatar.barge_in()
                if self.on_state:
                    self.on_state("thinking")
                return
            if ev.kind == "audio":
                await self._out_audio(ev.payload)
            elif ev.kind == "viseme" and self.on_viseme:
                await self.on_viseme(ev.payload)

    async def _synthesize_in_thread(self, text: str) -> AsyncIterator[any]:
        # Generator wrapper to run generator-based TTS synthesis in thread if needed
        # Since self.tts.synthesize is an async generator, we consume it and yield.
        # Inside PiperTTS, wave/onnx calls are synchronous so we run them inside to_thread.
        async for ev in self.tts.synthesize(text):
            yield ev

    async def _out_audio(self, chunk: bytes):
        # Callback for processed voice audio output (e.g. WebRTC addTrack)
        pass

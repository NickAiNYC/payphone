import asyncio
import av
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaStreamTrack
from ..consent.manager import ConsentManager
from ..consent.policy import RawMediaPolicy
from ..avatar.state_machine import AvatarStateMachine
from ..voice.pipeline import VoicePipeline


class AvatarAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self._queue = asyncio.Queue()
        self.resampler = av.AudioResampler(format="s16", layout="stereo", rate=48000)
        self.pts = 0

    async def recv(self):
        # Retrieve 16kHz mono PCM bytes (20ms = 640 bytes)
        pcm_bytes = await self._queue.get()

        # Convert PCM bytes to numpy array
        data = np.frombuffer(pcm_bytes, dtype=np.int16)

        # Create 16kHz mono AudioFrame
        frame = av.AudioFrame.from_ndarray(
            data.reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = 16000
        frame.time_base = av.Fraction(1, 16000)

        # Resample to 48kHz stereo AudioFrame
        resampled = self.resampler.resample(frame)
        if not resampled:
            out_frame = av.AudioFrame(format="s16", layout="stereo", samples=960)
            out_frame.sample_rate = 48000
        else:
            out_frame = resampled[0]

        out_frame.pts = self.pts
        # 960 samples at 48000Hz = 20ms
        self.pts += out_frame.samples
        out_frame.time_base = av.Fraction(1, 48000)

        return out_frame


class HermesCallSession:
    def __init__(self, consent: ConsentManager, policy: RawMediaPolicy, signaling):
        self.consent = consent
        self.policy = policy
        self.signaling = signaling
        self.pc = RTCPeerConnection()
        self.avatar = AvatarStateMachine()
        self.call_id = None
        self.pipeline = None
        self.output_track = None

    async def pre_call_hook(self, human_pubkey: str, agent_pubkey: str):
        if not await self.consent.check(human_pubkey, agent_pubkey, ["mic"]):
            raise PermissionError("Consent denied for mic access")

        channel = self.pc.createDataChannel("avatar-state", ordered=True)
        self.channel = channel

        @channel.on("open")
        def on_open():
            try:
                channel.send(self.avatar.serialize())
            except Exception:
                pass

        def send_state(state_dict):
            if channel.readyState == "open":
                try:
                    channel.send(self.avatar.serialize())
                except Exception:
                    pass

        self.avatar.on(send_state)

    async def create_answer(
        self,
        offer_sdp: str,
        human_pubkey: str,
        agent_pubkey: str,
        voice_pipeline: VoicePipeline,
    ):
        await self.pre_call_hook(human_pubkey, agent_pubkey)
        self.pipeline = voice_pipeline
        self.output_track = AvatarAudioTrack()

        # Wire pipeline output to the WebRTC track
        async def send_audio(chunk: bytes):
            # Split the Piper TTS output (16kHz PCM mono) into 20ms chunks (640 bytes)
            chunk_size = 640
            for i in range(0, len(chunk), chunk_size):
                sub_chunk = chunk[i : i + chunk_size]
                if len(sub_chunk) < chunk_size:
                    sub_chunk = sub_chunk + b"\x00" * (chunk_size - len(sub_chunk))
                await self.output_track._queue.put(sub_chunk)

        self.pipeline._out_audio = send_audio

        # Wire visemes to the DataChannel
        import json

        async def send_viseme(viseme_payload):
            if self.channel and self.channel.readyState == "open":
                try:
                    payload = {
                        "type": "viseme",
                        "viseme": viseme_payload["viseme"],
                        "duration_ms": viseme_payload["duration_ms"],
                    }
                    self.channel.send(json.dumps(payload))
                except Exception:
                    pass

        self.pipeline.on_viseme = send_viseme

        # Wire emotions to the DataChannel
        async def send_emotion(emotion_name, intensity):
            if self.channel and self.channel.readyState == "open":
                try:
                    payload = {
                        "type": "emotion",
                        "emotion": emotion_name,
                        "intensity": intensity,
                    }
                    self.channel.send(json.dumps(payload))
                except Exception:
                    pass

        self.pipeline.on_emotion = send_emotion

        @self.pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                # Feed incoming mic audio to the VoicePipeline
                async def feed_pipeline():
                    async for frame in track:
                        # Convert 48kHz (usually) AudioFrame to 16kHz for Whisper
                        # For Whisper, we extract bytes and let the pipeline process
                        pcm_bytes = frame.to_ndarray().tobytes()
                        # Pass utterance audio to pipeline
                        await self.pipeline.process_utterance(pcm_bytes)

                asyncio.ensure_future(feed_pipeline())
                self.pc.addTrack(self.output_track)

        await self.pc.setRemoteDescription(
            RTCSessionDescription(sdp=offer_sdp, type="offer")
        )
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        return answer.sdp

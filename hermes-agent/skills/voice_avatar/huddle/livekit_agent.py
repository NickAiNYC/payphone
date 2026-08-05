import asyncio
from livekit import rtc
from ..voice.pipeline import VoicePipeline


class LiveKitAgent:
    def __init__(self, room_url: str, token: str, pipeline: VoicePipeline):
        self.room_url = room_url
        self.token = token
        self.pipeline = pipeline
        self.room = rtc.Room()
        self.audio_source = rtc.AudioSource(16000, 1)

    async def connect(self):
        @self.room.on("track_subscribed")
        def on_track_subscribed(
            track: rtc.Track,
            publication: rtc.TrackPublication,
            participant: rtc.RemoteParticipant,
        ):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(
                    self.handle_incoming_audio(track, participant.identity)
                )

        print(f"[LiveKit Agent] Connecting to {self.room_url}...")
        await self.room.connect(self.room_url, self.token)
        print("[LiveKit Agent] Connected to LiveKit room!")

        # Publish agent output audio track
        track = rtc.LocalAudioTrack.create_audio_track("agent-audio", self.audio_source)
        options = rtc.TrackPublishOptions(name="agent-voice")
        await self.room.local_participant.publish_track(track, options)
        print("[LiveKit Agent] Published agent audio track.")

        # Wire pipeline voice synthesis callback to the LiveKit AudioSource
        async def send_audio(chunk: bytes):
            # 16-bit signed PCM = 2 bytes per sample
            samples_per_channel = len(chunk) // 2
            frame = rtc.AudioFrame(chunk, 16000, 1, samples_per_channel)
            await self.audio_source.capture_frame(frame)

        self.pipeline._out_audio = send_audio

    async def handle_incoming_audio(
        self, track: rtc.AudioTrack, participant_identity: str
    ):
        print(f"[LiveKit Agent] Subscribed to track from {participant_identity}")
        audio_stream = rtc.AudioStream(track)
        async for frame in audio_stream:
            # Yield audio data into the pipeline
            pcm_bytes = frame.data.tobytes()
            await self.pipeline.process_utterance(pcm_bytes)

    async def disconnect(self):
        await self.room.disconnect()
        print("[LiveKit Agent] Disconnected from room.")

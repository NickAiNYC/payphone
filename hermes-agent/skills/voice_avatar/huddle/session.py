from typing import List
import asyncio
import json
from ..voice.pipeline import VoicePipeline
from ..avatar.state_machine import AvatarStateMachine
from .floor_manager import FloorManager


class HermesHuddleSession:
    def __init__(
        self, sfu_client, voice_pipeline: VoicePipeline, floor_manager: FloorManager
    ):
        self.sfu = sfu_client
        self.pipeline = voice_pipeline
        self.avatar = AvatarStateMachine()
        self.floor = floor_manager
        self._listen_task = None

    async def join(self, room_name: str, token: str, agent_pubkeys: List[str]):
        await self.sfu.connect(room_name, token)

        def broadcast_state(state_dict):
            asyncio.create_task(
                self.sfu.send_data_message(self.avatar.serialize().encode())
            )

        self.avatar.on(broadcast_state)

        self.sfu.on_track(self._on_participant_track)
        self.sfu.on_data_message(self._on_data_message)

    async def _on_participant_track(self, track, participant_pubkey: str):
        if await self.floor.has_floor(participant_pubkey):
            await self.pipeline.handle_audio_stream(track)

    async def _on_data_message(self, payload: bytes, from_pubkey: str):
        try:
            state = json.loads(payload.decode())
            if state.get("s") == "speaking" and from_pubkey in getattr(
                self, "agent_pubkeys", []
            ):
                await self.floor.yield_floor()
        except:
            pass

    async def request_floor(self):
        await self.floor.request_floor(self.sfu.pubkey)
        if await self.floor.has_floor(self.sfu.pubkey):
            self.avatar.transition("speaking")

from hermes.skills import Skill, SkillContext, skill_method
from .calls.webrtc_endpoint import HermesCallSession
from .calls.signaling import NostrSignaling
from .voice.profile_manager import VoiceProfileManager
from .voice.pipeline import VoicePipeline, VoiceConfig
from .memory.trace import InteractionTraceWriter
from .memory.summarizer import CallSummarizer
from .avatar.state_machine import AvatarStateMachine
from .huddle.session import HermesHuddleSession
from .huddle.floor_manager import FloorManager
from .consent.manager import ConsentManager
from .consent.policy import RawMediaPolicy


class VoiceAvatarSkill(Skill):
    name = "voice_avatar"
    version = "0.1.0"

    def __init__(self, ctx: SkillContext):
        super().__init__(ctx)
        self.signaling = NostrSignaling(ctx.nostr, ctx.nostr.pubkey)
        self.profile_mgr = VoiceProfileManager(ctx.nostr, ctx)
        self.traces = InteractionTraceWriter(ctx.memory)
        self.summarizer = CallSummarizer(ctx.llm)
        self.active_calls = {}
        self.active_huddles = {}

    @skill_method(description="Accept incoming call")
    async def accept_call(
        self, call_id: str, human_pubkey: str, offer_sdp: str
    ) -> dict:
        stt = await self.profile_mgr.get_stt_config()
        tts = await self.profile_mgr.get_tts_config()
        vad = await self.profile_mgr.get_vad_config()

        avatar = AvatarStateMachine()
        pipeline = VoicePipeline(
            VoiceConfig(stt, tts, vad),
            self.ctx.llm_stream,
            avatar,
            self.ctx.policy,
            human_pubkey,
            self.ctx.nostr.pubkey,
        )
        await pipeline.start()

        session = HermesCallSession(self.ctx.consent, self.ctx.policy, self.signaling)
        self.active_calls[call_id] = session

        answer_sdp = await session.create_answer(
            offer_sdp, human_pubkey, self.ctx.nostr.pubkey, pipeline
        )
        await self.traces.start(call_id, "1:1", [human_pubkey, self.ctx.nostr.pubkey])
        return {"answer_sdp": answer_sdp}

    @skill_method(description="Hangup call and generate summary")
    async def hangup(self, call_id: str, human_pubkey: str) -> dict:
        session = self.active_calls.pop(call_id, None)
        if not session:
            return {"error": "not_found"}

        await session.pc.close()
        trace = await self.traces.end(call_id, "agent_initiated")
        summary = await self.summarizer.summarize(trace)
        await self.traces.write_memory(trace, summary)
        await self.signaling.send_summary(call_id, human_pubkey, summary)
        return summary

    @skill_method(description="Join huddle")
    async def join_huddle(self, huddle_id: str, sfu_room: str, sfu_token: str) -> dict:
        stt = await self.profile_mgr.get_stt_config()
        tts = await self.profile_mgr.get_tts_config()
        vad = await self.profile_mgr.get_vad_config()

        avatar = AvatarStateMachine()
        pipeline = VoicePipeline(
            VoiceConfig(stt, tts, vad),
            self.ctx.llm_stream,
            avatar,
            self.ctx.policy,
            "human_pk",
            self.ctx.nostr.pubkey,
        )
        await pipeline.start()

        sfu_client = None  # Inject LiveKitSFUClient here
        floor_mgr = FloorManager()
        session = HermesHuddleSession(sfu_client, pipeline, floor_mgr)
        await session.join(sfu_room, sfu_token, [])
        self.active_huddles[huddle_id] = session
        return {"status": "joined"}

from __future__ import annotations
import json
from typing import Any
from ..memory.trace import InteractionTrace


class VoiceSelfImprover:
    def __init__(self, llm_client, memory_store):
        self.llm = llm_client
        self.memory = memory_store

    async def analyze_and_propose(self, trace: InteractionTrace, summary: dict):
        barge_in_count = len(trace.barge_ins)
        avg_tool_latency = (
            sum(t["latency_ms"] for t in trace.tool_calls) / len(trace.tool_calls)
            if trace.tool_calls
            else 0
        )

        prompt = f"""
        You are analyzing a voice call InteractionTrace to improve the agent's behavior.
        The user interrupted (barge-in) {barge_in_count} times.
        The average tool latency was {avg_tool_latency}ms.
        Summary: {json.dumps(summary)}
        
        Propose a JSON patch (RFC 6902) to the VoiceProfile to improve user experience.
        For example, if barge-ins are high, increase TTS speed or reduce LLM max_tokens.
        If user sounded frustrated, adjust default emotion to 'apologetic'.
        
        Format: {{"patch": [{{"op": "replace", "path": "/tts/speed", "value": 1.1}}], "reason": "..."}}
        """

        proposal = await self.llm.complete(
            prompt,
            response_format={
                "type": "object",
                "properties": {
                    "patch": {"type": "array"},
                    "reason": {"type": "string"},
                },
            },
            max_tokens=500,
            temperature=0.2,
        )

        await self.memory.save_skill_diff(
            skill_name="voice_avatar",
            diff=proposal["patch"],
            reason=proposal["reason"],
            trace_id=trace.call_id,
        )

        if summary.get("emotional_tone") == "frustrated":
            await self.memory.update_user_preferences(
                trace.participants[0], {"default_emotion": "apologetic"}
            )

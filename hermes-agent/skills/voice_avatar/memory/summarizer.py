from typing import Any
import json
from .trace import InteractionTrace

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {"type": "array", "items": {"type": "string"}},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"task": {"type": "string"}, "owner": {"type": "string"}},
            },
        },
        "emotional_tone": {"type": "string"},
        "tools_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topics", "decisions", "action_items"],
}


class CallSummarizer:
    def __init__(self, llm_client):
        self.llm = llm_client

    async def summarize(self, trace: InteractionTrace) -> dict[str, Any]:
        prompt = f"""Summarize this {trace.kind} interaction. 
        Transcript: {json.dumps(trace.transcript)}
        Tools: {json.dumps(trace.tool_calls)}
        Barge-ins: {json.dumps(trace.barge_ins)}
        Produce a structured summary identifying topics, decisions, action items, emotional tone, and tools used.
        """
        return await self.llm.complete(
            prompt, response_format=SUMMARY_SCHEMA, max_tokens=2048, temperature=0.2
        )

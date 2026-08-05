from dataclasses import dataclass, field
from typing import List, Dict
import time


@dataclass
class InteractionTrace:
    call_id: str
    kind: str
    started_at: float
    ended_at: float = 0.0
    participants: List[str] = field(default_factory=list)
    transcript: List[Dict] = field(default_factory=list)
    tool_calls: List[Dict] = field(default_factory=list)
    avatar_events: List[Dict] = field(default_factory=list)
    barge_ins: List[Dict] = field(default_factory=list)

    def add_turn(self, speaker: str, text: str, emotion: str = "neutral"):
        self.transcript.append(
            {"t": time.time(), "speaker": speaker, "text": text, "emotion": emotion}
        )

    def add_tool(self, name: str, args: dict, result: str, latency_ms: float):
        self.tool_calls.append(
            {
                "t": time.time(),
                "name": name,
                "args": args,
                "result": result,
                "latency_ms": latency_ms,
            }
        )

    def add_avatar_event(self, state: str, emotion: str):
        self.avatar_events.append(
            {"t": time.time(), "state": state, "emotion": emotion}
        )

    def add_barge_in(self, by: str, recovered_in_ms: float):
        self.barge_ins.append(
            {"t": time.time(), "by": by, "recovered_in_ms": recovered_in_ms}
        )


class InteractionTraceWriter:
    def __init__(self, memory_store):
        self.mem = memory_store

    async def start(
        self, call_id: str, kind: str, participants: list
    ) -> InteractionTrace:
        t = InteractionTrace(
            call_id=call_id,
            kind=kind,
            started_at=time.time(),
            participants=participants,
        )
        await self.mem.set(f"call:active:{call_id}", t)
        return t

    async def end(self, call_id: str, reason: str) -> InteractionTrace:
        t: InteractionTrace = await self.mem.get(f"call:active:{call_id}")
        t.ended_at = time.time()
        await self.mem.delete(f"call:active:{call_id}")
        await self.mem.append(f"call:trace:{call_id}", t)
        return t

    async def write_memory(self, trace: InteractionTrace, summary: dict):
        await self.mem.remember(
            kind="interaction",
            scope=trace.kind,
            summary=(
                summary["summary"] if "summary" in summary else summary.get("topics")
            ),
            entities=summary.get("entities", []),
            action_items=summary.get("action_items", []),
            trace_ref=trace.id,
        )

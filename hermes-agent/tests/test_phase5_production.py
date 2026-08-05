import pytest, asyncio
from unittest.mock import AsyncMock, MagicMock
from skills.voice_avatar.hardening.reconnect import ReconnectionManager
from skills.voice_avatar.self_improvement.refiner import VoiceSelfImprover
from skills.voice_avatar.memory.trace import InteractionTrace


@pytest.mark.asyncio
async def test_reconnection_falls_back_to_data_only():
    mock_pc = MagicMock()
    mock_pc.connectionState = "disconnected"
    mock_pc.getTransceivers.return_value = []
    mgr = ReconnectionManager(mock_pc, AsyncMock(), AsyncMock(), max_retries=1)
    await mgr._ice_restart()
    await asyncio.sleep(0.1)
    mock_pc.getTransceivers.assert_called()


@pytest.mark.asyncio
async def test_self_improvement_proposes_diff():
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = {
        "patch": [{"op": "replace", "path": "/tts/speed", "value": 1.1}],
        "reason": "High barge-in rate",
    }
    improver = VoiceSelfImprover(mock_llm, AsyncMock())
    trace = InteractionTrace(call_id="1", kind="1:1", started_at=0)
    trace.add_barge_in("human_pk", 150)
    trace.add_barge_in("human_pk", 140)
    await improver.analyze_and_propose(trace, {"emotional_tone": "neutral"})
    improver.memory.save_skill_diff.assert_called_once()

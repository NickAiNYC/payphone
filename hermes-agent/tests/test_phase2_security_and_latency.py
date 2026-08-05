import pytest, time, asyncio
from unittest.mock import AsyncMock, MagicMock
from skills.voice_avatar.consent.manager import ConsentManager
from skills.voice_avatar.calls.webrtc_endpoint import HermesCallSession
from skills.voice_avatar.voice.barge_in import BargeInCoordinator


@pytest.mark.asyncio
async def test_consent_rejection_blocks_offer():
    mock_consent = AsyncMock(ConsentManager)
    mock_consent.check.return_value = False
    session = HermesCallSession(mock_consent, AsyncMock(), AsyncMock())
    with pytest.raises(PermissionError, match="Consent denied"):
        await session.pre_call_hook("human_pk", "agent_pk")


@pytest.mark.asyncio
async def test_barge_in_latency_under_150ms():
    mock_tts = AsyncMock()
    mock_tts.cancel.return_value = asyncio.sleep(0.01)
    coordinator = BargeInCoordinator(mock_tts, AsyncMock(), MagicMock())
    start = time.time()
    await coordinator.on_vad_speech_start()
    latency_ms = (time.time() - start) * 1000
    assert latency_ms < 150.0

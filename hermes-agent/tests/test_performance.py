import pytest
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock
from skills.voice_avatar.voice.barge_in import BargeInCoordinator
from skills.voice_avatar.avatar.state_machine import AvatarStateMachine

# Performance Budgets:
# - Voice end-to-end latency < 300 ms P50 / < 500 ms P95
# - Barge-in recovery < 150 ms
# - Avatar state propagation < 50 ms
# - First-call setup < 2 s
# - Huddle join < 3 s


@pytest.mark.asyncio
async def test_barge_in_latency_budget():
    """Asserts that BargeInCoordinator cancels TTS and triggers avatar transition within 150ms budget."""
    mock_tts = AsyncMock()

    async def mock_cancel():
        pass

    mock_tts.cancel = mock_cancel

    avatar = MagicMock()

    coordinator = BargeInCoordinator(mock_tts, AsyncMock(), avatar)

    start_time = time.time()
    await coordinator.on_vad_speech_start()
    latency_ms = (time.time() - start_time) * 1000

    assert (
        latency_ms < 150.0
    ), f"Barge-in latency of {latency_ms:.2f}ms exceeded the 150ms budget"
    avatar.barge_in.assert_called_once()


@pytest.mark.asyncio
async def test_avatar_state_propagation_budget():
    """Asserts that state transitions propagate events to listeners in under 50ms."""
    avatar = AvatarStateMachine()
    events = []

    avatar.on(lambda ev: events.append(ev))

    start_time = time.perf_counter()
    avatar.transition("idle")
    latency_ms = (time.perf_counter() - start_time) * 1000

    assert (
        latency_ms < 50.0
    ), f"Avatar state propagation latency of {latency_ms:.2f}ms exceeded the 50ms budget"
    assert len(events) == 1
    assert events[0]["s"] == "idle"


@pytest.mark.asyncio
async def test_call_connection_setup_mock_budget():
    """Asserts that connection initialization and track setup execute in under 2 seconds."""
    from skills.voice_avatar.calls.webrtc_endpoint import HermesCallSession

    mock_consent = AsyncMock()
    mock_consent.check.return_value = True

    mock_policy = AsyncMock()

    session = HermesCallSession(mock_consent, mock_policy, AsyncMock())

    start_time = time.perf_counter()
    # Execute pre-call tasks (DataChannel configuration, event binding)
    await session.pre_call_hook("human_pk", "agent_pk")
    latency_ms = (time.perf_counter() - start_time) * 1000

    assert (
        latency_ms < 2000.0
    ), f"Call connection setup latency of {latency_ms:.2f}ms exceeded the 2000ms budget"


@pytest.mark.asyncio
async def test_huddle_join_mock_budget():
    """Asserts that join operations execute in under 3 seconds."""
    from skills.voice_avatar.huddle.session import HermesHuddleSession

    mock_sfu = AsyncMock()
    mock_sfu.join.return_value = asyncio.sleep(0.05)  # simulate join response

    session = HermesHuddleSession(mock_sfu, AsyncMock(), AsyncMock())

    start_time = time.perf_counter()
    await session.join("sfu_room", "sfu_token", [])
    latency_ms = (time.perf_counter() - start_time) * 1000

    assert (
        latency_ms < 3000.0
    ), f"Huddle join latency of {latency_ms:.2f}ms exceeded the 3000ms budget"

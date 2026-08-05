import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from skills.voice_avatar.calls.webrtc_endpoint import HermesCallSession
from skills.voice_avatar.calls.signaling import NostrSignaling


@pytest.mark.asyncio
async def test_webrtc_handshake_flow():
    """Verifies that the signaling loop formats, processes, and completes WebRTC SDP negotiations."""
    mock_nostr = AsyncMock()
    signaling = NostrSignaling(mock_nostr, "agent_pubkey")

    mock_consent = AsyncMock()
    mock_consent.check.return_value = True
    mock_policy = AsyncMock()

    session = HermesCallSession(mock_consent, mock_policy, signaling)

    # 1. Create client-side offer SDP with valid mock ICE/DTLS credentials for aiortc parser validation
    offer_sdp = (
        "v=0\r\n"
        "o=- 42 2 IN IP4 127.0.0.1\r\n"
        "s=-\r\n"
        "t=0 0\r\n"
        "a=ice-ufrag:mockufrag\r\n"
        "a=ice-pwd:mockpassword\r\n"
        "a=fingerprint:sha-256 AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99\r\n"
        "a=setup:actpass\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "c=IN IP4 127.0.0.1\r\n"
        "a=rtpmap:111 opus/48000/2\r\n"
        "a=rtcp-mux\r\n"
        "a=mid:0\r\n"
        "a=sendrecv\r\n"
    )

    # Mock pipeline attributes required by create_answer
    mock_pipeline = AsyncMock()

    # 2. Complete answer creation
    answer_sdp = await session.create_answer(
        offer_sdp=offer_sdp,
        human_pubkey="human_pubkey",
        agent_pubkey="agent_pubkey",
        voice_pipeline=mock_pipeline,
    )

    assert "v=0" in answer_sdp
    assert "m=audio" in answer_sdp
    assert session.pc.remoteDescription is not None
    assert "mockufrag" in session.pc.remoteDescription.sdp


@pytest.mark.asyncio
async def test_nostr_signaling_outgoing_gift_wrap():
    """Asserts that signaling sends properly formatted kind-21001/kind-21002 events via NIP-17 packaging."""
    mock_nostr = AsyncMock()
    signaling = NostrSignaling(mock_nostr, "agent_pubkey")

    # Send a call invitation (kind 21001)
    call_id = await signaling.send_invite("human_pubkey", "offer_sdp_stub", ["audio"])

    assert len(call_id) == 16  # secrets.token_hex(8)

    # Verify signature parameters matches target kind and recipient tags
    mock_nostr.publish_gift_wrap.assert_called_once()
    called_to_pubkey, called_kind, called_content = (
        mock_nostr.publish_gift_wrap.call_args[0]
    )

    assert called_to_pubkey == "human_pubkey"
    assert called_kind == 21001

    parsed_payload = json.loads(called_content)
    assert parsed_payload["call_id"] == call_id
    assert parsed_payload["offer_sdp"] == "offer_sdp_stub"

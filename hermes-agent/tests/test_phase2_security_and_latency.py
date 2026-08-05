import pytest
import time
import json
import hashlib
import asyncio
from unittest.mock import AsyncMock, MagicMock
from skills.voice_avatar.consent.manager import (
    ConsentManager,
    verify_nostr_event_crypto,
)
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


@pytest.mark.asyncio
async def test_relay_consent_signature_verification_and_forgery_rejection():
    # Real test event signed with BIP-340 Schnorr signature
    valid_event = {
        "kind": 21005,
        "created_at": 1700000000,
        "tags": [["p", "agent_pubkey"]],
        "content": '{"scopes":["mic"],"record":false,"server_processing_opt_in":false,"expiration":1800000000}',
        "pubkey": "75d0e3c1fd7b4346f4c0b343fac81320c33625aebb602e662efc000e77300f55",
        "id": "8e30354454ef67487d2d971b0620f5c95cb9615b405f61d344c9bf7c17a2aa51",
        "sig": "08328fe94fb82f78f929cf33325099447d68f03515400ad16fc63b12950039508122a8b5f7224f56c3ede4a41709ac2a5ed1d5a7eefd73102afb7bd78504f5d8",
    }
    human_pk = "75d0e3c1fd7b4346f4c0b343fac81320c33625aebb602e662efc000e77300f55"

    # 1. Valid event verifies True
    assert verify_nostr_event_crypto(valid_event, human_pk) is True

    # 2. Forged event content fails verification
    forged_content_event = dict(valid_event)
    forged_content_event["content"] = (
        '{"scopes":["mic"],"record":true,"server_processing_opt_in":true,"expiration":1800000000}'
    )
    assert verify_nostr_event_crypto(forged_content_event, human_pk) is False

    # 3. Forged pubkey fails verification
    forged_pubkey_event = dict(valid_event)
    forged_pubkey_event["pubkey"] = (
        "1111111111111111111111111111111111111111111111111111111111111111"
    )
    assert verify_nostr_event_crypto(forged_pubkey_event, human_pk) is False

    # 4. ConsentManager rejecting forged events from mock relay
    mock_nostr = AsyncMock()
    mock_nostr.get_events.return_value = [forged_content_event]

    manager = ConsentManager(nostr_client=mock_nostr)
    grant = await manager.fetch_grant(human_pk, "agent_pubkey")

    # Must fail closed (return None) when relay events fail cryptographic verification
    assert grant is None


def test_coincurve_fast_path_agreement():
    """Asserts that coincurve PublicKeyXOnly fast-path and pure-Python BIP-340 verifiers agree 100%."""
    try:
        from coincurve import PublicKeyXOnly
    except ImportError:
        pytest.skip("coincurve not installed in local environment")

    valid_event = {
        "kind": 21005,
        "created_at": 1700000000,
        "tags": [["p", "agent_pubkey"]],
        "content": '{"scopes":["mic"],"record":false,"server_processing_opt_in":false,"expiration":1800000000}',
        "pubkey": "75d0e3c1fd7b4346f4c0b343fac81320c33625aebb602e662efc000e77300f55",
        "id": "8e30354454ef67487d2d971b0620f5c95cb9615b405f61d344c9bf7c17a2aa51",
        "sig": "08328fe94fb82f78f929cf33325099447d68f03515400ad16fc63b12950039508122a8b5f7224f56c3ede4a41709ac2a5ed1d5a7eefd73102afb7bd78504f5d8",
    }

    sig_bytes = bytes.fromhex(valid_event["sig"])
    msg_bytes = bytes.fromhex(valid_event["id"])
    pub_bytes = bytes.fromhex(valid_event["pubkey"])

    coincurve_result = PublicKeyXOnly(pub_bytes).verify(sig_bytes, msg_bytes)
    python_result = verify_nostr_event_crypto(valid_event, valid_event["pubkey"])

    assert coincurve_result == python_result == True

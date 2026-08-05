import pytest
import time
import json
import hashlib
import asyncio
from unittest.mock import AsyncMock, MagicMock
from skills.voice_avatar.consent.manager import (
    ConsentManager,
    verify_nostr_event_crypto,
    _verify_schnorr_python,
)
from skills.voice_avatar.calls.webrtc_endpoint import HermesCallSession
from skills.voice_avatar.voice.barge_in import BargeInCoordinator

# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_EVENT = {
    "kind": 21005,
    "created_at": 1700000000,
    "tags": [["p", "agent_pubkey"]],
    "content": '{"scopes":["mic"],"record":false,"server_processing_opt_in":false,"expiration":1800000000}',
    "pubkey": "75d0e3c1fd7b4346f4c0b343fac81320c33625aebb602e662efc000e77300f55",
    "id": "8e30354454ef67487d2d971b0620f5c95cb9615b405f61d344c9bf7c17a2aa51",
    "sig": "08328fe94fb82f78f929cf33325099447d68f03515400ad16fc63b12950039508122a8b5f7224f56c3ede4a41709ac2a5ed1d5a7eefd73102afb7bd78504f5d8",
}
HUMAN_PK = VALID_EVENT["pubkey"]


# ── Core consent & media tests ─────────────────────────────────────────────────


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


# ── BIP-340 verification & forgery rejection ───────────────────────────────────


@pytest.mark.asyncio
async def test_relay_consent_signature_verification_and_forgery_rejection():
    # 1. Valid event verifies True
    assert verify_nostr_event_crypto(VALID_EVENT, HUMAN_PK) is True

    # 2. Forged event content fails verification (event ID is now stale)
    forged_content_event = dict(VALID_EVENT)
    forged_content_event["content"] = (
        '{"scopes":["mic"],"record":true,"server_processing_opt_in":true,"expiration":1800000000}'
    )
    assert verify_nostr_event_crypto(forged_content_event, HUMAN_PK) is False

    # 3. Forged pubkey fails the author-match check before crypto
    forged_pubkey_event = dict(VALID_EVENT)
    forged_pubkey_event["pubkey"] = (
        "1111111111111111111111111111111111111111111111111111111111111111"
    )
    assert verify_nostr_event_crypto(forged_pubkey_event, HUMAN_PK) is False

    # 4. ConsentManager must fail closed when relay events fail cryptographic verification
    mock_nostr = AsyncMock()
    mock_nostr.get_events.return_value = [forged_content_event]
    manager = ConsentManager(nostr_client=mock_nostr)
    grant = await manager.fetch_grant(HUMAN_PK, "agent_pubkey")
    assert grant is None


# ── Differential test: coincurve fast-path vs pure-Python fallback ─────────────


@pytest.mark.parametrize(
    "label,event,pubkey",
    [
        ("valid event", VALID_EVENT, HUMAN_PK),
        (
            "tampered content (id stale)",
            {**VALID_EVENT, "content": '{"scopes":["admin"],"expiration":1800000000}'},
            HUMAN_PK,
        ),
        (
            "wrong author pubkey",
            VALID_EVENT,
            "1111111111111111111111111111111111111111111111111111111111111111",
        ),
        (
            "zeroed signature",
            {**VALID_EVENT, "sig": "0" * 128},
            HUMAN_PK,
        ),
    ],
)
def test_coincurve_vs_python_differential(label, event, pubkey):
    """Asserts that coincurve PublicKeyXOnly and _verify_schnorr_python agree on every case.

    Both verifiers are called directly on the same (sig, pubkey, event_id) triple.
    This tests signature-level agreement only — id recomputation and author matching
    are wrapper-level defenses tested by verify_nostr_event_crypto below.
    """
    try:
        from coincurve import PublicKeyXOnly
    except ImportError:
        pytest.skip("coincurve not installed")

    evt = event if isinstance(event, dict) else VALID_EVENT
    sig_hex = evt.get("sig", "")
    pk_hex = evt.get("pubkey", pubkey)
    event_id_hex = evt.get("id", "")

    # coincurve path — directly invoked, no dispatch
    try:
        sig_bytes = bytes.fromhex(sig_hex)
        msg_bytes = bytes.fromhex(event_id_hex)
        pub_bytes = bytes.fromhex(pk_hex)
        coincurve_result = PublicKeyXOnly(pub_bytes).verify(sig_bytes, msg_bytes)
    except Exception:
        coincurve_result = False

    # Pure-Python path — directly invoked, bypasses coincurve dispatch
    python_result = _verify_schnorr_python(sig_hex, pk_hex, event_id_hex)

    # Both verifiers must agree — divergence here is a security-critical bug
    assert coincurve_result == python_result, (
        f"[{label}] coincurve={coincurve_result} but pure-Python={python_result} — "
        "verifiers diverged on the same input."
    )


# ── End-to-end wrapper tests: id recomputation + author match + crypto ─────────


@pytest.mark.parametrize(
    "label,event,pubkey,expected",
    [
        ("valid event", VALID_EVENT, HUMAN_PK, True),
        (
            "tampered content (id stale, recomputation catches it)",
            {**VALID_EVENT, "content": '{"scopes":["admin"],"expiration":1800000000}'},
            HUMAN_PK,
            False,
        ),
        (
            "wrong author pubkey (author-match catches it)",
            VALID_EVENT,
            "1111111111111111111111111111111111111111111111111111111111111111",
            False,
        ),
        (
            "zeroed signature (crypto rejects it)",
            {**VALID_EVENT, "sig": "0" * 128},
            HUMAN_PK,
            False,
        ),
    ],
)
def test_verify_nostr_event_end_to_end(label, event, pubkey, expected):
    """Tests the full verify_nostr_event_crypto wrapper which applies all three
    defense layers: author pubkey match, event id recomputation, and BIP-340
    Schnorr signature verification.
    """
    result = verify_nostr_event_crypto(event, pubkey)
    assert result == expected, f"[{label}] expected={expected}, got={result}"

"""Signed VoIP ring payloads.

See docs/agent-initiated-calls.md for the design. The short version: a PushKit
payload transits APNs and a push service, neither of which should be able to
fabricate a ring. Signing with the agent's Nostr key lets the device verify that
the agent named on the lock screen is the one that actually asked to call —
using the same BIP-340 verifier already used for consent events.

The device must complete verification without any network access, because iOS
requires reportNewIncomingCall() before the push handler returns.
"""

import json
import time
import uuid
import hashlib
from typing import Any, Dict, List, Optional

# APNs caps payloads at 4 KB. This is a hard ceiling, not a target — a ring
# carries identity and pointers, never content.
MAX_PAYLOAD_BYTES = 4096

# A ring is not durable. If the device has not seen it inside this window the
# call is missed, and re-ringing is the user's decision to allow.
DEFAULT_TTL_SECONDS = 60

SIGNED_FIELDS = ("v", "call_id", "agent", "name", "reason", "room", "ctx", "iat", "exp")


def canonical_bytes(payload: Dict[str, Any]) -> bytes:
    """Deterministic serialisation of everything except `sig`.

    Both sides must agree byte for byte, so: fixed field order, compact
    separators, no ASCII escaping (matching NIP-01 event id serialisation).
    """
    ordered = [payload.get(k) for k in SIGNED_FIELDS]
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def payload_digest(payload: Dict[str, Any]) -> bytes:
    return hashlib.sha256(canonical_bytes(payload)).digest()


def build_ring_payload(
    agent_pubkey: str,
    display_name: str,
    reason: str,
    room: str,
    context_pointers: Optional[List[str]] = None,
    call_id: Optional[str] = None,
    ttl: int = DEFAULT_TTL_SECONDS,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the unsigned payload. Call sign_ring_payload() before sending.

    `display_name` duplicates the agent's kind 0 metadata on purpose: the device
    needs it inside the push handler, before any relay is reachable. The device
    should still prefer its own cached profile, and must treat this copy as
    untrusted until the signature verifies.
    """
    issued = int(time.time()) if now is None else int(now)
    return {
        "v": 1,
        "call_id": call_id or str(uuid.uuid4()),
        "agent": agent_pubkey,
        "name": display_name,
        "reason": reason,
        "room": room,
        "ctx": list(context_pointers or []),
        "iat": issued,
        "exp": issued + int(ttl),
    }


def sign_ring_payload(payload: Dict[str, Any], sign) -> Dict[str, Any]:
    """Attach a BIP-340 signature over the canonical digest.

    `sign` takes 32 bytes and returns 64 signature bytes — e.g.
    `coincurve.PrivateKey.sign_schnorr`, or a NIP-07-style remote signer.
    """
    signed = dict(payload)
    signed["sig"] = sign(payload_digest(payload)).hex()

    encoded = json.dumps(signed, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"ring payload is {len(encoded)} bytes, over the {MAX_PAYLOAD_BYTES} byte "
            "APNs limit — shorten `reason` or move context into pointers"
        )
    return signed


def verify_ring_payload(
    payload: Dict[str, Any],
    expected_agent: str,
    now: Optional[int] = None,
    clock_skew: int = 30,
) -> bool:
    """Mirror of the device-side check, in the order the device runs it.

    Every step is local: expiry, then author, then signature. Present here so the
    scheme can be tested server-side and so both implementations have one
    reference to agree with.

    Replay rejection (has this call_id been seen?) is deliberately not handled
    here — it needs per-device state, and belongs with the caller.
    """
    from skills.voice_avatar.consent.manager import verify_schnorr

    ts = int(time.time()) if now is None else int(now)

    try:
        # Cheap rejections first — a stale or misaddressed ring never reaches
        # the curve math.
        if int(payload.get("exp", 0)) < ts:
            return False
        if int(payload.get("iat", 0)) > ts + clock_skew:
            return False
        agent = payload.get("agent", "")
        if not agent or agent.lower() != expected_agent.lower():
            return False

        return verify_schnorr(
            payload.get("sig", ""), agent, payload_digest(payload).hex()
        )
    except (ValueError, TypeError, KeyError):
        return False

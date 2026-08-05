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


class ReplayGuard:
    """Rejects a ring whose (agent, call_id) has already been consumed.

    A signature proves *origin*, not *freshness*. An attacker who captures a
    valid push can replay it verbatim: the signature still verifies, and the
    device rings for something that already happened. Expiry alone only narrows
    the window — inside it, replay is free.

    The store is self-bounding: an entry is only useful until the payload's own
    `exp`, after which the expiry check rejects it anyway. So retention is
    O(rings per TTL), not unbounded, and eviction needs no policy beyond time.

    Not thread-safe by design — the iOS push handler is single-threaded, and the
    agent-side equivalent should hold this behind whatever lock it already has.
    """

    def __init__(self, max_entries: int = 4096):
        self._seen: Dict[str, int] = {}
        self._max_entries = max_entries

    @staticmethod
    def _key(payload: Dict[str, Any]) -> str:
        # Scoped by agent: two agents may legitimately mint the same call_id.
        return f"{payload.get('agent', '')}:{payload.get('call_id', '')}"

    def _drop_expired(self, ts: int) -> None:
        for key in [k for k, exp in self._seen.items() if exp < ts]:
            del self._seen[key]

    def _enforce_cap(self) -> None:
        """Pathological case only: an attacker flooding distinct unexpired ids.
        Drop the soonest-to-expire first, so live rings outlive stale ones."""
        overflow = len(self._seen) - self._max_entries
        if overflow > 0:
            for key, _ in sorted(self._seen.items(), key=lambda kv: kv[1])[:overflow]:
                del self._seen[key]

    def consume(self, payload: Dict[str, Any], now: Optional[int] = None) -> bool:
        """True the first time a ring is seen, False on every replay."""
        ts = int(time.time()) if now is None else int(now)
        self._drop_expired(ts)

        key = self._key(payload)
        if key in self._seen:
            return False

        self._seen[key] = int(payload.get("exp", ts))
        # Capped after insertion, so the bound holds on exit rather than on entry.
        self._enforce_cap()
        return True

    def __len__(self) -> int:
        return len(self._seen)


def verify_ring_payload(
    payload: Dict[str, Any],
    expected_agent: str,
    now: Optional[int] = None,
    clock_skew: int = 30,
    replay_guard: Optional["ReplayGuard"] = None,
) -> bool:
    """Mirror of the device-side check, in the order the device runs it.

    Every step is local: expiry, then author, then signature. Present here so the
    scheme can be tested server-side and so both implementations have one
    reference to agree with.

    Pass a ReplayGuard to reject replays. It is optional only because the store
    is per-device state; omitting it leaves a captured push replayable inside its
    expiry window, so production callers should always supply one.
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

        if not verify_schnorr(
            payload.get("sig", ""), agent, payload_digest(payload).hex()
        ):
            return False

        # Consumed last: a forged ring must not be able to burn a call_id and
        # so block the genuine one that follows.
        if replay_guard is not None and not replay_guard.consume(payload, ts):
            return False

        return True
    except (ValueError, TypeError, KeyError):
        return False

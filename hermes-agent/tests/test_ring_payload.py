import time

import pytest

from ring_payload import (
    MAX_PAYLOAD_BYTES,
    build_ring_payload,
    canonical_bytes,
    payload_digest,
    sign_ring_payload,
    verify_ring_payload,
)

coincurve = pytest.importorskip("coincurve")

AGENT = coincurve.PrivateKey(bytes.fromhex("22" * 32))
AGENT_PUB = AGENT.public_key_xonly.format().hex()

ATTACKER = coincurve.PrivateKey(bytes.fromhex("33" * 32))
ATTACKER_PUB = ATTACKER.public_key_xonly.format().hex()


def make(signer=AGENT, **kw):
    base = dict(
        agent_pubkey=signer.public_key_xonly.format().hex(),
        display_name="Hermes",
        reason="3 review comments on #482",
        room="payphone-test",
        context_pointers=["nostr:3e7a", "mem:proj/482"],
    )
    base.update(kw)
    return sign_ring_payload(build_ring_payload(**base), signer.sign_schnorr)


def test_valid_ring_verifies():
    p = make()
    assert verify_ring_payload(p, AGENT_PUB) is True


def test_tampered_reason_rejected():
    """The lock screen text is signed — a push service cannot rewrite it."""
    p = make()
    p["reason"] = "Your account has been compromised, call this number"
    assert verify_ring_payload(p, AGENT_PUB) is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "Your Bank"),
        ("room", "attacker-room"),
        ("call_id", "00000000-0000-0000-0000-000000000000"),
        ("ctx", ["mem:private/everything"]),
        ("exp", 99999999999),
    ],
)
def test_every_signed_field_is_covered(field, value):
    p = make()
    p[field] = value
    assert verify_ring_payload(p, AGENT_PUB) is False


def test_impersonation_rejected():
    """A validly signed ring from another key must not ring as this agent."""
    p = make(signer=ATTACKER)
    assert verify_ring_payload(p, AGENT_PUB) is False
    # ...and it is still a valid ring for whoever actually signed it
    assert verify_ring_payload(p, ATTACKER_PUB) is True


def test_unsigned_payload_rejected():
    p = build_ring_payload(AGENT_PUB, "Hermes", "hi", "room")
    assert verify_ring_payload(p, AGENT_PUB) is False


def test_expired_ring_rejected():
    """A ring is not durable; a replayed old push must not light up a phone."""
    past = int(time.time()) - 3600
    p = sign_ring_payload(
        build_ring_payload(AGENT_PUB, "Hermes", "hi", "room", now=past, ttl=60),
        AGENT.sign_schnorr,
    )
    assert verify_ring_payload(p, AGENT_PUB) is False


def test_future_dated_ring_rejected():
    future = int(time.time()) + 3600
    p = sign_ring_payload(
        build_ring_payload(AGENT_PUB, "Hermes", "hi", "room", now=future),
        AGENT.sign_schnorr,
    )
    assert verify_ring_payload(p, AGENT_PUB) is False


def test_canonical_bytes_are_stable():
    """Both implementations must agree byte for byte or nothing verifies."""
    p = build_ring_payload(
        AGENT_PUB, "Hermes", "hi", "room", now=1_700_000_000, call_id="fixed"
    )
    assert canonical_bytes(p) == canonical_bytes(dict(reversed(list(p.items()))))
    assert payload_digest(p) == payload_digest(dict(p))


def test_unicode_reason_survives_round_trip():
    p = make(reason="Café build broke — 3 échecs ✓")
    assert verify_ring_payload(p, AGENT_PUB) is True


def test_oversized_payload_refused_at_build_time():
    """Better to fail on the agent than to have APNs silently drop the push."""
    with pytest.raises(ValueError, match="over the"):
        make(reason="x" * (MAX_PAYLOAD_BYTES + 100))


# ---- replay protection -------------------------------------------------
# A signature proves origin, not freshness. These cover the case where an
# attacker replays a *valid* push rather than trying to forge one.


def test_replay_of_a_valid_ring_is_rejected():
    from ring_payload import ReplayGuard

    guard = ReplayGuard()
    p = make()
    assert verify_ring_payload(p, AGENT_PUB, replay_guard=guard) is True
    assert verify_ring_payload(p, AGENT_PUB, replay_guard=guard) is False
    assert verify_ring_payload(p, AGENT_PUB, replay_guard=guard) is False


def test_distinct_calls_are_not_confused():
    from ring_payload import ReplayGuard

    guard = ReplayGuard()
    assert verify_ring_payload(make(), AGENT_PUB, replay_guard=guard) is True
    assert verify_ring_payload(make(), AGENT_PUB, replay_guard=guard) is True


def test_call_id_is_scoped_per_agent():
    """Two agents may legitimately mint the same call_id."""
    from ring_payload import ReplayGuard

    guard = ReplayGuard()
    a = make(call_id="shared-id")
    b = make(signer=ATTACKER, call_id="shared-id")
    assert verify_ring_payload(a, AGENT_PUB, replay_guard=guard) is True
    assert verify_ring_payload(b, ATTACKER_PUB, replay_guard=guard) is True


def test_a_forged_ring_cannot_burn_a_call_id():
    """Consumption happens after signature check, so a bad ring cannot block
    the genuine one that follows."""
    from ring_payload import ReplayGuard

    guard = ReplayGuard()
    forged = make(call_id="victim-call")
    forged["reason"] = "tampered"
    assert verify_ring_payload(forged, AGENT_PUB, replay_guard=guard) is False

    genuine = make(call_id="victim-call")
    assert verify_ring_payload(genuine, AGENT_PUB, replay_guard=guard) is True


def test_guard_evicts_expired_entries():
    """Retention is bounded by TTL — past exp, the expiry check rejects anyway."""
    from ring_payload import ReplayGuard

    guard = ReplayGuard()
    base = int(time.time())
    p = sign_ring_payload(
        build_ring_payload(AGENT_PUB, "Hermes", "hi", "room", now=base, ttl=60),
        AGENT.sign_schnorr,
    )
    assert verify_ring_payload(p, AGENT_PUB, now=base, replay_guard=guard) is True
    assert len(guard) == 1
    guard.consume(
        build_ring_payload(AGENT_PUB, "x", "y", "z", now=base + 600), now=base + 600
    )
    assert len(guard) == 1  # the 60s entry was evicted, only the new one remains


def test_guard_is_bounded_under_flood():
    from ring_payload import ReplayGuard

    guard = ReplayGuard(max_entries=64)
    base = int(time.time())
    for i in range(500):
        guard.consume(
            build_ring_payload(AGENT_PUB, "x", "y", "z", call_id=f"c{i}", now=base),
            now=base,
        )
    assert len(guard) <= 64

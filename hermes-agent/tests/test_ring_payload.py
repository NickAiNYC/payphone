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

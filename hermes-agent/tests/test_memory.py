"""Durable fact model, crypto envelope, and collapse rules.

Relay behaviour is verified by hand (see the write-path commit message); these
cover the logic that cannot be checked by looking at CLI output.
"""

import json

import pytest

pytest.importorskip("coincurve")

from memory import (  # noqa: E402
    KIND_DURABLE_FACT,
    DurableFact,
    build_fact_event,
    collapse,
    decode_fact_event,
    to_context_objects,
)
from nip44 import pubkey_from_privkey  # noqa: E402

AGENT = "a1" * 32
USER_PRIV = "b2" * 32
USER = pubkey_from_privkey(USER_PRIV)


def fact(summary="a claim", **kw):
    return DurableFact(summary=summary, **kw)


# ---- envelope ----------------------------------------------------------


def test_fact_round_trips_through_the_envelope():
    ev = build_fact_event(AGENT, USER, fact("Nick hates cold pizza", type="preference"))
    back = decode_fact_event(ev, AGENT, USER)
    assert back.summary == "Nick hates cold pizza"
    assert back.type == "preference"


def test_the_user_can_read_their_own_memory():
    """The conversation key is symmetric, so ownership is not just a claim."""
    ev = build_fact_event(AGENT, USER, fact("a private preference"))
    agent_pub = pubkey_from_privkey(AGENT)
    assert decode_fact_event(ev, USER_PRIV, agent_pub).summary == "a private preference"


def test_a_third_party_cannot_read_it():
    ev = build_fact_event(AGENT, USER, fact("a private preference"))
    stranger = "cc" * 32
    with pytest.raises(ValueError, match="MAC mismatch"):
        decode_fact_event(ev, stranger, pubkey_from_privkey(AGENT))


def test_summary_is_not_in_the_event():
    ev = build_fact_event(AGENT, USER, fact("the secret preference"))
    assert "the secret preference" not in json.dumps(ev)


def test_every_fact_gets_a_unique_d_tag():
    """Kind 31001 is parameterized-replaceable: facts sharing a d-tag replace
    each other on the relay. A shared tag would silently destroy memory."""
    a = build_fact_event(AGENT, USER, fact("first"))
    b = build_fact_event(AGENT, USER, fact("second"))
    d_of = lambda e: next(t[1] for t in e["tags"] if t[0] == "d")  # noqa: E731
    assert d_of(a) != d_of(b)
    assert a["kind"] == b["kind"] == KIND_DURABLE_FACT


def test_fact_is_addressed_to_the_user():
    ev = build_fact_event(AGENT, USER, fact())
    assert ["p", USER] in ev["tags"]


@pytest.mark.parametrize("bad", ["opinion", "", "FACT"])
def test_unknown_types_refused(bad):
    with pytest.raises(ValueError, match="type must be"):
        build_fact_event(AGENT, USER, fact(type=bad))


def test_empty_fact_refused_unless_it_supersedes():
    with pytest.raises(ValueError, match="needs a summary"):
        build_fact_event(AGENT, USER, fact(""))
    # ...but an empty fact that supersedes is a tombstone, which is allowed.
    build_fact_event(AGENT, USER, fact("", supersedes=["abc"]))


# ---- collapse ----------------------------------------------------------


def test_newest_first():
    out = collapse(
        [
            fact("old", fact_id="1", created_at=100),
            fact("new", fact_id="2", created_at=200),
        ]
    )
    assert [f.summary for f in out] == ["new", "old"]


def test_superseded_fact_disappears():
    out = collapse(
        [
            fact("hates cold pizza", fact_id="1", created_at=100),
            fact("likes it after all", fact_id="2", created_at=200, supersedes=["1"]),
        ]
    )
    assert [f.summary for f in out] == ["likes it after all"]


def test_tombstone_removes_without_adding():
    out = collapse(
        [
            fact("wrong claim", fact_id="1", created_at=100),
            fact("", fact_id="2", created_at=200, supersedes=["1"]),
        ]
    )
    assert out == []


def test_supersede_chain_leaves_only_the_survivor():
    out = collapse(
        [
            fact("v1", fact_id="1", created_at=100),
            fact("v2", fact_id="2", created_at=200, supersedes=["1"]),
            fact("v3", fact_id="3", created_at=300, supersedes=["2"]),
        ]
    )
    assert [f.summary for f in out] == ["v3"]


def test_one_fact_can_supersede_several():
    out = collapse(
        [
            fact("a", fact_id="1", created_at=100),
            fact("b", fact_id="2", created_at=110),
            fact("merged", fact_id="3", created_at=200, supersedes=["1", "2"]),
        ]
    )
    assert [f.summary for f in out] == ["merged"]


def test_supersede_of_an_unknown_id_is_kept():
    """A typo must not silently swallow the new fact — it becomes an orphan,
    which the CLI warns about at write time."""
    out = collapse([fact("orphan", fact_id="1", created_at=100, supersedes=["nope"])])
    assert [f.summary for f in out] == ["orphan"]


def test_unrelated_facts_coexist():
    out = collapse(
        [
            fact("prefers python", fact_id="1", created_at=100),
            fact("auth runs in eu-west-1", fact_id="2", created_at=200),
        ]
    )
    assert len(out) == 2


def test_ordering_is_stable_for_equal_timestamps():
    a = collapse(
        [fact("x", fact_id="1", created_at=5), fact("y", fact_id="2", created_at=5)]
    )
    b = collapse(
        [fact("y", fact_id="2", created_at=5), fact("x", fact_id="1", created_at=5)]
    )
    assert [f.fact_id for f in a] == [f.fact_id for f in b]


def test_context_objects_carry_provenance():
    objs = to_context_objects(
        collapse(
            [fact("prefers python", fact_id="1", created_at=100, type="preference")]
        )
    )
    assert objs[0]["kind"] == "durable_fact"
    assert objs[0]["type"] == "preference"
    assert objs[0]["learned"] == 100

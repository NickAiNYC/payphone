"""Consent cache isolation and revocation.

Both bugs covered here were live: the cache was keyed by the human alone, so a
second agent inherited the first agent's grant; and nothing dropped a cached
grant on revocation, so a revoked grant stayed usable until its own expiration
while the UI promised revocation "at any time".
"""

import asyncio

from skills.voice_avatar.consent.manager import ConsentGrant, ConsentManager

HUMAN = "aa" * 32
AGENT_A = "bb" * 32
AGENT_B = "cc" * 32


def grant(**kw):
    base = dict(
        scopes={"mic"},
        record=False,
        server_processing_opt_in=False,
        expiration=9999999999,
    )
    base.update(kw)
    return ConsentGrant(**base)


class Relay:
    """Stands in for a relay so the cache path is exercised."""

    def __init__(self):
        self.calls = 0


def test_grant_does_not_leak_between_agents():
    mgr = ConsentManager(nostr_client=Relay())
    # Agent A is granted the works, including cloud processing.
    mgr._cache[(HUMAN, AGENT_A)] = grant(
        scopes={"mic", "record"}, record=True, server_processing_opt_in=True
    )

    async def run():
        assert await mgr.check(HUMAN, AGENT_A, ["record"]) is True
        # Agent B was granted nothing and must inherit nothing.
        assert await mgr.check(HUMAN, AGENT_B, ["record"]) is False
        assert await mgr.check(HUMAN, AGENT_B, ["mic"]) is False

    asyncio.run(run())


def test_cache_is_keyed_by_both_parties():
    mgr = ConsentManager(nostr_client=Relay())
    mgr._cache[(HUMAN, AGENT_A)] = grant()
    assert (HUMAN, AGENT_A) in mgr._cache
    assert (HUMAN, AGENT_B) not in mgr._cache
    assert HUMAN not in mgr._cache  # the old, unsafe key shape


def test_revoke_drops_the_grant():
    mgr = ConsentManager(nostr_client=Relay())
    mgr._cache[(HUMAN, AGENT_A)] = grant()

    async def run():
        assert await mgr.check(HUMAN, AGENT_A, ["mic"]) is True
        assert mgr.revoke(HUMAN, AGENT_A) is True
        # With a relay attached and nothing cached, fetch_grant fails closed.
        assert await mgr.check(HUMAN, AGENT_A, ["mic"]) is False

    asyncio.run(run())


def test_revoke_is_scoped_to_one_agent():
    mgr = ConsentManager(nostr_client=Relay())
    mgr._cache[(HUMAN, AGENT_A)] = grant()
    mgr._cache[(HUMAN, AGENT_B)] = grant()

    assert mgr.revoke(HUMAN, AGENT_A) is True
    assert (HUMAN, AGENT_A) not in mgr._cache
    assert (HUMAN, AGENT_B) in mgr._cache


def test_revoke_all_clears_every_agent_for_one_human():
    mgr = ConsentManager(nostr_client=Relay())
    other_human = "dd" * 32
    mgr._cache[(HUMAN, AGENT_A)] = grant()
    mgr._cache[(HUMAN, AGENT_B)] = grant()
    mgr._cache[(other_human, AGENT_A)] = grant()

    assert mgr.revoke_all(HUMAN) == 2
    assert (other_human, AGENT_A) in mgr._cache


def test_revoking_nothing_reports_nothing():
    mgr = ConsentManager(nostr_client=Relay())
    assert mgr.revoke(HUMAN, AGENT_A) is False
    assert mgr.revoke_all(HUMAN) == 0

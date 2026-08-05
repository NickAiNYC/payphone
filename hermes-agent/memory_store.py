"""Relay I/O for durable facts.

Kept separate from memory.py so the fact model and the collapse rules can be
tested without a relay, and so a different backend can be swapped in later
without touching either.
"""

import asyncio
import json
import logging
from typing import List, Optional

import websockets

from memory import (
    KIND_DURABLE_FACT,
    DurableFact,
    agent_pubkey,
    build_fact_event,
    collapse,
    decode_fact_event,
)

logger = logging.getLogger(__name__)


async def publish_fact(
    relay_url: str, agent_privkey: str, user_pubkey: str, fact: DurableFact
) -> str:
    """Publish one fact. Returns the event id."""
    event = build_fact_event(agent_privkey, user_pubkey, fact)
    async with websockets.connect(relay_url) as ws:
        await ws.send(json.dumps(["EVENT", event]))
        resp = json.loads(await asyncio.wait_for(ws.recv(), 5))
        if not (resp[0] == "OK" and resp[2]):
            raise RuntimeError(f"relay rejected fact: {resp}")
    return event["id"]


async def fetch_facts(
    relay_url: str,
    agent_privkey: str,
    user_pubkey: str,
    limit: int = 200,
    timeout: float = 4.0,
) -> List[DurableFact]:
    """Every live fact this agent holds for this user, newest first.

    A fact that fails to decrypt is skipped rather than raising: one corrupt or
    foreign event must not cost the user the rest of their memory.
    """
    sub = "facts"
    facts: List[DurableFact] = []
    ours = agent_pubkey(agent_privkey)

    try:
        async with websockets.connect(relay_url) as ws:
            await ws.send(
                json.dumps(
                    [
                        "REQ",
                        sub,
                        {
                            "kinds": [KIND_DURABLE_FACT],
                            "authors": [ours],
                            "#p": [user_pubkey],
                            "limit": limit,
                        },
                    ]
                )
            )
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                if msg[0] == "EVENT" and msg[1] == sub:
                    try:
                        facts.append(
                            decode_fact_event(msg[2], agent_privkey, user_pubkey)
                        )
                    except Exception as err:
                        logger.warning("[Memory] undecodable fact skipped: %s", err)
                elif msg[0] == "EOSE" and msg[1] == sub:
                    break
    except (asyncio.TimeoutError, OSError) as err:
        logger.warning("[Memory] relay unreachable: %s", err)

    return collapse(facts)


async def fact_pointers(
    relay_url: str, agent_privkey: str, user_pubkey: str
) -> List[str]:
    """Pointers for the live facts, for the ring payload's `ctx` field."""
    return [
        f"mem:{f.fact_id}"
        for f in await fetch_facts(relay_url, agent_privkey, user_pubkey)
    ]


def make_fact_fetcher(relay_url: str, agent_privkey: str, user_pubkey: str):
    """A pointer resolver for context_resolver.resolve_context().

    Facts are fetched once and served from that snapshot, so resolving N
    pointers costs one relay round trip rather than N — which is what keeps
    resolution inside the first-utterance deadline.
    """
    cache: dict = {}
    loaded = False
    lock = asyncio.Lock()

    async def fetch(pointer: str) -> Optional[dict]:
        nonlocal loaded
        async with lock:
            if not loaded:
                for f in await fetch_facts(relay_url, agent_privkey, user_pubkey):
                    cache[f"mem:{f.fact_id}"] = {
                        "kind": "durable_fact",
                        "type": f.type,
                        "summary": f.summary,
                        "confidence": f.confidence,
                        "learned": f.created_at,
                    }
                loaded = True
        return cache.get(pointer)

    return fetch

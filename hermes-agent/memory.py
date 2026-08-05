"""Durable facts: write, read, supersede.

The smallest thing that can produce evidence. See
docs/write-path-assumptions.md for what counts as a fact and what is
deliberately excluded.

Trust model: a fact is signed by the agent and encrypted to the NIP-44
conversation key between the agent and the user. That key is symmetric by
construction, so both parties can read it and nobody else can — the user owns
their memory in the only sense that survives a public relay.

A note on kind 31001. It sits in NIP-01's parameterized-replaceable range
(30000–39999), where a relay replaces any event sharing (kind, pubkey, d-tag).
Facts published without a `d` tag would all share `d=""` and each new one would
silently delete the last. Every fact therefore carries a unique `d`. That also
buys a clean in-place update path later.
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from coincurve import PrivateKey

from nip44 import decrypt as nip44_decrypt
from nip44 import encrypt as nip44_encrypt
from nip44 import get_conversation_key, pubkey_from_privkey

KIND_DURABLE_FACT = 31001

FACT_TYPES = ("preference", "decision", "commitment", "fact")


@dataclass
class DurableFact:
    summary: str
    type: str = "fact"
    confidence: float = 1.0
    source_conversation_id: Optional[str] = None
    supersedes: List[str] = field(default_factory=list)
    created_at: int = 0
    fact_id: str = ""

    @property
    def is_tombstone(self) -> bool:
        """A supersede with no summary means: forget this, add nothing."""
        return not self.summary.strip()

    def to_content(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "summary": self.summary,
            "confidence": self.confidence,
            "source_conversation_id": self.source_conversation_id,
            "supersedes": self.supersedes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_content(cls, data: Dict[str, Any], fact_id: str, created_at: int):
        return cls(
            summary=str(data.get("summary", "")),
            type=str(data.get("type", "fact")),
            confidence=float(data.get("confidence", 1.0)),
            source_conversation_id=data.get("source_conversation_id"),
            supersedes=list(data.get("supersedes") or []),
            created_at=int(data.get("created_at") or created_at),
            fact_id=fact_id,
        )


def _finalize(privkey_hex: str, kind: int, tags: list, content: str) -> dict:
    priv = PrivateKey(bytes.fromhex(privkey_hex))
    pubkey = priv.public_key_xonly.format().hex()
    created_at = int(time.time())
    canonical = json.dumps(
        [0, pubkey, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    event_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "id": event_id,
        "pubkey": pubkey,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": priv.sign_schnorr(bytes.fromhex(event_id)).hex(),
    }


def build_fact_event(
    agent_privkey: str,
    user_pubkey: str,
    fact: DurableFact,
) -> dict:
    """Sign and encrypt a fact into a publishable event."""
    if fact.type not in FACT_TYPES:
        raise ValueError(f"type must be one of {FACT_TYPES}, got {fact.type!r}")
    if not fact.summary.strip() and not fact.supersedes:
        raise ValueError("a fact needs a summary, or must supersede something")

    fact.created_at = fact.created_at or int(time.time())
    key = get_conversation_key(agent_privkey, user_pubkey)
    content = nip44_encrypt(json.dumps(fact.to_content()), key)

    return _finalize(
        agent_privkey,
        KIND_DURABLE_FACT,
        [
            # Unique per fact, or the relay treats the next one as a replacement.
            ["d", fact.fact_id or uuid.uuid4().hex],
            ["p", user_pubkey],
        ],
        content,
    )


def decode_fact_event(event: dict, privkey: str, peer_pubkey: str) -> DurableFact:
    """Decrypt one fact event. Raises if the MAC does not verify."""
    key = get_conversation_key(privkey, peer_pubkey)
    data = json.loads(nip44_decrypt(event["content"], key))
    return DurableFact.from_content(
        data, fact_id=event["id"], created_at=int(event.get("created_at", 0))
    )


def collapse(facts: List[DurableFact]) -> List[DurableFact]:
    """Drop superseded facts and tombstones, newest first.

    Append-only storage means an override is a new fact pointing at the old
    one. Retrieval is where that resolves — no deletion required, which is the
    only workable answer on a replicated public relay.
    """
    superseded = {sid for f in facts for sid in f.supersedes}
    live = [f for f in facts if f.fact_id not in superseded and not f.is_tombstone]
    return sorted(live, key=lambda f: (f.created_at, f.fact_id), reverse=True)


def to_context_objects(facts: List[DurableFact]) -> List[Dict[str, Any]]:
    """Shape facts for injection into the model's context block."""
    return [
        {
            "kind": "durable_fact",
            "type": f.type,
            "summary": f.summary,
            "confidence": f.confidence,
            "learned": f.created_at,
        }
        for f in facts
    ]


def agent_pubkey(agent_privkey: str) -> str:
    return pubkey_from_privkey(agent_privkey)

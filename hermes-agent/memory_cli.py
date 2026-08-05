"""Write and read durable facts by hand.

Manual on purpose. Storage and retrieval must be provably correct before
automatic extraction is layered on, or a failure is ambiguous between a bad
prompt and broken crypto. See docs/write-path-assumptions.md.

    python3 hermes-agent/memory_cli.py add "Nick hates cold pizza" --type preference
    python3 hermes-agent/memory_cli.py list
    python3 hermes-agent/memory_cli.py add "Nick likes cold pizza after all" \\
        --supersedes <fact-id>
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory import FACT_TYPES, DurableFact  # noqa: E402
from memory_store import fetch_facts, publish_fact  # noqa: E402
from secure_storage import HermesSecureStorage  # noqa: E402

RELAY = os.environ.get("RELAY_URL", "ws://localhost:8080")
# The demo user. A real deployment addresses whoever is on the call.
USER = os.environ.get("MEMORY_USER_PUBKEY") or (
    "4f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa"
)


def agent_key() -> str:
    return HermesSecureStorage().load_key()


async def cmd_add(args) -> int:
    # A supersede pointing at nothing is just a new fact, so a mistyped or
    # truncated id silently creates an orphan duplicate instead of replacing
    # anything. Cheap to catch here; confusing to debug later.
    if args.supersedes:
        live = {f.fact_id for f in await fetch_facts(RELAY, agent_key(), USER)}
        for target in args.supersedes:
            if target not in live:
                print(
                    f"warning: --supersedes {target[:16]}… matches no live fact "
                    "(use the full id from `list`); storing as a new fact",
                    file=sys.stderr,
                )

    fact = DurableFact(
        summary=args.summary,
        type=args.type,
        confidence=args.confidence,
        source_conversation_id=args.conversation,
        supersedes=args.supersedes or [],
    )
    fact_id = await publish_fact(RELAY, agent_key(), USER, fact)
    verb = "superseded" if fact.supersedes else "stored"
    print(f"{verb}: {fact_id}")
    if fact.is_tombstone:
        print("  (tombstone — retrieval will treat the target as absent)")
    return 0


async def cmd_list(args) -> int:
    facts = await fetch_facts(RELAY, agent_key(), USER)
    if not facts:
        print("no durable facts")
        return 0
    print(f"{len(facts)} durable fact(s), newest first:\n")
    for f in facts:
        print(f"  [{f.type:11s}] {f.summary}")
        # Full id, not truncated: this is the value you paste into
        # --supersedes, and a prefix silently fails to match.
        print(f"  {'':13s} {f.fact_id}")
    return 0


async def cmd_recall(args) -> int:
    """What the agent would be handed about a topic. The read side of the loop."""
    facts = await fetch_facts(RELAY, agent_key(), USER)
    needle = args.query.lower()
    hits = [f for f in facts if needle in f.summary.lower()]
    if not hits:
        print(f'nothing durable about "{args.query}"')
        return 1
    for f in hits:
        print(f"{f.summary}  ({f.type})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="durable facts")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="store a durable fact")
    a.add_argument("summary", help="the claim, in plain language")
    a.add_argument("--type", choices=FACT_TYPES, default="fact")
    a.add_argument("--confidence", type=float, default=1.0)
    a.add_argument("--conversation", default=None)
    a.add_argument("--supersedes", nargs="*", help="fact ids this replaces")
    a.set_defaults(fn=cmd_add)

    ls = sub.add_parser("list", help="every live fact, newest first")
    ls.set_defaults(fn=cmd_list)

    r = sub.add_parser("recall", help="what the agent would know about a topic")
    r.add_argument("query")
    r.set_defaults(fn=cmd_recall)

    args = p.parse_args()
    return asyncio.run(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())

"""The deployment review scenario, end to end.

One agent, one human, one broken build, one memory chain. Every stage runs the
real module — signature, policy, replay guard, context resolver — against the
relay in docker-compose. Nothing here is mocked except the parts that are
explicitly labelled STUB in the output.

    docker compose up -d
    PYTHONPATH=hermes-agent:hermes-agent/skills \\
        python3 hermes-agent/demo/deployment_review.py

The point is not that a phone rings. It is that an autonomous identity decided
to interrupt a human, proved who it was, respected the human's boundaries, and
arrived already knowing where the conversation left off.
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

import websockets
from coincurve import PrivateKey

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_resolver import resolve_context  # noqa: E402
from memory import DurableFact  # noqa: E402
from memory_store import fact_pointers, make_fact_fetcher, publish_fact  # noqa: E402
from interruption_policy import InterruptionPolicy  # noqa: E402
from ring_payload import (  # noqa: E402
    ReplayGuard,
    build_ring_payload,
    sign_ring_payload,
    verify_ring_payload,
)
from secure_storage import HermesSecureStorage  # noqa: E402
from skills.voice_avatar.consent.manager import verify_nostr_event_crypto  # noqa: E402

RELAY = os.environ.get("DEMO_RELAY", "ws://localhost:8080")

# Deterministic keys so the scenario is reproducible across runs.
# The agent's real stored key, so durable facts written by the CLI are the
# same ones this scenario reads back.
AGENT_KEY = HermesSecureStorage().load_key()
HERMES = PrivateKey(bytes.fromhex(AGENT_KEY))
NICK = PrivateKey(bytes.fromhex("b2" * 32))
HERMES_PUB = HERMES.public_key_xonly.format().hex()
NICK_PUB = NICK.public_key_xonly.format().hex()

KIND_PROFILE = 0
KIND_PREFERENCES = 21006
KIND_MEMORY = 21008

DIM, BOLD, GREEN, YELLOW, CYAN, RESET = (
    "\033[2m",
    "\033[1m",
    "\033[32m",
    "\033[33m",
    "\033[36m",
    "\033[0m",
)


def scene(n, title):
    print(f"\n{BOLD}{CYAN}── {n}. {title}{RESET}")


def ok(msg):
    print(f"   {GREEN}✓{RESET} {msg}")


def note(msg):
    print(f"   {DIM}{msg}{RESET}")


def sign_event(priv, kind, content, tags=None):
    import hashlib

    pub = priv.public_key_xonly.format().hex()
    tags = tags or []
    created = int(time.time())
    canon = json.dumps(
        [0, pub, created, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    eid = hashlib.sha256(canon.encode()).hexdigest()
    return {
        "id": eid,
        "pubkey": pub,
        "created_at": created,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": priv.sign_schnorr(bytes.fromhex(eid)).hex(),
    }


async def publish(ws, event):
    await ws.send(json.dumps(["EVENT", event]))
    resp = json.loads(await asyncio.wait_for(ws.recv(), 5))
    if not (resp[0] == "OK" and resp[2]):
        raise RuntimeError(f"relay rejected event: {resp}")
    return event["id"]


async def fetch_event(event_id):
    """One connection per lookup.

    Concurrent REQ subscriptions multiplexed over a single socket race for
    recv() and swallow each other's EVENT frames — a real client needs a
    message router, and this demo just avoids the problem.
    """
    sub = f"get-{event_id[:8]}"
    try:
        async with websockets.connect(RELAY) as ws:
            await ws.send(json.dumps(["REQ", sub, {"ids": [event_id]}]))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
                if msg[0] == "EVENT" and msg[1] == sub:
                    return msg[2]
                if msg[0] == "EOSE" and msg[1] == sub:
                    return None
    except (asyncio.TimeoutError, OSError):
        return None


async def main():
    print(f"\n{BOLD}payphone · deployment review{RESET}")
    note(f"relay {RELAY}")
    note(f"hermes {HERMES_PUB[:16]}…   nick {NICK_PUB[:16]}…")

    async with websockets.connect(RELAY) as ws:
        # ── setup ───────────────────────────────────────────────────────────
        scene(1, "Identities and history on the relay")

        await publish(
            ws,
            sign_event(
                HERMES,
                KIND_PROFILE,
                json.dumps(
                    {
                        "name": "hermes",
                        "display_name": "Hermes",
                        "about": "Local-first voice agent · Whisper + Piper",
                        "nip05": "hermes@payphone.local",
                    }
                ),
            ),
        )
        ok("Hermes published its kind 0 profile")

        prefs_id = await publish(
            ws,
            sign_event(
                NICK,
                KIND_PREFERENCES,
                json.dumps(
                    {
                        "quiet_hours": {"start": "22:00", "end": "08:00", "tz": "UTC"},
                        "always_allow": ["security"],
                        "min_priority": "normal",
                    }
                ),
            ),
        )
        ok("Nick published kind 21006 — quiet hours 22:00–08:00, security exempt")

        yesterday = await publish(
            ws,
            sign_event(
                HERMES,
                KIND_MEMORY,
                json.dumps(
                    {
                        "kind": "conversation",
                        "topic": "auth middleware",
                        "summary": (
                            "Debugged token validation in the auth middleware. Validator "
                            "passes locally, fails in CI. Suspected env var fallback differs."
                        ),
                        "when": "yesterday 16:20",
                    }
                ),
            ),
        )
        today = await publish(
            ws,
            sign_event(
                HERMES,
                KIND_MEMORY,
                json.dumps(
                    {
                        "kind": "observation",
                        "topic": "auth middleware",
                        "summary": "CI run #4821 failed: test_token_validator, same assertion.",
                        "when": "today 09:14",
                    }
                ),
            ),
        )
        ok("Two memory objects written — yesterday's session, today's CI result")

        # A durable fact: smaller and longer-lived than the conversation it
        # came from. This is the object that makes the *second* interaction
        # different, and it survives restarts, models and devices.
        durable_id = await publish_fact(
            RELAY,
            AGENT_KEY,
            NICK_PUB,
            DurableFact(
                summary="Nick deploys on Fridays and wants CI failures raised same-day",
                type="preference",
                source_conversation_id="call-yesterday",
            ),
        )
        ok(f"One durable fact stored — kind 31001, encrypted to (agent, Nick)")
        note(f"  {durable_id[:24]}…")
        note(f"pointers: nostr:{yesterday[:12]}… nostr:{today[:12]}…")

        # ── the trigger ─────────────────────────────────────────────────────
        scene(2, "Hermes notices something")
        note(
            "CI run #4821 failed — test_token_validator, the same assertion as yesterday"
        )
        ok("Hermes has context that makes this worth a human's attention")

        # ── policy ──────────────────────────────────────────────────────────
        scene(3, "Should Hermes interrupt? (kind 21006, before signing anything)")
        prefs_ev = await fetch_event(prefs_id)
        policy = InterruptionPolicy.from_event_content(json.loads(prefs_ev["content"]))
        note("read back from the relay, not from local state")

        now = int(time.time())
        at_3am = int(datetime(2026, 8, 6, 3, 0, tzinfo=timezone.utc).timestamp())
        deferred = policy.may_interrupt(at_3am, category="deployment")
        print(
            f"   {YELLOW}·{RESET} at 03:00 → allowed={deferred.allowed} ({deferred.reason})"
        )
        note(
            f"     would hold the intent until {datetime.fromtimestamp(deferred.defer_until, timezone.utc):%H:%M UTC}"
        )

        decision = policy.may_interrupt(now, category="deployment", priority="normal")
        if not decision.allowed:
            print(
                f"   {YELLOW}·{RESET} right now → deferred ({decision.reason}). Nothing is minted."
            )
            return
        ok(f"right now → permitted ({decision.reason})")

        # ── intent ──────────────────────────────────────────────────────────
        scene(4, "Hermes signs an intent envelope")
        envelope = sign_ring_payload(
            build_ring_payload(
                agent_pubkey=HERMES_PUB,
                display_name="Hermes",
                reason="Deployment review — auth middleware",
                room="payphone-demo",
                context_pointers=[f"nostr:{yesterday}", f"nostr:{today}"],
            ),
            HERMES.sign_schnorr,
        )
        size = len(json.dumps(envelope).encode())
        ok(f"signed, {size} bytes (APNs ceiling 4096)")
        note(
            json.dumps({k: envelope[k] for k in ("reason", "room", "exp")}, indent=None)
        )

        # ── device ──────────────────────────────────────────────────────────
        scene(5, "The device verifies — all local, before the screen lights up")
        guard = ReplayGuard()
        assert verify_ring_payload(envelope, HERMES_PUB, replay_guard=guard)
        ok("expiry, author, BIP-340 signature, replay — accepted")

        tampered = dict(envelope)
        tampered["reason"] = "Your account has been compromised"
        assert not verify_ring_payload(tampered, HERMES_PUB, replay_guard=guard)
        ok("a push service rewriting the reason — rejected")

        assert not verify_ring_payload(envelope, HERMES_PUB, replay_guard=guard)
        ok("the same envelope replayed — rejected")

        print(f"\n   {BOLD}┌───────────────────────────────┐{RESET}")
        print(f"   {BOLD}│{RESET}  Hermes                       {BOLD}│{RESET}")
        print(
            f"   {BOLD}│{RESET}  {DIM}Deployment review —{RESET}          {BOLD}│{RESET}"
        )
        print(
            f"   {BOLD}│{RESET}  {DIM}auth middleware{RESET}              {BOLD}│{RESET}"
        )
        print(f"   {BOLD}└───────────────────────────────┘{RESET}")

        # ── context ─────────────────────────────────────────────────────────
        scene(6, "Context resolves while it rings")
        note("pointers are live kind 31001 facts, not fixtures")

        async def fetch_pointer(pointer):
            ev = await fetch_event(pointer.removeprefix("nostr:"))
            if ev is None:
                return None
            if not verify_nostr_event_crypto(ev, ev["pubkey"]):
                return None  # unverified memory is no memory
            return json.loads(ev["content"])

        # Durable memory the agent has actually accumulated, alongside the
        # per-call pointers in the envelope.
        mem_pointers = await fact_pointers(RELAY, AGENT_KEY, NICK_PUB)
        mem_fetch = make_fact_fetcher(RELAY, AGENT_KEY, NICK_PUB)

        async def fetch_any(pointer):
            if pointer.startswith("mem:"):
                return await mem_fetch(pointer)
            return await fetch_pointer(pointer)

        started = time.perf_counter()
        ctx = await resolve_context(
            envelope["ctx"] + mem_pointers, fetch_any, started_at=started
        )
        ok(
            f"{ctx.context_status.value} in {ctx.elapsed_ms} ms — {len(ctx.objects)} objects, signatures verified"
        )

        # ── hydration ───────────────────────────────────────────────────────
        scene(7, "What Hermes is handed before it speaks")
        print(json.dumps(ctx.to_prompt_state(), indent=2)[:700])

        scene(8, "Nick answers")
        if ctx.is_continuation:
            prior = next(
                (o for o in ctx.objects if o.get("kind") == "conversation"), {}
            )
            obs = next((o for o in ctx.objects if o.get("kind") == "observation"), {})
            print(f'   {BOLD}Hermes:{RESET} "Hey Nick. {obs.get("summary", "")}')
            print(f"           Yesterday we found the validator passes locally but")
            print(f'           fails in CI — you suspected the env var fallback."')
        else:
            print(f'   {BOLD}Hermes:{RESET} "Hey Nick — my long-term memory is not')
            print(f"           syncing right now, so let's just take today's topic.\"")

        print(
            f"\n{DIM}   STUB: APNs transport, and the spoken audio. Everything above —"
        )
        print(f"   identity, policy, signature, replay, resolution — is real.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())

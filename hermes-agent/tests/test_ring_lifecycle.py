import asyncio
from datetime import datetime, timezone

import pytest

from context_resolver import (
    ContextStatus,
    FallbackReason,
    SessionMode,
    resolve_context,
)
from interruption_policy import InterruptionPolicy

# ---------------------------------------------------------------- context ---
# The invariant under test: the model is never handed an ambiguous memory
# state. Every branch must name its mode explicitly.


async def _fetch_ok(pointer):
    return {"pointer": pointer, "body": "…"}


async def _fetch_denied(pointer):
    return None  # unauthorised resolves to nothing, it does not raise


def test_full_resolution_is_a_continuation():
    r = asyncio.run(resolve_context(["mem:a", "mem:b"], _fetch_ok))
    assert r.session_mode is SessionMode.CONTINUATION
    assert r.context_status is ContextStatus.READY
    assert len(r.objects) == 2
    assert r.is_continuation


def test_partial_resolution_degrades_but_still_continues():
    async def half(pointer):
        return {"p": pointer} if pointer.endswith("a") else None

    r = asyncio.run(resolve_context(["mem:a", "mem:b"], half))
    assert r.session_mode is SessionMode.CONTINUATION
    assert r.context_status is ContextStatus.DEGRADED
    assert r.unresolved == ["mem:b"]


def test_everything_denied_is_a_fresh_start_not_an_empty_continuation():
    """An empty object list must not read as 'I remember nothing happened'."""
    r = asyncio.run(resolve_context(["mem:a"], _fetch_denied))
    assert r.session_mode is SessionMode.FRESH_START
    assert r.reason is FallbackReason.UNAUTHORIZED


def test_no_pointers_is_a_fresh_start():
    r = asyncio.run(resolve_context([], _fetch_ok))
    assert r.session_mode is SessionMode.FRESH_START
    assert r.reason is FallbackReason.NO_POINTERS


def test_slow_relay_falls_back_within_the_deadline():
    async def slow(pointer):
        await asyncio.sleep(5)
        return {"p": pointer}

    r = asyncio.run(resolve_context(["mem:a"], slow, deadline_ms=120))
    assert r.session_mode is SessionMode.FRESH_START
    assert r.reason is FallbackReason.TIMEOUT
    assert r.elapsed_ms < 1000  # bailed at the deadline, did not wait 5s


def test_one_bad_pointer_does_not_sink_the_others():
    async def flaky(pointer):
        if pointer == "mem:bad":
            raise RuntimeError("corrupt object")
        return {"p": pointer}

    r = asyncio.run(resolve_context(["mem:ok", "mem:bad"], flaky))
    assert r.session_mode is SessionMode.CONTINUATION
    assert r.context_status is ContextStatus.DEGRADED


@pytest.mark.parametrize(
    "fetch,expected_keys",
    [
        (_fetch_ok, {"session_mode", "context_status", "resolved_count", "context"}),
        (
            _fetch_denied,
            {
                "session_mode",
                "context_status",
                "resolved_count",
                "unresolved_count",
                "reason",
            },
        ),
    ],
)
def test_prompt_state_is_always_explicit(fetch, expected_keys):
    r = asyncio.run(resolve_context(["mem:a"], fetch))
    state = r.to_prompt_state()
    assert expected_keys.issubset(state.keys())
    # never a null the model has to interpret
    assert all(v is not None for v in state.values())


# ----------------------------------------------------------------- policy ---
# Defends against the agent being annoying, rather than against an attacker.

NY = {"quiet_hours": {"start": "22:00", "end": "08:00", "tz": "UTC"}}


def _at(hour, minute=0):
    return int(datetime(2026, 8, 5, hour, minute, tzinfo=timezone.utc).timestamp())


def test_daytime_ring_permitted():
    p = InterruptionPolicy.from_event_content(NY)
    assert p.may_interrupt(_at(14)).allowed is True


@pytest.mark.parametrize("hour", [23, 2, 7])
def test_quiet_hours_defer_across_midnight(hour):
    p = InterruptionPolicy.from_event_content(NY)
    d = p.may_interrupt(_at(hour))
    assert d.allowed is False
    assert d.deferred is True
    assert d.defer_until > _at(hour)


def test_deferred_until_the_window_opens():
    p = InterruptionPolicy.from_event_content(NY)
    d = p.may_interrupt(_at(23))
    assert d.defer_until == _at(8) + 86400  # 08:00 the following morning


def test_always_allow_overrides_quiet_hours():
    p = InterruptionPolicy.from_event_content({**NY, "always_allow": ["security"]})
    assert p.may_interrupt(_at(3), category="security").allowed is True
    assert p.may_interrupt(_at(3), category="general").allowed is False


def test_never_allow_beats_everything():
    p = InterruptionPolicy.from_event_content(
        {**NY, "never_allow": ["marketing"], "always_allow": ["marketing"]}
    )
    assert p.may_interrupt(_at(14), category="marketing").allowed is False


def test_minimum_priority_gate():
    p = InterruptionPolicy.from_event_content({"min_priority": "high"})
    assert p.may_interrupt(_at(14), priority="normal").allowed is False
    assert p.may_interrupt(_at(14), priority="critical").allowed is True


def test_no_preferences_allows_rings():
    """The ring consent grant already failed closed; this layer only refines."""
    assert InterruptionPolicy().may_interrupt(_at(3)).allowed is True


def test_malformed_preferences_do_not_crash_the_ring_path():
    p = InterruptionPolicy.from_event_content(
        {"quiet_hours": {"start": "not-a-time", "end": "08:00", "tz": "Mars/Olympus"}}
    )
    assert p.may_interrupt(_at(3)).allowed is True

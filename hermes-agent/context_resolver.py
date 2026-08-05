"""Context reconstruction, and the state the model is told about it.

Resolution starts while the phone is still ringing, not after the user answers.
There are several seconds of dead time during the ring, and spending them is
free — by the time anyone picks up, the answer is usually already there.

The rule this module exists to enforce: **the model is never handed an ambiguous
memory state.** Passing `{"memory": null}` makes the model decide whether it
remembers, and it will decide badly — either confabulating continuity it does not
have, or stammering. Instead it is told, explicitly, which mode it is in:

    {"session_mode": "continuation", "context_status": "ready",  ...}
    {"session_mode": "fresh_start",  "context_status": "unavailable", "reason": ...}

A greeting written against `fresh_start` ("Hey Nick, my long-term memory is not
syncing — let's just take today's topic") is a fine experience. A greeting that
assumes continuity and then discovers it has none is not.

Audio is still never blocked on this. The deadline gates the *first utterance*,
not the media path.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Budget for the first utterance. Resolution normally begins at ring time, so
# this is the tail case where the relay is slow or the pointer is cold.
DEFAULT_DEADLINE_MS = 700


class ContextStatus(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"  # some pointers resolved, some did not
    UNAVAILABLE = "unavailable"


class SessionMode(str, Enum):
    CONTINUATION = "continuation"
    FRESH_START = "fresh_start"


class FallbackReason(str, Enum):
    TIMEOUT = "timeout"
    NO_POINTERS = "no_pointers"
    UNAUTHORIZED = "unauthorized"  # consent denied every pointer
    RESOLVER_ERROR = "resolver_error"


@dataclass
class ResolvedContext:
    """What the agent runtime is hydrated with. Never partially undefined."""

    session_mode: SessionMode
    context_status: ContextStatus
    objects: List[Dict[str, Any]] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    reason: Optional[FallbackReason] = None
    elapsed_ms: int = 0

    @property
    def is_continuation(self) -> bool:
        return self.session_mode is SessionMode.CONTINUATION

    def to_prompt_state(self) -> Dict[str, Any]:
        """The block handed to the model. Explicit in every branch."""
        state: Dict[str, Any] = {
            "session_mode": self.session_mode.value,
            "context_status": self.context_status.value,
            "resolved_count": len(self.objects),
        }
        if self.unresolved:
            state["unresolved_count"] = len(self.unresolved)
        if self.reason is not None:
            state["reason"] = self.reason.value
        if self.objects:
            state["context"] = self.objects
        return state


async def resolve_context(
    pointers: List[str],
    fetch: Callable[[str], Awaitable[Optional[Dict[str, Any]]]],
    deadline_ms: int = DEFAULT_DEADLINE_MS,
    started_at: Optional[float] = None,
) -> ResolvedContext:
    """Resolve pointers within a hard deadline, degrading rather than failing.

    `fetch` resolves one pointer, returning None when it cannot — a pointer the
    caller is not authorised for resolves to None rather than raising, so an
    unauthorised reference does not leak that the object exists.

    `started_at` is a perf_counter() taken when the ring was sent. Pass it and
    the deadline covers the whole ring-to-answer window, so work already done
    while the phone was buzzing counts.
    """
    begin = time.perf_counter() if started_at is None else started_at

    def elapsed() -> int:
        return int((time.perf_counter() - begin) * 1000)

    if not pointers:
        return ResolvedContext(
            session_mode=SessionMode.FRESH_START,
            context_status=ContextStatus.UNAVAILABLE,
            reason=FallbackReason.NO_POINTERS,
            elapsed_ms=elapsed(),
        )

    remaining = max(0.0, (deadline_ms - elapsed()) / 1000.0)

    async def one(pointer: str):
        try:
            return pointer, await fetch(pointer)
        except Exception as err:  # a bad pointer must not sink the others
            logger.warning("[Context] pointer %s failed: %s", pointer, err)
            return pointer, None

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(one(p) for p in pointers)), timeout=remaining
        )
    except asyncio.TimeoutError:
        logger.warning("[Context] deadline hit after %d ms", elapsed())
        return ResolvedContext(
            session_mode=SessionMode.FRESH_START,
            context_status=ContextStatus.UNAVAILABLE,
            unresolved=list(pointers),
            reason=FallbackReason.TIMEOUT,
            elapsed_ms=elapsed(),
        )
    except Exception as err:
        logger.error("[Context] resolver failed: %s", err)
        return ResolvedContext(
            session_mode=SessionMode.FRESH_START,
            context_status=ContextStatus.UNAVAILABLE,
            unresolved=list(pointers),
            reason=FallbackReason.RESOLVER_ERROR,
            elapsed_ms=elapsed(),
        )

    objects = [obj for _, obj in results if obj is not None]
    unresolved = [ptr for ptr, obj in results if obj is None]

    if not objects:
        # Everything was denied or missing. Treat as a fresh start rather than
        # letting the model infer continuity from an empty list.
        return ResolvedContext(
            session_mode=SessionMode.FRESH_START,
            context_status=ContextStatus.UNAVAILABLE,
            unresolved=unresolved,
            reason=FallbackReason.UNAUTHORIZED,
            elapsed_ms=elapsed(),
        )

    return ResolvedContext(
        session_mode=SessionMode.CONTINUATION,
        context_status=(
            ContextStatus.READY if not unresolved else ContextStatus.DEGRADED
        ),
        objects=objects,
        unresolved=unresolved,
        elapsed_ms=elapsed(),
    )

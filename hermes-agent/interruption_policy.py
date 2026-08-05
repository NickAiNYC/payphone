"""When an agent is allowed to interrupt a human.

Everything else in the ring path defends against an *attacker*. This defends
against the agent itself — an agent that decides its own interruption budget will
get it wrong, and one 3 a.m. ring for a passing CI failure costs more trust than
a hundred well-timed calls earn.

Read from the human's kind 21006 preference event and evaluated **before the
intent is signed**, so a ring that should not happen is never minted at all.

    {
      "quiet_hours": {"start": "22:00", "end": "08:00", "tz": "America/New_York"},
      "always_allow": ["security"],
      "never_allow": ["marketing"],
      "min_priority": "normal"
    }

Absent a preference event, rings are allowed: reaching the human at all already
required a `ring` consent grant, which fails closed on its own. This layer
refines a permission that was granted, it does not replace the grant.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional

try:  # stdlib on 3.9+, but keep the module importable if tzdata is missing
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

logger = logging.getLogger(__name__)

PRIORITY_ORDER = {"low": 0, "normal": 1, "high": 2, "critical": 3}


@dataclass
class Decision:
    allowed: bool
    reason: str
    # When deferred, the epoch second the ring becomes permissible. The agent
    # should hold the intent — not drop it, and not re-decide on its own.
    defer_until: Optional[int] = None

    @property
    def deferred(self) -> bool:
        return not self.allowed and self.defer_until is not None


@dataclass
class InterruptionPolicy:
    quiet_start: Optional[dtime] = None
    quiet_end: Optional[dtime] = None
    tz: str = "UTC"
    always_allow: List[str] = field(default_factory=list)
    never_allow: List[str] = field(default_factory=list)
    min_priority: str = "low"

    @classmethod
    def from_event_content(cls, content: Dict[str, Any]) -> "InterruptionPolicy":
        quiet = content.get("quiet_hours") or {}

        def parse(value: Optional[str]) -> Optional[dtime]:
            if not value:
                return None
            try:
                hh, mm = str(value).split(":")
                return dtime(int(hh), int(mm))
            except (ValueError, TypeError):
                logger.warning("[Policy] unparseable quiet hour %r, ignoring", value)
                return None

        return cls(
            quiet_start=parse(quiet.get("start")),
            quiet_end=parse(quiet.get("end")),
            tz=quiet.get("tz") or "UTC",
            always_allow=list(content.get("always_allow") or []),
            never_allow=list(content.get("never_allow") or []),
            min_priority=str(content.get("min_priority") or "low"),
        )

    def _local(self, ts: int) -> datetime:
        if ZoneInfo is None:
            return datetime.utcfromtimestamp(ts)
        try:
            return datetime.fromtimestamp(ts, ZoneInfo(self.tz))
        except Exception:
            logger.warning("[Policy] unknown timezone %r, falling back to UTC", self.tz)
            return datetime.fromtimestamp(ts, ZoneInfo("UTC"))

    def _in_quiet_hours(self, moment: datetime) -> bool:
        if self.quiet_start is None or self.quiet_end is None:
            return False
        now = moment.time()
        if self.quiet_start <= self.quiet_end:
            return self.quiet_start <= now < self.quiet_end
        # Window crosses midnight (22:00 → 08:00).
        return now >= self.quiet_start or now < self.quiet_end

    def _next_allowed(self, moment: datetime) -> int:
        """First moment past the quiet window, as an epoch second."""
        assert self.quiet_end is not None
        end_today = moment.replace(
            hour=self.quiet_end.hour,
            minute=self.quiet_end.minute,
            second=0,
            microsecond=0,
        )
        if end_today <= moment:
            end_today += timedelta(days=1)
        return int(end_today.timestamp())

    def may_interrupt(
        self, now: int, category: str = "general", priority: str = "normal"
    ) -> Decision:
        """Evaluate a proposed ring. Call before signing the intent."""
        if category in self.never_allow:
            return Decision(False, f"category '{category}' is never allowed")

        if PRIORITY_ORDER.get(priority, 1) < PRIORITY_ORDER.get(self.min_priority, 0):
            return Decision(
                False, f"priority '{priority}' below minimum '{self.min_priority}'"
            )

        moment = self._local(now)
        if self._in_quiet_hours(moment):
            if category in self.always_allow:
                return Decision(True, f"category '{category}' overrides quiet hours")
            # Deferred, not dropped: the agent still has something to say, and
            # should say it through a quieter surface or when the window opens.
            return Decision(
                False,
                "within quiet hours",
                defer_until=self._next_allowed(moment),
            )

        return Decision(True, "permitted")


DEFAULT_POLICY = InterruptionPolicy()

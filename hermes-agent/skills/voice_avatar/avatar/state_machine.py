import json, time
from typing import Literal, Optional, Callable, Set

AvatarState = Literal[
    "sleeping", "idle", "listening", "thinking", "speaking", "reacting", "tool_using"
]
Emotion = Literal["neutral", "happy", "sad", "curious", "focused"]

TRANSITIONS = {
    "sleeping": ["idle"],
    "idle": ["listening", "sleeping"],
    "listening": ["thinking", "idle"],
    "thinking": ["speaking", "tool_using", "idle"],
    "tool_using": ["thinking", "speaking"],
    "speaking": ["listening", "idle"],
    "reacting": ["idle", "listening", "thinking"],
}


class AvatarStateMachine:
    def __init__(self):
        self.state: AvatarState = "sleeping"
        self.emotion: Emotion = "neutral"
        self._listeners: Set[Callable[[dict], None]] = set()

    def on(self, fn: Callable[[dict], None]):
        self._listeners.add(fn)
        return lambda: self._listeners.discard(fn)

    def transition(
        self,
        next_state: Optional[AvatarState] = None,
        emotion: Optional[Emotion] = None,
        intensity: float = 1.0,
    ):
        target = next_state or self.state
        if target != self.state and target not in TRANSITIONS.get(self.state, []):
            return
        self.state = target
        if emotion:
            self.emotion = emotion
        self._emit(intensity)

    def set_emotion(self, e: Emotion, i: float = 1.0):
        self.emotion = e
        self._emit(i)

    def start_speaking(self):
        self.transition("speaking")

    def stop_speaking(self):
        self.transition("idle")

    def barge_in(self):
        self.transition("thinking")

    def tool_started(self):
        self.transition("tool_using")

    def wake(self):
        if self.state == "sleeping":
            self.transition("idle")

    def serialize(self) -> str:
        return json.dumps(
            {"s": self.state, "e": self.emotion, "i": 1, "t": int(time.time() * 1000)}
        )

    def _emit(self, intensity: float = 1.0):
        event = {
            "s": self.state,
            "e": self.emotion,
            "i": intensity,
            "t": int(time.time() * 1000),
        }
        for fn in self._listeners:
            fn(event)

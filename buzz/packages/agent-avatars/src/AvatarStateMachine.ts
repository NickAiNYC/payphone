export type AvatarState = "sleeping" | "idle" | "listening" | "thinking" | "speaking" | "reacting" | "tool_using";
export type Emotion = "neutral" | "happy" | "sad" | "curious" | "focused";

export interface AvatarStateEvent {
  s: AvatarState;
  e: Emotion;
  i: number;
  t: number;
}

const TRANSITIONS: Record<AvatarState, AvatarState[]> = {
  sleeping: ["idle"], idle: ["listening", "sleeping"],
  listening: ["thinking", "idle"], thinking: ["speaking", "tool_using", "idle"],
  tool_using: ["thinking", "speaking"], speaking: ["listening", "idle"], reacting: ["idle", "listening", "thinking"]
};

export class AvatarStateMachine {
  private state: AvatarState = "sleeping";
  private emotion: Emotion = "neutral";
  private listeners = new Set<(e: AvatarStateEvent) => void>();

  on(fn: (e: AvatarStateEvent) => void) { this.listeners.add(fn); return () => this.listeners.delete(fn); }

  transition(next: Partial<AvatarStateEvent>) {
    const target = next.s ?? this.state;
    if (target !== this.state && !TRANSITIONS[this.state].includes(target)) return;
    this.state = target;
    if (next.e) this.emotion = next.e;
    this.emit();
  }

  setEmotion(e: Emotion, i = 1) { this.emotion = e; this.emit({ i }); }
  startSpeaking() { this.transition({ s: "speaking" }); }
  stopSpeaking() { this.transition({ s: "idle" }); }
  bargeIn() { this.transition({ s: "thinking" }); }
  toolStarted() { this.transition({ s: "tool_using" }); }
  wake() { if (this.state === "sleeping") this.transition({ s: "idle" }); }

  serialize(): string {
    return JSON.stringify({ s: this.state, e: this.emotion, i: 1, t: Date.now() });
  }

  private emit(overrides: Partial<AvatarStateEvent> = {}) {
    const event: AvatarStateEvent = { s: this.state, e: this.emotion, i: overrides.i ?? 1, t: Date.now() };
    this.listeners.forEach(l => l(event));
  }
}

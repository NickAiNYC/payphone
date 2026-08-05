# Agent-initiated calls: design sketch

How an agent rings a phone, what the lock screen shows, and how the conversation
arrives with its context already loaded.

Nothing here is built yet. This is the design to build against, and the shape of
the mechanism if it ever needs describing precisely to someone else.

Three pieces:

1. [VoIP push payload](#1-voip-push-payload) — what crosses APNs
2. [CallKit mapping](#2-callkit-mapping-from-kind-0) — how a Nostr pubkey becomes a caller
3. [Context injection](#3-context-injection-handshake) — how state arrives without bloating the push

---

## The constraint everything else follows from

iOS gives one hard rule, and it dictates the whole design:

> **Every PushKit VoIP push must result in a call to
> `CXProvider.reportNewIncomingCall()` before the handler returns.**

Miss it and iOS kills the app. Miss it repeatedly and the system stops delivering
VoIP pushes to you at all. There is no retry and no grace.

So the push must carry **everything needed to draw the incoming-call screen with
no network round trip**. Not a fetch, not a relay query, not an image download.
Whatever the lock screen shows has to already be on the device or already be in
the payload.

That single rule is why the design splits into *display data* (in the push, or
pre-cached) and *conversation state* (fetched only after the user answers).

---

## 1. VoIP push payload

APNs caps payloads at 4 KB. Aim for a few hundred bytes — the payload carries
identity and references, never content.

```jsonc
{
  "v": 1,
  "call_id": "9f2c1a4e-…",          // idempotency + replay key
  "agent": "4f355bdc…71aa",         // Nostr pubkey (hex, 32 bytes)
  "name":  "Hermes",                // kind 0 display_name, denormalised
  "reason": "3 review comments on #482",
  "room":  "payphone-9f2c1a4e",     // LiveKit room, pre-warmed
  "ctx":   ["3e7a…", "mem:proj/482"], // pointers, NOT content
  "iat":   1785919106,              // issued-at, for staleness
  "exp":   1785919166,              // 60s — a ring is not durable
  "sig":   "08328fe9…"              // BIP-340 over the canonical payload
}
```

### Why `name` is denormalised into the payload

It duplicates kind 0, which is ugly. It is also unavoidable: the display name is
needed *inside the push handler*, before any relay is reachable. The device
should still prefer its cached kind 0 when it has one — the payload copy is the
cold-start fallback, and is treated as untrusted until the signature checks out.

### Why the payload is signed

APNs is Apple's infrastructure and your push service is a server. Neither should
be able to fabricate a ring. Signing the payload with the agent's Nostr key means
the device can verify that the agent whose name is on the lock screen is the
agent that actually asked to call.

This reuses machinery that already exists in the repo: the BIP-340 verifier in
[`consent/manager.py`](../hermes-agent/skills/voice_avatar/consent/manager.py)
was validated against libsecp256k1 across 616 differential cases, and the client
already carries `nostr-tools`.

The signature covers a canonical serialisation of every field except `sig`
itself — same construction as a Nostr event id: compact JSON, sorted keys, no
whitespace, `ensure_ascii=false`.

Verification on the device, in order, all before `reportNewIncomingCall`:

1. `exp` is in the future and `iat` is not absurdly old → else drop
2. `sig` verifies against `agent` → else drop
3. `(agent, call_id)` has not been consumed → else drop (replay)
4. `agent` is in the local roster with a live `ring` consent grant → else drop

Order matters. A signature proves *origin*, not *freshness* — an attacker who
captures a valid push can replay it verbatim and the signature still verifies.
Expiry narrows the window; inside it, replay is free without step 3.

Replay consumption comes **after** signature verification, not before, so a
forged ring cannot burn a `call_id` and block the genuine ring that follows.
The store is self-bounding: an entry is only useful until that payload's own
`exp`, after which step 1 rejects it anyway. Implemented as `ReplayGuard` in
[`ring_payload.py`](../hermes-agent/ring_payload.py).

All four are local. None require the network. A push failing any of them is
still reported to CallKit and immediately ended with
`CXCallEndedReason.failed` — because the OS requires *a* call to be reported,
and silently swallowing the push is what gets the app terminated.

### What must not go in the payload

`reason` is human-readable text that transits Apple's servers. "3 review comments
on #482" is fine. "Your biopsy results are back" is not.

Two options, and this is a product decision rather than a technical one:

- **Ship the reason.** Best lock screen, worst privacy. Fine for most agents.
- **Ship an opaque pointer** and have the device resolve the reason from its own
  encrypted store, falling back to a generic "Hermes is calling" when it cannot.
  Costs nothing when the device is warm.

A per-agent `ring_privacy` flag in kind 0 would let each agent choose.

---

## 2. CallKit mapping from kind 0

### Handle

```swift
let handle = CXHandle(type: .generic, value: npub)   // npub1…, not raw hex
```

Use `.generic`. Not `.phoneNumber` — the agent has no number. Not
`.emailAddress` — a NIP-05 identifier looks like an email but is not one, and
claiming otherwise makes iOS offer to email the agent.

The handle value is iOS's identity key: it drives Recents, call dedup, and
Contacts matching. It must be stable per agent forever, so use the npub rather
than anything derived from a session.

### Display name

```swift
let update = CXCallUpdate()
update.remoteHandle = handle
update.localizedCallerName = profile.displayName ?? profile.name ?? shortNpub
update.hasVideo = false
update.supportsGrouping = false
update.supportsUngrouping = false
update.supportsDTMF = false
update.supportsHolding = true
```

`localizedCallerName` is what the lock screen shows. It maps directly from kind 0
`display_name`, falling back to `name`, then to a truncated npub — the same
precedence already implemented in
[`profile.ts`](../buzz/packages/nostr/src/profile.ts).

### The picture problem

This is the non-obvious part, and it is worth knowing before you design the UI.

**CallKit will not display an arbitrary per-caller image.** There is no
`callerImageData` on `CXCallUpdate`. The two things that exist are:

- `CXProviderConfiguration.iconTemplateImageData` — a single monochrome
  *template* image for the whole app. Not per-agent, and rendered as a mask, so
  a photo is meaningless here.
- The system Contacts card — if the incoming handle matches a `CNContact`, iOS
  shows that contact's photo.

So getting an agent's kind-0 picture onto the lock screen means **writing the
agent into Contacts**:

```swift
let contact = CNMutableContact()
contact.givenName = profile.displayName ?? "Agent"
contact.imageData = cachedPictureJPEG          // from kind 0 `picture`
contact.contactRelations = []
contact.instantMessageAddresses = [
  CNLabeledValue(label: "payphone",
                 value: CNInstantMessageAddress(username: npub, service: "payphone"))
]
```

This is a real product decision with real consequences:

- It needs `CNContactStore` write permission, which users reasonably question.
- It puts AI agents in the user's actual address book, mixed with humans.
- It is the *only* way to get the agent's face on a native incoming call.

I would ship without it first — app icon plus `localizedCallerName` is a
perfectly good incoming call — and offer "Add Hermes to Contacts" as an explicit
opt-in that upgrades the experience. Never write contacts silently.

### Cache kind 0 at roster time, not ring time

Profile and picture must be on disk before the first ring. Fetch on add, refresh
opportunistically after each call, and store the decoded picture as JPEG next to
the pubkey. The push handler must never touch the network.

### LiveKit and the audio session

The one LiveKit-specific gotcha: disable the SDK's automatic `AVAudioSession`
configuration and let CallKit own it.

```swift
AudioManager.shared.audioSession.isAutomaticConfigurationEnabled = false

func provider(_ p: CXProvider, didActivate session: AVAudioSession) {
    AudioManager.shared.audioSession.audioSessionDidActivate(session)
}
func provider(_ p: CXProvider, didDeactivate session: AVAudioSession) {
    AudioManager.shared.audioSession.audioSessionDidDeactivate(session)
}
```

If both CallKit and the SDK try to configure the session, you get a call that
connects with no audio — and it reproduces only on device, never in the
simulator.

---

## 3. Context-injection handshake

### Pointers, not payloads

The push carries references. Resolution happens after the user answers, over an
authenticated channel. Four reasons, in order of importance:

1. **Privacy** — conversation state never transits Apple.
2. **Revocability** — a pointer can be dead by the time it is resolved. Embedded
   content cannot be recalled.
3. **Consent timing** — the consent check runs at resolve time, against the
   grant as it stands *now*, not as it stood when the push was queued.
4. **Size** — 4 KB does not hold a conversation.

### Flow

```
agent                     relay / APNs                    device
  │                                                          │
  ├─ decides to ring                                         │
  ├─ check kind 21005 grant has "ring" ──────────────────────┤
  ├─ pre-warm LiveKit room, mint token                       │
  ├─ build payload, sign with agent key                      │
  ├─ POST to push service ──────► APNs ─────────────────────►│
  │                                                          ├─ verify exp/replay/sig/grant  (all local)
  │                                                          ├─ reportNewIncomingCall()      (< run loop)
  │                                                          │
  │                                              ╭───────────┴─ user answers
  │                                              │           │
  │                                              │           ├─ CXAnswerCallAction
  │                                              │           ├─ join LiveKit room  ─── audio starts NOW
  │                                              │           │
  │                                              │           ├─ resolve ctx pointers (concurrent)
  │◄─────────────────────────────────────────────┼───────────┤   REQ kinds:[…] ids:[…]
  ├─ agent already holds state                   │           ├─ NIP-44 decrypt with owner key
  │                                              │           ├─ hydrate UI: threads, diff, summary
  ├─ speaks ──────────────────────────────────────────────► │
  │                                                          │
  ╰─ on end: SkillRefiner + summariser ◄─────────────────────╯
```

### Audio must not wait for context — but the greeting must

Two rules that look contradictory and are not.

**Never block the media path.** A user who swipes to answer and hears two
seconds of silence has already had a bad call.

**Never let the model guess whether it remembers.** Opening audio while
resolution is still in flight means the first sentence is written against an
unknown state. If it assumes continuity and resolution then fails, the agent
stammers or confabulates — worse than admitting it has no context.

Resolution therefore starts **while the phone is still ringing**, not on answer.
There are several seconds of dead time during the ring and spending them is
free; by the time anyone picks up the answer is usually already there. The
deadline gates the *first utterance*, not the audio.

The model is never handed `{"memory": null}` and left to interpret it. It is
told which mode it is in:

```jsonc
{"session_mode": "continuation", "context_status": "ready",
 "resolved_count": 3, "context": [ … ]}

{"session_mode": "fresh_start", "context_status": "unavailable",
 "reason": "timeout", "unresolved_count": 2}
```

A greeting written against `fresh_start` — *"Hey Nick, my long-term memory is
not syncing, let's just take today's topic"* — is a perfectly good experience.
A greeting that assumes continuity and discovers it has none is not.

Partial resolution is its own state: `degraded` still means continuation, since
some context beats none, but the model knows not to claim completeness.
Everything denied is **not** an empty continuation — it is a fresh start, or an
empty object list reads to the model as "nothing happened."

Implemented in [`context_resolver.py`](../hermes-agent/context_resolver.py).

### Pointer types

```
nostr:<event-id>        an event on a relay — signed, verifiable
mem:<scope>/<key>       an encrypted memory object owned by the agent key
room:<name>             a LiveKit room to join rather than create
doc:<workspace-id>      a shared surface to open alongside the call
```

Every pointer resolves through the consent gate. A pointer to a memory slice the
caller has not granted access to resolves to nothing — it does not error, and it
does not leak that the object exists.

### Decline and timeout

`CXEndCallAction` before answer publishes a decline event so the agent knows the
outcome and can fall back to a notification or a written summary. A ring with no
response inside `exp` is a missed call: the agent should not re-ring
immediately, and repeated rings need a backoff the *user* controls, not the
agent.

### Not being annoying

Every other check defends against an attacker. This one defends against the
agent. An agent that sets its own interruption budget will get it wrong, and a
single 3 a.m. ring about a passing CI failure costs more trust than a hundred
well-timed calls earn.

The human's preferences live in a kind 21006 event and are evaluated **before
the intent is signed**, so a ring that should not happen is never minted:

```jsonc
{ "quiet_hours": {"start": "22:00", "end": "08:00", "tz": "America/New_York"},
  "always_allow": ["security"], "never_allow": ["marketing"],
  "min_priority": "normal" }
```

A blocked ring is *deferred*, not dropped — the agent still has something to
say and should either wait for the window or use a quieter surface. The
decision carries `defer_until` so the agent does not re-decide for itself.

Absent any preference event, rings are allowed: reaching the human already
required a `ring` grant, which fails closed on its own. This layer refines a
permission that was granted rather than replacing the grant.

Implemented in [`interruption_policy.py`](../hermes-agent/interruption_policy.py).

### Consent

Extend kind 21005 with a `ring` scope, and fail closed — an agent without it
gets no push at all. The check belongs in two places:

- **Server side**, before queueing the push, so it is not sent at all.
- **Device side**, before reporting the call, so a compromised push service
  cannot ring a phone for an agent the user never authorised.

Defence in depth matters here specifically because ringing someone's phone is
the most intrusive thing an agent in this system can do.

---

## Open questions

- **Key rotation.** Signed rings are verified against the agent's current
  pubkey. Rotation needs a device-visible transition, or every rotation looks
  like an impersonation attempt. This interacts with memory epoch keys and
  should be designed once, for both.
- **Multi-device.** Ringing every device is correct; only one should win. CallKit
  has no cross-device arbitration, so the room join is the natural point of
  election.
- **Rate limiting.** Belongs with the user, enforced on-device, not with the
  agent. An agent that decides its own ring budget will get it wrong.
- **Do Not Disturb.** VoIP pushes can break through Focus. That is a privilege
  worth being conservative with; consider defaulting agents to *not* breaking
  through and letting the user promote individual ones.

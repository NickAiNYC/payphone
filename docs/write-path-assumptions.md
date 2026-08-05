# Write path assumptions

Written before the code, deliberately. This file exists to stop the memory
system quietly becoming a knowledge graph before anyone has shown that a single
durable fact changes what a user does.

The milestone is **evidence generation**, not memory. The write path is only
valuable because it produces something observable in a second interaction.

## What counts as a durable fact

A statement that would still be true and still be useful next week.

- `preference` — "prefers Python over Go for data pipelines"
- `decision` — "decided not to migrate off Postgres this quarter"
- `commitment` — "owes the design review by Friday"
- `fact` — "the auth service runs in eu-west-1"

One claim per object, in plain language, meaningful without the conversation it
came from. If it needs the transcript to make sense, it is not a durable fact.

## What is intentionally not stored

- Transcripts. The whole point is that the durable object is smaller and
  longer-lived than the conversation.
- Anything the user did not say or clearly imply. No inference about mood,
  competence, health or relationships.
- Anything with a natural expiry shorter than a week — "is in a meeting now".
- Credentials, keys, or anything that looks like one.
- Embeddings, vectors, or a search index. Retrieval is: fetch this user's facts,
  most recent first. If that stops being enough, that is a finding, not a
  failure.

## When the LLM is allowed to write memory

**Right now: never.** Facts are written by an explicit call to
`/api/memory/add` or the CLI.

This is the deliberate order. Storage and retrieval have to be provably correct
before extraction is layered on, or a failure is ambiguous between a broken
prompt and broken crypto. Automatic extraction is a separate project and starts
only once the manual loop is boring.

## How a user deletes or overrides memory

Relays are append-only and replicated; a delete request cannot be honoured by
retracting bytes that are already elsewhere. So:

- **Override** — write a new fact carrying `supersedes: [<old id>]`. Retrieval
  drops superseded facts and takes the most recent survivor.
- **Delete** — write a tombstone: a fact that supersedes the target and carries
  no summary. Retrieval treats it as absence.
- **Forget everything** — the facts are encrypted to the conversation key
  between the user and the agent. Destroying the agent's key makes every fact
  permanently unreadable by anyone. That is the only honest delete on a public
  relay, and it is all-or-nothing.

The limitation is real and is recorded in
[security-status.md](security-status.md) rather than glossed.

## Evidence that would make us redesign this

- A user cannot tell whether a fact was stored. → retrieval must be visible.
- Facts accumulate faster than they are used. → extraction is too eager;
  a fact nobody retrieves is a liability, not an asset.
- Users override facts often. → the schema is wrong, or extraction infers.
- Chronological retrieval stops finding the relevant fact past ~50 facts.
  → *then* consider ranking. Not before.
- The second interaction is not noticeably different from the first.
  → the entire thesis is wrong, and no amount of memory engineering fixes it.

## Success criteria for the first commit

Small on purpose.

1. An interaction ends and exactly one durable object exists that did not before.
2. A later interaction retrieves it.
3. The retrieval changes the agent's response in a way the user notices.
4. It survives a process restart.

Nothing about ontologies, conflict resolution, epochs, semantic search or
provider portability yet.

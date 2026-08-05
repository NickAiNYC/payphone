# Security status — August 2026

Current as of `38057bc` plus the P0 pass. The point of this file is that a
reviewer should not have to infer the security posture from commit history, and
that the README cannot drift ahead of the implementation again without this
document visibly contradicting it.

If something here disagrees with marketing language elsewhere in the
repository, **this file is correct and the other place is a bug.**

---

## Implemented and verified

| Property | Mechanism | How it was verified |
|---|---|---|
| Signaling confidentiality | NIP-44 v2 — ECDH on the raw shared x-coordinate, HKDF-extract with `nip44-v2`, per-message HKDF-expand keyed by a 32-byte nonce, ChaCha20 | Cross-checked against `nostr-tools` in **both** directions: matching conversation key, Python→JS and JS→Python payloads, and a full two-layer gift wrap built by the real client path decrypting in the agent |
| Signaling integrity | HMAC-SHA256 over `nonce‖ciphertext`, compared in constant time **before** decrypting | Tampered ciphertext, tampered MAC, wrong key and version downgrade all rejected |
| Length hiding | Power-of-two padding buckets | Different plaintext lengths sharing a bucket produce identical ciphertext length |
| Event authenticity | BIP-340 Schnorr over the NIP-01 canonical id | 616-case differential harness against libsecp256k1; mutation-tested — breaking the curve math fails the suite |
| Sender authenticity | Inbound trusts the **signed seal's** author, not the unsigned rumor's self-declared pubkey | Covered in the gift-wrap interop test |
| Ring authenticity | BIP-340 over a canonical digest of every field | Tampering any signed field is rejected; a valid signature from another key is rejected for this agent |
| Ring freshness | 60 s expiry, 30 s skew tolerance, plus a `(agent, call_id)` replay guard consumed **after** signature verification | Replay, expiry, future-dating and forged-ring-burning-a-call-id all covered |
| Consent isolation | Cache keyed by `(human, agent)` | A grant to one agent does not satisfy a check for another |
| Consent revocation | `revoke()` / `revoke_all()` drop cached grants so the next check re-reads | Revoked grant fails closed immediately |
| Consent fail-closed | With a relay attached and no grant found, `fetch_grant` returns `None` | Verified across all three paths — no client, client with empty cache, client with a valid grant |
| TURN credentials | Short-lived HMAC-SHA1 REST credentials; the static secret never reaches the browser | Verified against live coturn: valid allocates, wrong password and expired timestamp both refused |
| Endpoint gate | `X-API-Key` on `/api/ice`, `/api/call/offer`, `/api/call/hangup` | Verified live: 401 with no key, 401 with a wrong key, 200 with the right one |

---

## Intentionally unsupported

Not oversights. These are decisions, and each has a reason.

- **Encrypted memory objects.** Memory is currently written in plaintext by the
  demo scenario. Encryption is deliberately deferred until the write path
  exists, because the epoch-key design has to be decided before the first
  durable write, not retrofitted after.
- **Per-user authentication on the HTTP API.** The `X-API-Key` gate stops
  drive-by abuse of a reachable deployment. It is not user auth: a browser
  client carries the key in its bundle where any user can read it. Per-user
  authentication belongs on the Nostr path, where the caller already proves key
  ownership by signing.
- **NIP-05 verification.** The identifier is displayed as plain text with **no
  verification affordance**, because `/.well-known/nostr.json` is not fetched or
  matched. A checkmark without that fetch is an impersonation vector.
- **Multi-relay publication.** One relay today. This forfeits redundancy and is
  a known single point of failure.

---

## Known limitations

Ranked by how much they would matter in production.

1. **No key recovery.** Losing the device loses the identity and everything
   bound to it. There is no social recovery, no escrow, no export flow. At any
   real scale this produces users who cannot be helped.
2. **No key rotation.** Identity keys are permanent. Rotation interacts with
   memory epoch keys and ring signature verification, and should be designed
   once for all three.
3. **No forward secrecy.** NIP-44 conversation keys are static per key pair.
   Compromise of a long-term key decrypts all past traffic that anyone
   archived — and relays are public, replicated and permanent.
4. **Ephemeral client identity.** Without a NIP-07 extension the client
   generates a new keypair per page load, so consent grants do not survive a
   refresh.
5. **Prompt injection through memory.** Resolved memory objects are injected
   into model context. The signature proves the agent authored the object, not
   that its content is safe — and the agent signs its own summaries of
   user-supplied text. There is no sanitisation boundary.
6. **No rate limiting** anywhere.
7. **No observability.** No metrics, tracing or error reporting. An incident
   would be debugged by reading container logs.
8. **Unbounded relay storage.** `strfry.conf` sets a 10 TiB map with no
   retention policy. There is no deletion path, which conflicts directly with
   an erasure request against an append-only replicated log.
9. **`secure_storage` dev fallback** writes the master key in plaintext beside
   the ciphertext it protects, guarded only by `ENVIRONMENT=production`, which
   nothing sets by default.
10. **Default secrets in `.env.example`** (`COTURN_SECRET=coturnsecret`). People
    deploy examples.

---

## Fixed, and worth recording

Three defects that were live and are not obvious from the current code:

- **Signaling was not encrypted.** `FallbackCryptographer` prepended 12 random
  bytes and base64-encoded — no key, no cipher — on the default path for any
  user without a NIP-07 extension. The agent held a symmetric key hardcoded in
  this public repository and returned ciphertext unchanged on decryption
  failure, silently accepting plaintext.
- **The agent's outbound Nostr path had never worked.** Gift wraps were
  published with `"pubkey": "throwaway_agent_pubkey"` and
  `"sig": "mock_signature"`. Any relay that validates signatures drops those.
- **Consent leaked between agents.** The cache was keyed by the human alone.

---

## Reporting

Vulnerabilities via
[GitHub private reporting](https://github.com/NickAiNYC/payphone/security/advisories/new).

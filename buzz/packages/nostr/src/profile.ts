/**
 * NIP-01 kind 0 profile metadata.
 *
 * An agent is a pubkey, so its display name and picture come from the same
 * identity you call — the standard Nostr metadata event, readable by any client,
 * not a payphone-specific side channel.
 */

export interface NostrProfile {
  pubkey: string;
  name?: string;
  display_name?: string;
  about?: string;
  picture?: string;
  nip05?: string;
}

/** Best display name available.
 *  Falls back to `fallback` when the agent has published no kind 0, and only
 *  then to a truncated pubkey — a raw key is a poor thing to show a caller. */
export function profileLabel(
  p: NostrProfile | null,
  pubkey: string,
  fallback?: string
): string {
  return (
    p?.display_name?.trim() ||
    p?.name?.trim() ||
    fallback?.trim() ||
    `${pubkey.slice(0, 8)}…${pubkey.slice(-4)}`
  );
}

/**
 * Fetch the newest kind 0 for `pubkey` from a relay.
 *
 * Opens its own short-lived socket rather than sharing the call signaling
 * socket: profile lookup happens before a call exists, and must never delay or
 * fail one.
 */
export function fetchProfile(
  relayUrl: string,
  pubkey: string,
  timeoutMs = 4000
): Promise<NostrProfile | null> {
  return new Promise(resolve => {
    let socket: WebSocket;
    let newest: { at: number; profile: NostrProfile } | null = null;
    let done = false;

    const finish = (value: NostrProfile | null) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      try { socket?.close(); } catch { /* already closing */ }
      resolve(value);
    };

    const timer = setTimeout(() => finish(newest?.profile ?? null), timeoutMs);

    try {
      socket = new WebSocket(relayUrl);
    } catch (err) {
      console.warn("[Nostr] profile socket failed to open:", err);
      return finish(null);
    }

    const subId = `profile-${pubkey.slice(0, 8)}`;

    socket.onopen = () => {
      socket.send(JSON.stringify(["REQ", subId, { kinds: [0], authors: [pubkey], limit: 5 }]));
    };

    socket.onmessage = event => {
      try {
        const msg = JSON.parse(event.data);

        if (msg[0] === "EVENT" && msg[1] === subId) {
          const ev = msg[2];
          if (ev?.kind !== 0 || ev.pubkey !== pubkey) return;
          const meta = JSON.parse(ev.content || "{}");
          const at = Number(ev.created_at) || 0;
          // Relays may hold several; keep the most recent by created_at.
          if (!newest || at > newest.at) {
            newest = {
              at,
              profile: {
                pubkey,
                name: meta.name,
                display_name: meta.display_name,
                about: meta.about,
                picture: meta.picture,
                nip05: meta.nip05,
              },
            };
          }
        } else if (msg[0] === "EOSE" && msg[1] === subId) {
          finish(newest?.profile ?? null);
        }
      } catch {
        /* malformed event from an untrusted relay — ignore it */
      }
    };

    socket.onerror = () => finish(newest?.profile ?? null);
  });
}

/**
 * Average colour of a profile picture, as linear-ish 0..1 RGB, normalised so the
 * brightest channel is 1. Used to tint the avatar so each agent reads as
 * distinct while staying inside the same stylised language.
 *
 * Returns null if the image cannot be read — a remote host without permissive
 * CORS taints the canvas, and getImageData throws. The caller keeps its default.
 */
export function tintFromImage(url: string, timeoutMs = 5000): Promise<[number, number, number] | null> {
  return new Promise(resolve => {
    let done = false;
    const finish = (v: [number, number, number] | null) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve(v);
    };
    const timer = setTimeout(() => finish(null), timeoutMs);

    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onerror = () => finish(null);
    img.onload = () => {
      try {
        const size = 24;
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = size;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        if (!ctx) return finish(null);
        ctx.drawImage(img, 0, 0, size, size);
        const { data } = ctx.getImageData(0, 0, size, size);

        let r = 0, g = 0, b = 0, weight = 0;
        for (let i = 0; i < data.length; i += 4) {
          if (data[i + 3] < 24) continue; // skip transparent padding
          const [pr, pg, pb] = [data[i] / 255, data[i + 1] / 255, data[i + 2] / 255];
          const max = Math.max(pr, pg, pb);
          const min = Math.min(pr, pg, pb);
          // Weight by saturation so a mostly-grey photo does not wash the tint out.
          const w = 0.15 + (max - min);
          r += pr * w; g += pg * w; b += pb * w; weight += w;
        }
        if (weight === 0) return finish(null);

        r /= weight; g /= weight; b /= weight;
        const peak = Math.max(r, g, b, 0.001);
        // Normalise to full brightness; the shader controls actual luminance.
        finish([r / peak, g / peak, b / peak]);
      } catch {
        // Tainted canvas (no CORS headers on the picture host).
        finish(null);
      }
    };
    img.src = url;
  });
}

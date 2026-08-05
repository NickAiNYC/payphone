import { generateSecretKey, getPublicKey, finalizeEvent } from 'nostr-tools/pure';
import { nip44 } from 'nostr-tools';
import { finalizeEvent as finalize } from 'nostr-tools/pure';

// NIP-07 Browser Extension interface
export interface WindowNostr {
  getPublicKey(): Promise<string>;
  signEvent(event: any): Promise<any>;
  nip44?: {
    encrypt(peerPubkey: string, plaintext: string): Promise<string>;
    decrypt(peerPubkey: string, ciphertext: string): Promise<string>;
  };
}

export class NostrSignaling {
  private socket: WebSocket;
  private pubkey: string = "";
  private privKey?: Uint8Array;
  private nip07?: WindowNostr;
  private onAnswerCallback?: (sdp: string) => void;
  private onIceCallback?: (candidate: any) => void;

  constructor(private relayUrl: string, private agentPubkey: string) {
    if (typeof window !== 'undefined' && (window as any).nostr) {
      this.nip07 = (window as any).nostr as WindowNostr;
    }

    if (!this.nip07) {
      this.privKey = generateSecretKey();
      this.pubkey = getPublicKey(this.privKey);
      console.warn("[Nostr] No NIP-07 extension detected. Falling back to ephemeral keypair.");
    }

    this.socket = new WebSocket(relayUrl);
    this.setupSocket();
  }

  private async setupSocket() {
    if (this.nip07 && !this.pubkey) {
      try {
        this.pubkey = await this.nip07.getPublicKey();
        console.log("[Nostr] Initialized pubkey from NIP-07 extension:", this.pubkey);
      } catch (err) {
        console.warn("[Nostr] NIP-07 getPublicKey failed. Falling back to ephemeral keypair:", err);
        this.privKey = generateSecretKey();
        this.pubkey = getPublicKey(this.privKey);
      }
    }

    this.socket.onopen = () => {
      console.log("[Nostr] Connected to relay:", this.relayUrl, "User Pubkey:", this.pubkey);
      const sub = ["REQ", "sub-call", {
        kinds: [13],
        "#p": [this.pubkey]
      }];
      this.socket.send(JSON.stringify(sub));
    };

    this.socket.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg[0] === "EVENT") {
          const giftWrap = msg[2];
          if (giftWrap.kind === 13) {
            // Outer layer is from the wrap's throwaway key, inner from the
            // real sender's. A bad MAC throws and the event is discarded.
            const seal = JSON.parse(
              await this.decryptFrom(giftWrap.pubkey, giftWrap.content)
            );
            const rumor = JSON.parse(
              await this.decryptFrom(seal.pubkey, seal.content)
            );
            
            if (rumor.kind === 21001) {
              const content = JSON.parse(rumor.content);
              if (content.type === "answer" && this.onAnswerCallback) {
                this.onAnswerCallback(content.sdp);
              }
            } else if (rumor.kind === 21002 && this.onIceCallback) {
              const content = JSON.parse(rumor.content);
              this.onIceCallback(content.candidate);
            }
          }
        }
      } catch (err) {
        console.error("[Nostr] Error decrypting incoming message:", err);
      }
    };
  }

  /** NIP-44 encrypt to `peerPubkey`. Uses the NIP-07 extension when it exposes
   *  nip44 (so the key never leaves it), otherwise our own key via nostr-tools.
   *  There is no unencrypted path — the previous fallback was base64. */
  private async encryptTo(peerPubkey: string, plaintext: string): Promise<string> {
    if (this.nip07?.nip44) {
      return this.nip07.nip44.encrypt(peerPubkey, plaintext);
    }
    if (!this.privKey) {
      throw new Error("[Nostr] no key available to encrypt with");
    }
    return nip44.encrypt(plaintext, nip44.getConversationKey(this.privKey, peerPubkey));
  }

  /** Decrypt a payload authored by `peerPubkey`. Throws on a bad MAC. */
  private async decryptFrom(peerPubkey: string, ciphertext: string): Promise<string> {
    if (this.nip07?.nip44) {
      return this.nip07.nip44.decrypt(peerPubkey, ciphertext);
    }
    if (!this.privKey) {
      throw new Error("[Nostr] no key available to decrypt with");
    }
    return nip44.decrypt(ciphertext, nip44.getConversationKey(this.privKey, peerPubkey));
  }

  private async wrapInGift(rumor: any): Promise<any> {
    // Seal: the rumor encrypted to the agent, signed by us so the agent can
    // prove who sent it.
    const sealTemplate = {
      kind: 14,
      created_at: Math.floor(Date.now() / 1000),
      tags: [],
      content: await this.encryptTo(this.agentPubkey, JSON.stringify(rumor)),
    };

    const signedSeal = this.nip07
      ? await this.nip07.signEvent(sealTemplate)
      : finalize(sealTemplate, this.privKey!);

    // Gift wrap: the seal encrypted and signed under a throwaway key, so the
    // relay cannot correlate sender and recipient across events.
    const throwawayPriv = generateSecretKey();
    const wrapKey = nip44.getConversationKey(throwawayPriv, this.agentPubkey);

    return finalizeEvent(
      {
        kind: 13,
        created_at: Math.floor(Date.now() / 1000),
        tags: [["p", this.agentPubkey]],
        content: nip44.encrypt(JSON.stringify(signedSeal), wrapKey),
      },
      throwawayPriv
    );
  }

  async sendOffer(sdp: string): Promise<void> {
    const offerPayload = {
      type: "offer",
      sdp: sdp,
      pubkey: this.pubkey
    };

    const rumor = {
      kind: 21001,
      pubkey: this.pubkey,
      created_at: Math.floor(Date.now() / 1000),
      tags: [["p", this.agentPubkey]],
      content: JSON.stringify(offerPayload)
    };

    const giftWrap = await this.wrapInGift(rumor);
    this.socket.send(JSON.stringify(["EVENT", giftWrap]));
    console.log("[Nostr] NIP-17 Gift-wrapped offer sent to agent:", this.agentPubkey);
  }

  async sendIce(candidate: RTCIceCandidate): Promise<void> {
    const icePayload = {
      candidate: candidate.toJSON(),
      pubkey: this.pubkey
    };

    const rumor = {
      kind: 21002,
      pubkey: this.pubkey,
      created_at: Math.floor(Date.now() / 1000),
      tags: [["p", this.agentPubkey]],
      content: JSON.stringify(icePayload)
    };

    const giftWrap = await this.wrapInGift(rumor);
    this.socket.send(JSON.stringify(["EVENT", giftWrap]));
  }

  onAnswer(callback: (sdp: string) => void) {
    this.onAnswerCallback = callback;
  }

  onIce(callback: (candidate: any) => void) {
    this.onIceCallback = callback;
  }
}

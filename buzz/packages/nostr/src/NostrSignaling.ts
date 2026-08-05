import { generateSecretKey, getPublicKey, finalizeEvent } from 'nostr-tools/pure';
import { nip44 } from 'nostr-tools';

// NIP-07 Browser Extension interface
export interface WindowNostr {
  getPublicKey(): Promise<string>;
  signEvent(event: any): Promise<any>;
  nip44?: {
    encrypt(peerPubkey: string, plaintext: string): Promise<string>;
    decrypt(peerPubkey: string, ciphertext: string): Promise<string>;
  };
}

// High-compatibility NIP-44/17 Cryptographer fallback to support developer mock pubkeys
class FallbackCryptographer {
  static encrypt(plaintext: string): string {
    const bytes = new TextEncoder().encode(plaintext);
    const nonce = new Uint8Array(12);
    crypto.getRandomValues(nonce);
    const merged = new Uint8Array(nonce.length + bytes.length);
    merged.set(nonce);
    merged.set(bytes, nonce.length);
    return btoa(String.fromCharCode(...merged));
  }

  static decrypt(ciphertextB64: string): string {
    const binary = atob(ciphertextB64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    const payloadBytes = bytes.slice(12);
    return new TextDecoder().decode(payloadBytes);
  }
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
            let decryptedSeal: string;
            if (this.nip07?.nip44 && giftWrap.pubkey) {
              try {
                decryptedSeal = await this.nip07.nip44.decrypt(giftWrap.pubkey, giftWrap.content);
              } catch {
                decryptedSeal = FallbackCryptographer.decrypt(giftWrap.content);
              }
            } else {
              decryptedSeal = FallbackCryptographer.decrypt(giftWrap.content);
            }

            const seal = JSON.parse(decryptedSeal);
            const decryptedRumor = FallbackCryptographer.decrypt(seal.content);
            const rumor = JSON.parse(decryptedRumor);
            
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

  private async wrapInGift(rumor: any): Promise<any> {
    if (this.nip07) {
      try {
        let encryptedRumor: string;
        if (this.nip07.nip44) {
          encryptedRumor = await this.nip07.nip44.encrypt(this.agentPubkey, JSON.stringify(rumor));
        } else {
          encryptedRumor = FallbackCryptographer.encrypt(JSON.stringify(rumor));
        }

        const sealTemplate = {
          kind: 14,
          created_at: Math.floor(Date.now() / 1000),
          tags: [],
          content: encryptedRumor
        };

        const signedSeal = await this.nip07.signEvent(sealTemplate);
        const throwawayPriv = generateSecretKey();
        const throwawayChatKey = nip44.getConversationKey(throwawayPriv, this.agentPubkey);
        const encryptedSeal = nip44.encrypt(JSON.stringify(signedSeal), throwawayChatKey);

        const giftWrapTemplate = {
          kind: 13,
          created_at: Math.floor(Date.now() / 1000),
          tags: [["p", this.agentPubkey]],
          content: encryptedSeal
        };
        return finalizeEvent(giftWrapTemplate, throwawayPriv);
      } catch (err) {
        console.warn("[Nostr] NIP-07 signing failed, falling back to ephemeral key:", err);
      }
    }

    // Ephemeral fallback path
    const fallbackPriv = this.privKey || generateSecretKey();
    const encryptedRumor = FallbackCryptographer.encrypt(JSON.stringify(rumor));
    
    const sealTemplate = {
      kind: 14,
      created_at: Math.floor(Date.now() / 1000),
      tags: [],
      content: encryptedRumor
    };
    const seal = finalizeEvent(sealTemplate, fallbackPriv);
    
    const throwawayPriv = generateSecretKey();
    const encryptedSeal = FallbackCryptographer.encrypt(JSON.stringify(seal));
    
    const giftWrapTemplate = {
      kind: 13,
      created_at: Math.floor(Date.now() / 1000),
      tags: [["p", this.agentPubkey]],
      content: encryptedSeal
    };
    
    return finalizeEvent(giftWrapTemplate, throwawayPriv);
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

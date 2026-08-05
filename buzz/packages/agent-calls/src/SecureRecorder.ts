import { bytesToHex } from "@noble/hashes/utils";

export class SecureCallRecorder {
  private recorder?: MediaRecorder;
  private chunks: Blob[] = [];
  private symmetricKey?: CryptoKey;

  constructor(private signer: any, private uploadToStorage: (blob: Blob, filename: string) => Promise<string>) {}

  async startRecording(stream: MediaStream, participantConsents: Record<string, boolean>): Promise<boolean> {
    const allConsented = Object.values(participantConsents).every(c => c === true);
    if (!allConsented) return false;

    this.symmetricKey = await window.crypto.subtle.generateKey(
      { name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]
    );

    this.recorder = new MediaRecorder(stream);
    this.recorder.ondataavailable = (e) => { if (e.data.size > 0) this.chunks.push(e.data); };
    this.recorder.start(1000);
    return true;
  }

  async stopAndPublish(participantPubkeys: string[], callId: string): Promise<any> {
    this.recorder?.stop();
    await new Promise(r => this.recorder!.onstop = r);
    
    const blob = new Blob(this.chunks, { type: "audio/webm" });
    const arrayBuffer = await blob.arrayBuffer();

    const iv = window.crypto.getRandomValues(new Uint8Array(12));
    const encryptedData = await window.crypto.subtle.encrypt(
      { name: "AES-GCM", iv }, this.symmetricKey!, arrayBuffer
    );

    const encryptedBlob = new Blob([encryptedData], { type: "application/octet-stream" });
    const url = await this.uploadToStorage(encryptedBlob, `${callId}_recording.enc`);

    const rawKey = await window.crypto.subtle.exportKey("raw", this.symmetricKey!);
    const rawKeyHex = bytesToHex(new Uint8Array(rawKey));

    const keyWraps = await Promise.all(participantPubkeys.map(async (pk) => {
      const wrapped = await this.signer.nip44Encrypt(pk, rawKeyHex);
      return { pubkey: pk, wrapped_key: wrapped };
    }));

    return { url, iv: bytesToHex(iv), keyWraps };
  }
}

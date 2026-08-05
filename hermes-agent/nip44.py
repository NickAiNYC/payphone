"""NIP-44 v2 encryption.

Replaces two things that were not encryption:

  * the client's `FallbackCryptographer`, which prepended 12 random bytes and
    base64-encoded the result — no key, no cipher;
  * the agent's `MOCK_SHARED_KEY`, a symmetric key hardcoded in a public
    repository, whose decrypt path returned the ciphertext unchanged on failure
    and so silently accepted plaintext.

This follows the NIP-44 v2 spec so it interoperates with nostr-tools on the
client. Cross-implementation agreement is verified in tests/test_nip44.py —
a Python-encrypted payload must decrypt in JavaScript and vice versa, because
an encryption scheme that only agrees with itself is just obfuscation with
extra steps.

    conversation_key = hkdf_extract(salt="nip44-v2", ikm=ecdh_x(priv, pub))
    nonce            = 32 random bytes
    ck, cn, hk       = hkdf_expand(conversation_key, info=nonce, L=76)
    ciphertext       = chacha20(ck, cn, pad(plaintext))
    mac              = hmac_sha256(hk, nonce || ciphertext)
    payload          = base64(0x02 || nonce || ciphertext || mac)
"""

import base64
import hashlib
import hmac
import os
import secrets
from typing import Union

from coincurve import PrivateKey, PublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

VERSION = 2
MIN_PLAINTEXT = 1
MAX_PLAINTEXT = 65535


def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    out, t, counter = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        out += t
        counter += 1
    return out[:length]


def _chacha20(key: bytes, nonce12: bytes, data: bytes) -> bytes:
    # `cryptography` wants a 16-byte nonce: 4-byte little-endian counter, then
    # the 12-byte nonce. NIP-44 starts the counter at zero.
    cipher = Cipher(algorithms.ChaCha20(key, b"\x00" * 4 + nonce12), mode=None)
    enc = cipher.encryptor()
    return enc.update(data) + enc.finalize()


def _calc_padded_len(unpadded_len: int) -> int:
    """Pad to a power-of-two bucket so ciphertext length leaks less about the
    plaintext length."""
    if unpadded_len <= 32:
        return 32
    next_power = 1 << (unpadded_len - 1).bit_length()
    chunk = 32 if next_power <= 256 else next_power // 8
    return chunk * (((unpadded_len - 1) // chunk) + 1)


def _pad(plaintext: bytes) -> bytes:
    n = len(plaintext)
    if not (MIN_PLAINTEXT <= n <= MAX_PLAINTEXT):
        raise ValueError(f"plaintext must be 1..{MAX_PLAINTEXT} bytes, got {n}")
    return n.to_bytes(2, "big") + plaintext + b"\x00" * (_calc_padded_len(n) - n)


def _unpad(padded: bytes) -> bytes:
    if len(padded) < 2:
        raise ValueError("padded payload too short")
    n = int.from_bytes(padded[:2], "big")
    plaintext = padded[2 : 2 + n]
    # Both checks matter: a wrong length is how a padding oracle starts.
    if len(plaintext) != n or len(padded) != 2 + _calc_padded_len(n):
        raise ValueError("invalid padding")
    return plaintext


def _normalise_privkey(privkey: Union[str, bytes]) -> bytes:
    if isinstance(privkey, str):
        privkey = bytes.fromhex(privkey)
    if len(privkey) != 32:
        raise ValueError("private key must be 32 bytes")
    return privkey


def get_conversation_key(privkey: Union[str, bytes], pubkey_hex: str) -> bytes:
    """ECDH between our private key and their x-only pubkey.

    NIP-44 uses the raw x-coordinate of the shared point — not a hash of it,
    and not the compressed encoding.
    """
    priv = _normalise_privkey(privkey)
    if len(pubkey_hex) != 64:
        raise ValueError("x-only pubkey must be 32 bytes of hex")
    # x-only keys are implicitly even-y, hence the 02 prefix.
    point = PublicKey(bytes.fromhex("02" + pubkey_hex))
    shared_x = point.multiply(priv).format(compressed=False)[1:33]
    return _hkdf_extract(salt=b"nip44-v2", ikm=shared_x)


def encrypt(plaintext: str, conversation_key: bytes, nonce: bytes = None) -> str:
    if len(conversation_key) != 32:
        raise ValueError("conversation key must be 32 bytes")
    nonce = nonce or secrets.token_bytes(32)
    if len(nonce) != 32:
        raise ValueError("nonce must be 32 bytes")

    keys = _hkdf_expand(conversation_key, nonce, 76)
    chacha_key, chacha_nonce, hmac_key = keys[0:32], keys[32:44], keys[44:76]

    ciphertext = _chacha20(chacha_key, chacha_nonce, _pad(plaintext.encode("utf-8")))
    mac = hmac.new(hmac_key, nonce + ciphertext, hashlib.sha256).digest()
    return base64.b64encode(bytes([VERSION]) + nonce + ciphertext + mac).decode("ascii")


def decrypt(payload: str, conversation_key: bytes) -> str:
    if len(conversation_key) != 32:
        raise ValueError("conversation key must be 32 bytes")
    if payload.startswith("#"):
        raise ValueError("unsupported NIP-44 version")

    raw = base64.b64decode(payload, validate=True)
    if len(raw) < 99:
        raise ValueError("payload too short")
    if raw[0] != VERSION:
        raise ValueError(f"unsupported NIP-44 version {raw[0]}")

    nonce, ciphertext, mac = raw[1:33], raw[33:-32], raw[-32:]

    keys = _hkdf_expand(conversation_key, nonce, 76)
    chacha_key, chacha_nonce, hmac_key = keys[0:32], keys[32:44], keys[44:76]

    expected = hmac.new(hmac_key, nonce + ciphertext, hashlib.sha256).digest()
    # Constant-time, and checked before decrypting: never act on unauthenticated
    # ciphertext.
    if not hmac.compare_digest(mac, expected):
        raise ValueError("MAC mismatch — payload is forged or the key is wrong")

    return _unpad(_chacha20(chacha_key, chacha_nonce, ciphertext)).decode("utf-8")


def pubkey_from_privkey(privkey: Union[str, bytes]) -> str:
    """x-only public key hex, which is what Nostr addresses by."""
    return PrivateKey(_normalise_privkey(privkey)).public_key_xonly.format().hex()


def generate_privkey() -> str:
    return os.urandom(32).hex()

import base64

import pytest

pytest.importorskip("coincurve")

from nip44 import (  # noqa: E402
    decrypt,
    encrypt,
    generate_privkey,
    get_conversation_key,
    pubkey_from_privkey,
)

ALICE = "11" * 32
BOB = "22" * 32
ALICE_PUB = pubkey_from_privkey(ALICE)
BOB_PUB = pubkey_from_privkey(BOB)


def ck():
    return get_conversation_key(ALICE, BOB_PUB)


def test_ecdh_is_symmetric():
    """Either side derives the same conversation key, or nothing works."""
    assert get_conversation_key(ALICE, BOB_PUB) == get_conversation_key(BOB, ALICE_PUB)


def test_conversation_key_matches_nostr_tools():
    """Pinned against nostr-tools' getConversationKey for these keys.

    Cross-checked live against the JS implementation; if this value changes,
    the agent and the browser have silently stopped being able to talk.
    """
    assert ck().hex().startswith("2cbdf074f601178c")


def test_round_trip():
    for msg in ["hello", "a", "x" * 5000, "unicode → ✓ café 🔐", '{"type":"offer"}']:
        assert decrypt(encrypt(msg, ck()), ck()) == msg


def test_ciphertext_is_not_the_plaintext():
    """The bug this module replaced: base64 of the plaintext, called encryption."""
    plain = "the SDP nobody should be able to read"
    payload = encrypt(plain, ck())
    assert plain not in payload
    assert plain.encode() not in base64.b64decode(payload)


def test_nonce_makes_ciphertexts_unique():
    assert encrypt("same", ck()) != encrypt("same", ck())


def test_tampered_ciphertext_rejected():
    raw = bytearray(base64.b64decode(encrypt("secret", ck())))
    raw[50] ^= 1
    with pytest.raises(ValueError, match="MAC mismatch"):
        decrypt(base64.b64encode(bytes(raw)).decode(), ck())


def test_tampered_mac_rejected():
    raw = bytearray(base64.b64decode(encrypt("secret", ck())))
    raw[-1] ^= 1
    with pytest.raises(ValueError, match="MAC mismatch"):
        decrypt(base64.b64encode(bytes(raw)).decode(), ck())


def test_wrong_key_rejected():
    stranger = get_conversation_key(generate_privkey(), ALICE_PUB)
    with pytest.raises(ValueError, match="MAC mismatch"):
        decrypt(encrypt("secret", ck()), stranger)


def test_version_downgrade_rejected():
    with pytest.raises(ValueError, match="version"):
        decrypt(base64.b64encode(b"\x01" + b"\x00" * 130).decode(), ck())


def test_truncated_payload_rejected():
    with pytest.raises(ValueError):
        decrypt(base64.b64encode(b"\x02" + b"\x00" * 40).decode(), ck())


def test_empty_plaintext_refused():
    """NIP-44 has no representation for an empty message."""
    with pytest.raises(ValueError, match="1\\.\\."):
        encrypt("", ck())


@pytest.mark.parametrize("length", [1, 31, 32, 33, 255, 256, 257, 1000])
def test_padding_hides_exact_length(length):
    """Ciphertext length must land on a bucket, not track the plaintext."""
    payload = base64.b64decode(encrypt("x" * length, ck()))
    body = len(payload) - 1 - 32 - 32  # strip version, nonce, mac
    # body is a 2-byte big-endian length prefix followed by the padded
    # plaintext, and the padding lands on a 32-byte bucket.
    assert (body - 2) % 32 == 0
    assert body > length


def test_padding_buckets_collide():
    a = len(base64.b64decode(encrypt("x" * 33, ck())))
    b = len(base64.b64decode(encrypt("x" * 60, ck())))
    assert a == b, "different lengths must share a bucket"


def test_malformed_keys_refused():
    with pytest.raises(ValueError):
        get_conversation_key("aa" * 16, BOB_PUB)  # short private key
    with pytest.raises(ValueError):
        get_conversation_key(ALICE, "deadbeef")  # short pubkey
    with pytest.raises(ValueError):
        encrypt("x", b"\x00" * 16)  # short conversation key

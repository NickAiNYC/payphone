import time
import json
import logging
import hashlib
import asyncio
from dataclasses import dataclass
from typing import List, Set, Optional
from datetime import timedelta

logger = logging.getLogger(__name__)

# secp256k1 curve parameters for BIP-340 Schnorr signature verification
_SECP256K1_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_SECP256K1_G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and y1 != y2:
        return None
    if x1 == x2:
        lam = (3 * x1 * x1 * pow(2 * y1, _SECP256K1_P - 2, _SECP256K1_P)) % _SECP256K1_P
    else:
        lam = ((y2 - y1) * pow(x2 - x1, _SECP256K1_P - 2, _SECP256K1_P)) % _SECP256K1_P
    x3 = (lam * lam - x1 - x2) % _SECP256K1_P
    y3 = (lam * (x1 - x3) - y1) % _SECP256K1_P
    return (x3, y3)


def _point_mul(p, n):
    r = None
    q = p
    while n > 0:
        if n & 1:
            r = _point_add(r, q)
        q = _point_add(q, q)
        n >>= 1
    return r


def _lift_x(x):
    if x >= _SECP256K1_P:
        return None
    y_sq = (pow(x, 3, _SECP256K1_P) + 7) % _SECP256K1_P
    y = pow(y_sq, (_SECP256K1_P + 1) // 4, _SECP256K1_P)
    if pow(y, 2, _SECP256K1_P) != y_sq:
        return None
    return (x, y if y % 2 == 0 else _SECP256K1_P - y)


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    tag_hash = hashlib.sha256(tag.encode("utf-8")).digest()
    return hashlib.sha256(tag_hash + tag_hash + msg).digest()


def verify_nostr_event_crypto(event: dict, expected_pubkey: str) -> bool:
    """Strictly verifies a Nostr event:
    1. Enforces event.pubkey == expected_pubkey.
    2. Recomputes event.id digest over canonical JSON structure.
    3. Cryptographically verifies BIP-340 Schnorr signature over secp256k1.
    """
    try:
        pubkey_hex = event.get("pubkey", "")
        if not pubkey_hex or pubkey_hex.lower() != expected_pubkey.lower():
            logger.warning(
                f"[ConsentManager] Mismatched author pubkey: got {pubkey_hex}, expected {expected_pubkey}"
            )
            return False

        event_id = event.get("id", "")
        canonical = json.dumps(
            [
                0,
                event["pubkey"],
                event["created_at"],
                event["kind"],
                event["tags"],
                event["content"],
            ],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        computed_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if computed_id.lower() != event_id.lower():
            logger.warning(
                f"[ConsentManager] Forged event ID digest: computed {computed_id}, got {event_id}"
            )
            return False

        sig_hex = event.get("sig", "")
        if len(sig_hex) != 128 or len(pubkey_hex) != 64:
            logger.warning("[ConsentManager] Malformed signature or pubkey byte length")
            return False

        # Optional fast-path via coincurve / libsecp256k1 if available
        try:
            import coincurve

            if hasattr(coincurve, "verify_schnorr"):
                sig_bytes = bytes.fromhex(event.get("sig", ""))
                msg_bytes = bytes.fromhex(event_id)
                pub_bytes = bytes.fromhex(pubkey_hex)
                if coincurve.verify_schnorr(sig_bytes, msg_bytes, pub_bytes):
                    return True
                else:
                    logger.warning(
                        "[ConsentManager] coincurve Schnorr verification failed"
                    )
                    return False
        except Exception:
            pass

        r_bytes = bytes.fromhex(sig_hex[:64])
        s_bytes = bytes.fromhex(sig_hex[64:])
        p_bytes = bytes.fromhex(pubkey_hex)
        msg_bytes = bytes.fromhex(event_id)

        r = int.from_bytes(r_bytes, "big")
        s = int.from_bytes(s_bytes, "big")
        if r >= _SECP256K1_P or s >= _SECP256K1_N:
            return False

        P_point = _lift_x(int.from_bytes(p_bytes, "big"))
        if P_point is None:
            return False

        e_bytes = _tagged_hash("BIP0340/challenge", r_bytes + p_bytes + msg_bytes)
        e = int.from_bytes(e_bytes, "big") % _SECP256K1_N

        sG = _point_mul(_SECP256K1_G, s)
        eP = _point_mul(P_point, e)
        neg_eP = (eP[0], _SECP256K1_P - eP[1]) if eP else None
        R = _point_add(sG, neg_eP)

        if R is None or R[1] % 2 != 0 or R[0] != r:
            logger.warning(
                "[ConsentManager] Invalid BIP-340 Schnorr signature on consent event"
            )
            return False

        return True
    except Exception as exc:
        logger.error(f"[ConsentManager] Exception verifying event signature: {exc}")
        return False


@dataclass
class ConsentGrant:
    scopes: Set[str]
    record: bool
    server_processing_opt_in: bool
    expiration: int


class ConsentManager:
    def __init__(self, nostr_client=None, agent_keys=None):
        self.nostr = nostr_client
        self.agent_keys = agent_keys
        self._cache = {}

    async def check(
        self, human_pubkey: str, agent_pubkey: str, required_scopes: List[str]
    ) -> bool:
        grant = await self.fetch_grant(human_pubkey, agent_pubkey)
        if not grant:
            logger.warning(f"Consent denied for {human_pubkey}: No valid grant found.")
            return False
        if grant.expiration <= int(time.time()):
            logger.warning(f"Consent denied for {human_pubkey}: Grant expired.")
            return False
        if not all(s in grant.scopes for s in required_scopes):
            logger.warning(
                f"Consent denied for {human_pubkey}: Missing required scopes {required_scopes}."
            )
            return False
        return True

    async def fetch_grant(
        self, human_pubkey: str, agent_pubkey: str
    ) -> Optional[ConsentGrant]:
        """Fetch kind 21005 cryptographic consent grant from Nostr relay with strict signature validation."""
        if self.nostr:
            if human_pubkey in self._cache:
                cached = self._cache[human_pubkey]
                if cached.expiration > int(time.time()):
                    return cached

            try:
                filter_obj = {
                    "kinds": [21005],
                    "authors": [human_pubkey],
                    "#p": [agent_pubkey],
                    "limit": 5,
                }

                events = []
                if hasattr(self.nostr, "get_events"):
                    events = await self.nostr.get_events([filter_obj])
                elif hasattr(self.nostr, "get_events_from_relays"):
                    events = await asyncio.to_thread(
                        self.nostr.get_events_from_relays,
                        [filter_obj],
                        timedelta(seconds=5),
                    )

                valid_grant = None
                latest_ts = 0

                for raw_event in events:
                    # Convert event object to dictionary if necessary
                    if isinstance(raw_event, dict):
                        evt_dict = raw_event
                    else:
                        evt_dict = {
                            "id": getattr(
                                raw_event,
                                "id",
                                getattr(raw_event, "id_hex", lambda: "")(),
                            ),
                            "pubkey": getattr(
                                raw_event,
                                "pubkey",
                                getattr(raw_event, "pubkey_hex", lambda: "")(),
                            ),
                            "created_at": getattr(raw_event, "created_at", 0),
                            "kind": getattr(raw_event, "kind", 21005),
                            "tags": getattr(raw_event, "tags", []),
                            "content": getattr(raw_event, "content", ""),
                            "sig": getattr(raw_event, "sig", ""),
                        }

                    # Enforce strict BIP-340 cryptographic signature & author validation in worker thread
                    is_valid = await asyncio.to_thread(
                        verify_nostr_event_crypto, evt_dict, human_pubkey
                    )
                    if not is_valid:
                        logger.warning(
                            "[ConsentManager] Rejecting unverified/forged consent event from relay"
                        )
                        continue

                    try:
                        raw_content = evt_dict.get("content", "{}")
                        if (
                            self.agent_keys
                            and raw_content
                            and not raw_content.startswith("{")
                        ):
                            try:
                                from nostr_sdk import nip44

                                secret_key = (
                                    self.agent_keys.secret_key()
                                    if hasattr(self.agent_keys, "secret_key")
                                    else self.agent_keys
                                )
                                raw_content = nip44.decrypt(
                                    secret_key,
                                    human_pubkey,
                                    raw_content,
                                )
                            except Exception as decrypt_err:
                                logger.debug(
                                    f"[ConsentManager] NIP-44 decrypt skipped/failed: {decrypt_err}"
                                )

                        content = json.loads(raw_content)
                        exp = content.get("expiration", int(time.time()) + 86400)
                        ts = evt_dict.get("created_at", 0)

                        if ts > latest_ts:
                            latest_ts = ts
                            valid_grant = ConsentGrant(
                                scopes=set(content.get("scopes", ["mic"])),
                                record=content.get("record", False),
                                server_processing_opt_in=content.get(
                                    "server_processing_opt_in", False
                                ),
                                expiration=exp,
                            )
                    except Exception as parse_err:
                        logger.error(
                            f"[ConsentManager] Error parsing verified consent event content: {parse_err}"
                        )

                if valid_grant:
                    self._cache[human_pubkey] = valid_grant
                    return valid_grant

                # Fail closed if nostr client is active and no verified grant is found on relay
                return None
            except Exception as e:
                logger.error(
                    f"[ConsentManager] Failed to query consent from Nostr relays: {e}"
                )
                return None

        # Fallback local grant for direct offline calls and development (nostr_client=None)
        return ConsentGrant(
            scopes={"mic"},
            record=False,
            server_processing_opt_in=False,
            expiration=int(time.time()) + 86400,
        )

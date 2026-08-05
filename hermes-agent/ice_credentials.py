"""Short-lived TURN credentials (coturn REST / RFC 7635 style).

coturn runs with --static-auth-secret; it does not hold a user table. Instead a
trusted service mints `username = <expiry-unix-ts>:<name>` and
`password = base64(HMAC-SHA1(secret, username))`. coturn recomputes the HMAC and
accepts the pair until the embedded timestamp passes.

The secret never reaches the browser — only a credential that expires.
"""

import os
import hmac
import time
import base64
import hashlib
from typing import List, Dict, Any

# Keep this short. The credential only has to survive ICE gathering, not the call:
# an allocation already established stays valid after the credential expires.
DEFAULT_TTL_SECONDS = 600


def _turn_urls() -> List[str]:
    """TURN endpoints advertised to clients.

    TURN_URLS wins when set (comma-separated). Otherwise derive from TURN_HOST,
    offering UDP, TCP and TCP/443 — the last one is what gets a call out of a
    hotel or corporate network that blocks everything else.
    """
    explicit = os.environ.get("TURN_URLS", "").strip()
    if explicit:
        return [u.strip() for u in explicit.split(",") if u.strip()]

    host = os.environ.get("TURN_HOST", "").strip()
    if not host:
        return []
    port = os.environ.get("TURN_PORT", "3478").strip()
    return [
        f"turn:{host}:{port}?transport=udp",
        f"turn:{host}:{port}?transport=tcp",
        f"turns:{host}:5349?transport=tcp",
    ]


def _stun_urls() -> List[str]:
    explicit = os.environ.get("STUN_URLS", "").strip()
    if explicit:
        return [u.strip() for u in explicit.split(",") if u.strip()]
    host = os.environ.get("TURN_HOST", "").strip()
    urls = ["stun:stun.l.google.com:19302"]
    if host:
        urls.insert(0, f"stun:{host}:{os.environ.get('TURN_PORT', '3478')}")
    return urls


def mint_turn_credential(
    name: str = "payphone", ttl: int = DEFAULT_TTL_SECONDS
) -> Dict[str, Any]:
    """Return {username, credential, ttl, urls}, or {} when TURN is not configured."""
    secret = os.environ.get("COTURN_SECRET", "").strip()
    urls = _turn_urls()
    if not secret or not urls:
        return {}

    expiry = int(time.time()) + int(ttl)
    username = f"{expiry}:{name}"
    digest = hmac.new(
        secret.encode("utf-8"), username.encode("utf-8"), hashlib.sha1
    ).digest()
    return {
        "username": username,
        "credential": base64.b64encode(digest).decode("ascii"),
        "ttl": int(ttl),
        "urls": urls,
    }


def ice_servers(
    name: str = "payphone", ttl: int = DEFAULT_TTL_SECONDS
) -> List[Dict[str, Any]]:
    """RTCIceServer[] ready to hand to a browser's RTCPeerConnection."""
    servers: List[Dict[str, Any]] = [{"urls": _stun_urls()}]
    turn = mint_turn_credential(name, ttl)
    if turn:
        servers.append(
            {
                "urls": turn["urls"],
                "username": turn["username"],
                "credential": turn["credential"],
            }
        )
    return servers

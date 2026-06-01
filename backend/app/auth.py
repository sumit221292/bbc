"""Single-password authentication for the dashboard.

Design choices:
  - One password (`ADMIN_PASSWORD` env var). Single owner, single account,
    no user management needed. Keeps surface area tiny.
  - HMAC-signed token in an HttpOnly + SameSite=Lax + Secure cookie.
    Browser stores it; XSS can't read it; CSRF mitigated by SameSite=Lax.
  - Stateless: no session table. Token carries an `exp` (30 days) and a
    signature; server verifies on every request. Logout just clears the
    cookie -- the token would still verify until expiry, but the user
    no longer has it.
  - Signing key is derived from ADMIN_PASSWORD itself (sha256). Means:
      * One env var to manage (no separate AUTH_SECRET).
      * Changing the password invalidates all outstanding tokens, which
        is the right security behaviour anyway.
  - Auth disabled when ADMIN_PASSWORD is empty -- preserves local dev
    convenience. Production sets the var; local doesn't bother.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Cookie, HTTPException, status


ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
TOKEN_TTL_SECONDS = 30 * 86400   # 30 days -- "remember me by default"
COOKIE_NAME = "btc_session"
# Secure cookies on the production host. Local dev with auth enabled
# would break here; we don't enable auth locally though.
_COOKIE_SECURE = os.environ.get("COOKIE_INSECURE", "") not in ("1", "true", "yes")


def is_auth_disabled() -> bool:
    """True iff no ADMIN_PASSWORD is configured. The whole app skips
    auth checks in this mode -- intended for local dev only."""
    return not ADMIN_PASSWORD


def _secret() -> bytes:
    """HMAC signing key. Derived from the password so rotating the
    password automatically invalidates all outstanding tokens."""
    return hashlib.sha256(ADMIN_PASSWORD.encode("utf-8")).digest()


def _sign(payload: bytes) -> bytes:
    return hmac.new(_secret(), payload, hashlib.sha256).digest()


def make_token(now_ts: int | None = None) -> str:
    """Build a signed token. Returns a string safe for cookie storage:
    `<base64-payload>.<base64-signature>`.
    """
    ts = int(now_ts if now_ts is not None else time.time())
    payload = json.dumps({"exp": ts + TOKEN_TTL_SECONDS}, separators=(",", ":")).encode()
    sig = _sign(payload)
    return (
        base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
        + "."
        + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    )


def _b64decode(s: str) -> bytes:
    # Add padding back -- we stripped `=` chars before encoding.
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        b64_payload, b64_sig = token.split(".", 1)
        payload = _b64decode(b64_payload)
        sig = _b64decode(b64_sig)
        if not hmac.compare_digest(sig, _sign(payload)):
            return False
        data = json.loads(payload)
        return int(data.get("exp", 0)) > int(time.time())
    except Exception:
        return False


def require_auth(btc_session: str | None = Cookie(default=None)) -> None:
    """FastAPI dependency. Use as:

        @router.post(...)
        async def handler(..., _auth: None = Depends(require_auth)):
            ...

    Returns None on success (we don't have a user concept, just gated
    or not). Raises 401 otherwise. When auth is globally disabled
    (no ADMIN_PASSWORD env), always succeeds -- local dev pass-through.
    """
    if is_auth_disabled():
        return
    if not verify_token(btc_session):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

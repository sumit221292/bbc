"""/api/auth/* -- single-password login flow.

Only three endpoints:
  POST /login   { password } -> sets HttpOnly cookie if password matches.
  POST /logout                -> clears the cookie.
  GET  /status                -> { authenticated, auth_disabled }.
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel

from ..auth import (
    ADMIN_PASSWORD, COOKIE_NAME, TOKEN_TTL_SECONDS, _COOKIE_SECURE,
    is_auth_disabled, make_token, verify_token,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(payload: LoginRequest, response: Response):
    if is_auth_disabled():
        # No ADMIN_PASSWORD set -- accept anything so local dev never
        # has to deal with the login screen.
        return {"ok": True, "auth_disabled": True}

    # Constant-time compare so the wrong password takes the same time
    # as the right one (no timing oracle on the password).
    if not hmac.compare_digest(
        (payload.password or "").encode("utf-8"),
        ADMIN_PASSWORD.encode("utf-8"),
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid password")

    token = make_token()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=TOKEN_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_COOKIE_SECURE,
        path="/",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/status")
async def status_endpoint(btc_session: str | None = Cookie(default=None)):
    if is_auth_disabled():
        return {"authenticated": True, "auth_disabled": True}
    return {
        "authenticated": verify_token(btc_session),
        "auth_disabled": False,
    }

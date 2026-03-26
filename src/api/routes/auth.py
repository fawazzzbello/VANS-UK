# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""
Authentication routes for the VANS UK admin interface.

Session-based auth using signed JWT cookies (python-jose).
Credentials are set via ADMIN_USERNAME and ADMIN_PASSWORD environment variables.
Set SECRET_KEY to a strong random value in production.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────

SECRET_KEY      = os.environ.get("SECRET_KEY", "vans-uk-insecure-dev-key-change-in-production")
ALGORITHM       = "HS256"
SESSION_HOURS   = 8
COOKIE_NAME     = "vans_session"

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Credentials — set these in Railway environment variables
_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "vans-admin-2026")


# ── Token helpers ─────────────────────────────────────────────────────────────

def create_session_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    return jwt.encode(
        {"sub": username, "exp": expire, "iat": datetime.now(timezone.utc)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def verify_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return True
    except JWTError:
        return False


def get_session_username(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


# ── Routes ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
async def login(body: LoginRequest, response: Response):
    """
    Validate admin credentials and set a session cookie.

    Credentials are configured via ADMIN_USERNAME and ADMIN_PASSWORD
    environment variables.
    """
    username_ok = body.username == _ADMIN_USERNAME
    password_ok = body.password == _ADMIN_PASSWORD

    if not (username_ok and password_ok):
        logger.warning("Failed login attempt for username '%s'", body.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_session_token(body.username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=False,  # set True behind HTTPS in production
    )
    logger.info("Admin login: %s", body.username)
    return {"status": "ok", "redirect": "/"}


@router.post("/auth/logout")
async def logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(COOKIE_NAME)
    return {"status": "logged_out"}


@router.get("/auth/status")
async def auth_status(request: Request):
    """Return whether the current request has a valid session."""
    token    = request.cookies.get(COOKIE_NAME)
    valid    = verify_session_token(token)
    username = get_session_username(token) if valid else None
    return {"authenticated": valid, "username": username}

"""JWT helpers and FastAPI auth dependencies.

Tokens are signed with HS256 using config.JWT_SECRET. The UserStore instance is
injected by app.py via set_user_store() so the dependencies can load the user.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import config

# Re-export password helpers so callers can import everything auth-related from here
from user_store import hash_password, verify_password  # noqa: F401

# HTTPBearer extracts "Authorization: Bearer <token>"; auto_error=False lets us
# return a clean 401 instead of FastAPI's default.
_bearer = HTTPBearer(auto_error=False)

# Set by app.py at startup
_user_store = None


def set_user_store(store):
    """Inject the shared UserStore instance (called once from app startup)."""
    global _user_store
    _user_store = store


def create_access_token(username: str, role: str) -> str:
    """Create a signed JWT carrying the username (sub), role, and expiry."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=config.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode/verify a JWT, raising jwt exceptions on failure/expiry."""
    return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Dict[str, Any]:
    """FastAPI dependency: resolve the authenticated user or raise 401."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise unauthorized

    username = payload.get("sub")
    if not username or _user_store is None:
        raise unauthorized

    user = _user_store.get_by_username(username)
    if not user:
        raise unauthorized

    return {"id": user["id"], "username": user["username"], "role": user["role"]}


def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """FastAPI dependency: require the authenticated user to be an admin (else 403)."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user

"""Authentication middleware and dependencies for FastAPI."""
from __future__ import annotations

from typing import Any

from fastapi import Cookie, HTTPException, Request

from app.auth_db import get_session_user

SESSION_COOKIE = "wrmeta_session"


def get_current_user(request: Request, wrmeta_session: str | None = Cookie(None)) -> dict[str, Any] | None:
    """Extract the current user from session cookie. Returns None if not logged in."""
    token = wrmeta_session
    if not token:
        return None
    return get_session_user(token)


def require_auth(request: Request, wrmeta_session: str | None = Cookie(None)) -> dict[str, Any]:
    """Require a logged-in user. Raises 401 if not authenticated."""
    user = get_current_user(request, wrmeta_session)
    if not user:
        raise HTTPException(status_code=401, detail="Login necessario")
    return user


def require_plan(*allowed_plans: str):
    """Factory that returns a dependency requiring the user to have one of the allowed plans."""
    def dependency(request: Request, wrmeta_session: str | None = Cookie(None)) -> dict[str, Any]:
        user = require_auth(request, wrmeta_session)
        if user["plan"] not in allowed_plans:
            raise HTTPException(
                status_code=403,
                detail=f"Plano '{user['plan']}' nao tem acesso. Necessario: {', '.join(allowed_plans)}",
            )
        return user
    return dependency

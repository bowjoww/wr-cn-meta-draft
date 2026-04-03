"""Authentication API routes."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr

from app.auth_db import (
    cleanup_expired_sessions,
    consume_invite,
    consume_password_reset_token,
    create_password_reset_token,
    create_session,
    create_team,
    create_team_invite,
    create_user,
    delete_session,
    get_session_user,
    get_team,
    get_team_members,
    get_user_by_email,
    update_user_plan,
    update_user_team,
    verify_password,
)
from app.auth_middleware import SESSION_COOKIE, require_auth, require_plan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class RegisterInput(BaseModel):
    email: str
    password: str
    display_name: str


class LoginInput(BaseModel):
    email: str
    password: str


class CreateTeamInput(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register")
def register(body: RegisterInput, response: Response) -> dict[str, Any]:
    """Register a new user account."""
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Senha deve ter pelo menos 6 caracteres")

    existing = get_user_by_email(body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email ja cadastrado")

    try:
        user = create_user(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    except Exception as exc:
        logger.error("Failed to create user: %s", exc)
        raise HTTPException(status_code=500, detail="Erro ao criar conta") from exc

    # Auto-login after registration
    token = create_session(user["id"])
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )
    return {"message": "Conta criada com sucesso", "user": user}


@router.post("/login")
def login(body: LoginInput, response: Response) -> dict[str, Any]:
    """Log in with email and password."""
    user = get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")

    token = create_session(user["id"])
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )

    # Remove password_hash from response
    user.pop("password_hash", None)
    return {"message": "Login realizado", "user": user}


@router.post("/logout")
def logout(response: Response, wrmeta_session: str | None = None) -> dict[str, str]:
    """Log out and invalidate the session."""
    if wrmeta_session:
        delete_session(wrmeta_session)
    response.delete_cookie(SESSION_COOKIE)
    return {"message": "Logout realizado"}


@router.get("/me")
def me(user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Get the current logged-in user's profile."""
    return {"user": user}


@router.post("/team")
def create_team_endpoint(
    body: CreateTeamInput,
    user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Create a team (current user becomes owner with 'coach' plan)."""
    if user.get("team_id"):
        raise HTTPException(status_code=400, detail="Voce ja pertence a um time")

    try:
        team = create_team(name=body.name, owner_id=user["id"])
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(status_code=409, detail="Nome de time ja existe") from exc
        raise HTTPException(status_code=500, detail="Erro ao criar time") from exc

    # Upgrade user to owner plan
    update_user_plan(user["id"], "owner")
    update_user_team(user["id"], team["id"])

    return {"message": f"Time '{team['name']}' criado", "team": team}


@router.get("/team")
def get_team_info(user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Get the current user's team info and members."""
    if not user.get("team_id"):
        raise HTTPException(status_code=404, detail="Voce nao pertence a nenhum time")

    team = get_team(user["team_id"])
    if not team:
        raise HTTPException(status_code=404, detail="Time nao encontrado")

    members = get_team_members(user["team_id"])
    return {"team": team, "members": members}


# ---------------------------------------------------------------------------
# Team invite flow
# ---------------------------------------------------------------------------

@router.post("/team/invite")
def create_invite(user: dict = Depends(require_plan("coach", "owner"))) -> dict[str, Any]:
    """Generate a single-use team invite link (coach/owner only)."""
    if not user.get("team_id"):
        raise HTTPException(status_code=400, detail="Voce nao pertence a nenhum time")
    token = create_team_invite(team_id=user["team_id"], created_by=user["id"])
    return {"invite_token": token, "expires_in_hours": 72}


class JoinTeamInput(BaseModel):
    token: str


@router.post("/team/join")
def join_team(body: JoinTeamInput, user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Join a team using an invite token."""
    if user.get("team_id"):
        raise HTTPException(status_code=400, detail="Voce ja pertence a um time")
    team = consume_invite(token=body.token, user_id=user["id"])
    if not team:
        raise HTTPException(status_code=400, detail="Convite invalido ou expirado")
    return {"message": f"Entrou no time '{team['name']}'", "team": team}


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

class PasswordResetRequestInput(BaseModel):
    email: str


class PasswordResetConfirmInput(BaseModel):
    token: str
    new_password: str


@router.post("/password-reset/request")
def request_password_reset(body: PasswordResetRequestInput) -> dict[str, str]:
    """Request a password reset token. Always returns 200 to avoid email enumeration."""
    user = get_user_by_email(body.email)
    if user:
        token = create_password_reset_token(user["id"])
        # In production this token would be emailed; for now it is returned in the response.
        logger.info("Password reset token for %s: %s", body.email, token)
        return {"message": "Se o email existir, um token de reset foi gerado", "token": token}
    return {"message": "Se o email existir, um token de reset foi gerado"}


@router.post("/password-reset/confirm")
def confirm_password_reset(body: PasswordResetConfirmInput) -> dict[str, str]:
    """Consume a reset token and set a new password."""
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Senha deve ter pelo menos 6 caracteres")
    ok = consume_password_reset_token(token=body.token, new_password=body.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail="Token invalido ou expirado")
    return {"message": "Senha atualizada com sucesso"}


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

@router.post("/sessions/cleanup")
def sessions_cleanup(user: dict = Depends(require_plan("owner"))) -> dict[str, int]:
    """Clean up expired sessions (owner only)."""
    count = cleanup_expired_sessions()
    return {"deleted": count}

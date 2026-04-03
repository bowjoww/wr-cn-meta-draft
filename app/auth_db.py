"""Authentication database: users, teams, sessions, invites, password resets."""
from __future__ import annotations

import atexit
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt as _bcrypt

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "auth.db"
SESSION_TTL_DAYS = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    plan            TEXT NOT NULL DEFAULT 'free'
                    CHECK(plan IN ('free','player','coach','owner')),
    team_id         INTEGER REFERENCES teams(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS team_invites (
    token       TEXT PRIMARY KEY,
    team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_by  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_auth_db() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _checkpoint() -> None:
    try:
        with _connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass


atexit.register(_checkpoint)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return _bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def create_user(email: str, password: str, display_name: str, plan: str = "free") -> dict[str, Any]:
    """Create a new user. Returns user dict (without password_hash)."""
    pw_hash = hash_password(password)
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, display_name, plan) VALUES (?, ?, ?, ?)",
            (email.lower().strip(), pw_hash, display_name.strip(), plan),
        )
        conn.commit()
        user_id = cursor.lastrowid
    return get_user_by_id(user_id)  # type: ignore[return-value]


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, display_name, plan, team_id, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Returns user dict WITH password_hash (for auth verification)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, display_name, plan, team_id, created_at FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()
    return dict(row) if row else None


def update_user_plan(user_id: int, plan: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))
        conn.commit()


def update_user_team(user_id: int, team_id: int | None) -> None:
    with _connect() as conn:
        conn.execute("UPDATE users SET team_id = ? WHERE id = ?", (team_id, user_id))
        conn.commit()


# ---------------------------------------------------------------------------
# Team CRUD
# ---------------------------------------------------------------------------

def create_team(name: str, owner_id: int) -> dict[str, Any]:
    """Create a team and assign the owner to it."""
    with _connect() as conn:
        cursor = conn.execute("INSERT INTO teams (name) VALUES (?)", (name.strip(),))
        team_id = cursor.lastrowid
        conn.execute("UPDATE users SET team_id = ? WHERE id = ?", (team_id, owner_id))
        conn.commit()
    return {"id": team_id, "name": name.strip()}


def get_team(team_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT id, name, created_at FROM teams WHERE id = ?", (team_id,)).fetchone()
    return dict(row) if row else None


def get_team_members(team_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, email, display_name, plan, created_at FROM users WHERE team_id = ?",
            (team_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def create_session(user_id: int) -> str:
    """Create a new session token. Returns the token string."""
    token = uuid.uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires.isoformat()),
        )
        conn.commit()
    return token


def get_session_user(token: str) -> dict[str, Any] | None:
    """Validate a session token and return the user, or None if invalid/expired."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT u.id, u.email, u.display_name, u.plan, u.team_id, u.created_at
               FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.id = ? AND s.expires_at > datetime('now')""",
            (token,),
        ).fetchone()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (token,))
        conn.commit()


def cleanup_expired_sessions() -> int:
    """Remove expired sessions. Returns count deleted."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE expires_at <= datetime('now')")
        conn.commit()
        return cursor.rowcount


# ---------------------------------------------------------------------------
# Team invite tokens
# ---------------------------------------------------------------------------

INVITE_TTL_HOURS = 72


def create_team_invite(team_id: int, created_by: int) -> str:
    """Create a team invite token valid for 72 hours. Returns the token."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO team_invites (token, team_id, created_by, expires_at) VALUES (?, ?, ?, ?)",
            (token, team_id, created_by, expires.isoformat()),
        )
        conn.commit()
    return token


def get_valid_invite(token: str) -> dict[str, Any] | None:
    """Return invite row if token exists, is unused, and not expired."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT i.token, i.team_id, t.name as team_name
               FROM team_invites i
               JOIN teams t ON i.team_id = t.id
               WHERE i.token = ? AND i.used_at IS NULL AND i.expires_at > datetime('now')""",
            (token,),
        ).fetchone()
    return dict(row) if row else None


def consume_invite(token: str, user_id: int) -> dict[str, Any] | None:
    """Mark invite as used and assign user to team. Returns team dict or None if invalid."""
    invite = get_valid_invite(token)
    if not invite:
        return None
    with _connect() as conn:
        conn.execute(
            "UPDATE team_invites SET used_at = datetime('now') WHERE token = ?",
            (token,),
        )
        conn.execute(
            "UPDATE users SET team_id = ?, plan = 'player' WHERE id = ? AND team_id IS NULL",
            (invite["team_id"], user_id),
        )
        conn.commit()
    return {"id": invite["team_id"], "name": invite["team_name"]}


# ---------------------------------------------------------------------------
# Password reset tokens
# ---------------------------------------------------------------------------

RESET_TTL_HOURS = 1


def create_password_reset_token(user_id: int) -> str:
    """Create a single-use password reset token. Returns the token."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=RESET_TTL_HOURS)
    with _connect() as conn:
        # Invalidate any existing unused tokens for this user
        conn.execute(
            "UPDATE password_reset_tokens SET used_at = datetime('now') WHERE user_id = ? AND used_at IS NULL",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO password_reset_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires.isoformat()),
        )
        conn.commit()
    return token


def consume_password_reset_token(token: str, new_password: str) -> bool:
    """Validate token, update password, mark token used. Returns True on success."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM password_reset_tokens WHERE token = ? AND used_at IS NULL AND expires_at > datetime('now')",
            (token,),
        ).fetchone()
        if not row:
            return False
        new_hash = hash_password(new_password)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, row["user_id"]))
        conn.execute(
            "UPDATE password_reset_tokens SET used_at = datetime('now') WHERE token = ?",
            (token,),
        )
        conn.commit()
    return True

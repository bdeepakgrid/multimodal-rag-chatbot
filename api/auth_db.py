import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from api.auth import Role, UserContext

DB_PATH = Path("./data/users.db")


def get_db_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    ).hex()
    return pw_hash, salt


def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    calculated_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(calculated_hash, pw_hash)


def init_auth_db() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            created_at TEXT NOT NULL
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """
    )
    conn.commit()

    # Seed initial users if table is empty
    cursor.execute("SELECT COUNT(*) as cnt FROM users")
    row = cursor.fetchone()
    if row and row["cnt"] == 0:
        seed_users = [
            ("technician", "technician@example.com", "tech123", Role.TECHNICIAN),
            ("reviewer", "reviewer@example.com", "reviewer123", Role.REVIEWER),
            ("admin", "admin@example.com", "admin123", Role.ADMIN),
        ]
        legacy_tokens = {
            Role.TECHNICIAN: ["tech-key-123", "technician-key-123"],
            Role.REVIEWER: ["reviewer-key-456"],
            Role.ADMIN: ["admin-key-789"],
        }
        for username, email, password, role in seed_users:
            user_id = str(uuid4())
            pw_hash, salt = hash_password(password)
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT INTO users (id, username, email, password_hash, salt, role, tenant_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'default', ?)
            """,
                (user_id, username, email, pw_hash, salt, role.value, now),
            )

            for legacy_token in legacy_tokens.get(role, []):
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO tokens (token, user_id, username, role, tenant_id, created_at)
                    VALUES (?, ?, ?, ?, 'default', ?)
                """,
                    (legacy_token, user_id, username, role.value, now),
                )
        conn.commit()
    conn.close()


def create_user(username: str, email: str, password: str, role: Role, tenant_id: str = "default") -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", (username, email))
    if cursor.fetchone():
        conn.close()
        raise ValueError("Username or email already exists")

    user_id = str(uuid4())
    pw_hash, salt = hash_password(password)
    now = datetime.now(timezone.utc).isoformat()

    cursor.execute(
        """
        INSERT INTO users (id, username, email, password_hash, salt, role, tenant_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (user_id, username, email, pw_hash, salt, role.value, tenant_id, now),
    )
    conn.commit()
    conn.close()

    return {
        "id": user_id,
        "username": username,
        "email": email,
        "role": role.value,
        "tenant_id": tenant_id,
    }


def authenticate_user(username_or_email: str, password: str) -> Optional[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE username = ? OR email = ?",
        (username_or_email, username_or_email),
    )
    user = cursor.fetchone()
    if not user:
        conn.close()
        return None

    if not verify_password(password, user["password_hash"], user["salt"]):
        conn.close()
        return None

    user_data = {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
    }
    conn.close()
    return user_data


def create_session_token(user: dict) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    token = f"token_{secrets.token_hex(24)}"
    now = datetime.now(timezone.utc).isoformat()

    cursor.execute(
        """
        INSERT INTO tokens (token, user_id, username, role, tenant_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (token, user["id"], user["username"], user["role"], user["tenant_id"], now),
    )
    conn.commit()
    conn.close()
    return token


def resolve_token(token: str) -> Optional[UserContext]:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tokens WHERE token = ?", (token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return UserContext(
        tenant_id=row["tenant_id"],
        role=Role(row["role"]),
        identity=row["username"],
    )


def list_users() -> list[dict]:
    """Returns a list of all users, sorted by creation date."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, username, email, role, tenant_id, created_at FROM users ORDER BY created_at DESC"
    )
    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "role": row["role"],
            "tenant_id": row["tenant_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def update_user_role(user_id: str, new_role: Role) -> bool:
    """Updates a user's role and invalidates their existing sessions."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Update the user's role
    cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role.value, user_id))
    if cursor.rowcount == 0:
        conn.close()
        return False

    # Invalidate existing sessions so the role change takes effect immediately on next login
    cursor.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))
    
    conn.commit()
    conn.close()
    return True

"""SQLite-backed user store with bcrypt password hashing.

Follows the repository's "plain class wrapper" style (cf. SessionManager,
VectorStore). No ORM — just stdlib sqlite3.
"""
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import bcrypt

VALID_ROLES = ("user", "admin")


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (returns a utf-8 string for storage)."""
    # bcrypt has a 72-byte input limit; encode and let it truncate consistently.
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


class UserStore:
    """User accounts persisted in a SQLite database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL
                )
                """
            )

    # ---- queries -------------------------------------------------------- #
    def get_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            return dict(row) if row else None

    def list_users(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, username, role, created_at FROM users ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def count_admins(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin'"
            ).fetchone()[0]

    # ---- mutations ------------------------------------------------------ #
    def create_user(self, username: str, password: str, role: str = "user") -> Dict[str, Any]:
        username = (username or "").strip()
        if not username:
            raise ValueError("username is required")
        if not password:
            raise ValueError("password is required")
        if role not in VALID_ROLES:
            raise ValueError(f"role must be one of {VALID_ROLES}")

        created_at = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                    (username, hash_password(password), role, created_at),
                )
                user_id = cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"username '{username}' already exists")

        return {"id": user_id, "username": username, "role": role, "created_at": created_at}

    def delete_user(self, user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            return cur.rowcount > 0

    def verify_login(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Return the user dict if credentials are valid, else None."""
        user = self.get_by_username(username)
        if not user:
            return None
        if not verify_password(password, user["password_hash"]):
            return None
        return user

    def seed_admin(self, username: str, password: str) -> bool:
        """Create the initial admin if no admin exists. Returns True if seeded."""
        if self.count_admins() > 0:
            return False
        if not username or not password:
            return False
        # If the username is taken (as a non-admin), promote rather than fail.
        existing = self.get_by_username(username)
        if existing:
            with self._connect() as conn:
                conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (existing["id"],))
            return True
        self.create_user(username, password, role="admin")
        return True

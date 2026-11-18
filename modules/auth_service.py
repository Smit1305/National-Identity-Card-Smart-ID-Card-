"""
Authentication, Authorization, Password Hashing, Rate Limiting & User Management
Uses bcrypt for password hashing and HMAC-SHA256 signed bearer tokens for REST APIs.
Never stores or exposes plain-text passwords or hashes in API responses.
"""

import os
import hmac
import time
import base64
import hashlib
import secrets
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

import bcrypt

from modules.database import get_connection, utc_now_str, log_audit, get_setting

# Application secret key (override via SMART_NIC_SECRET_KEY in production)
_SECRET_KEY = os.environ.get("SMART_NIC_SECRET_KEY", "smart-nic-academic-prototype-hmac-key-2026").encode("utf-8")

# Simple sliding-window in-memory rate limiter
_RATE_BUCKETS: Dict[str, deque] = defaultdict(deque)


def check_rate_limit(bucket_key: str, max_requests: int = 30, window_seconds: int = 60) -> Tuple[bool, int]:
    """
    Sliding-window rate limiter.
    Returns (allowed: bool, remaining_requests: int).
    """
    now = time.time()
    q = _RATE_BUCKETS[bucket_key]
    while q and (now - q[0]) > window_seconds:
        q.popleft()
    if len(q) >= max_requests:
        return False, 0
    q.append(now)
    return True, max_requests - len(q)


def hash_password(plain_password: str) -> str:
    """Hash a password with bcrypt and random salt."""
    if not plain_password or len(plain_password) < 6:
        raise ValueError("Password must be at least 6 characters long.")
    salt = bcrypt.gensalt(rounds=10)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify plaintext password against stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def create_signed_token(user_id: int, username: str, role: str, citizen_id: Optional[int], ttl_minutes: int = 480) -> str:
    """Create a compact HMAC-SHA256 signed session/API token."""
    exp = int(time.time()) + ttl_minutes * 60
    cid = str(citizen_id) if citizen_id is not None else "none"
    payload = f"{user_id}|{username}|{role}|{cid}|{exp}"
    sig = hmac.new(_SECRET_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}|{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def verify_signed_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify HMAC-SHA256 bearer token and return safe user payload if valid and unexpired."""
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        parts = raw.split("|")
        if len(parts) != 6:
            return None
        user_id_s, username, role, cid_s, exp_s, sig = parts
        payload = f"{user_id_s}|{username}|{role}|{cid_s}|{exp_s}"
        expected_sig = hmac.new(_SECRET_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        if int(exp_s) < int(time.time()):
            return None
        return {
            "id": int(user_id_s),
            "username": username,
            "role": role,
            "citizen_id": int(cid_s) if cid_s != "none" else None,
        }
    except Exception:
        return None


def _sanitize_user_row(row) -> Dict[str, Any]:
    """Return user dictionary WITHOUT password_hash."""
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
        "citizen_id": row["citizen_id"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "last_login": row["last_login"],
    }


def authenticate_user(username_or_email: str, password: str, expected_role: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Authenticate admin or citizen user with lockout protection and audit logging.
    Returns (success, message, safe_user_dict).
    """
    ident = (username_or_email or "").strip()
    if not ident or not password:
        return False, "Username/email and password are required.", None

    max_attempts = int(get_setting("max_login_attempts", "5") or 5)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
            (ident, ident),
        ).fetchone()

        if not row:
            log_audit("LOGIN_FAILED", "auth", ident, "Unknown username/email")
            return False, "Invalid username or password.", None

        if not row["is_active"]:
            log_audit("LOGIN_BLOCKED", "auth", str(row["id"]), "Account deactivated", row["id"], row["username"], row["role"])
            return False, "This account has been deactivated by an administrator.", None

        if expected_role and row["role"] != expected_role:
            log_audit("LOGIN_ROLE_MISMATCH", "auth", str(row["id"]), f"Attempted {expected_role} portal with {row['role']} role", row["id"], row["username"], row["role"])
            return False, f"This account does not have {expected_role} access privileges.", None

        # Check lockout
        if row["locked_until"]:
            try:
                lock_dt = datetime.strptime(row["locked_until"], "%Y-%m-%d %H:%M:%S")
                if datetime.now() < lock_dt:
                    mins = max(1, int((lock_dt - datetime.now()).total_seconds() // 60) + 1)
                    return False, f"Account temporarily locked due to failed attempts. Try again in {mins} min.", None
            except ValueError:
                pass

        if not verify_password(password, row["password_hash"]):
            new_fails = int(row["failed_attempts"] or 0) + 1
            locked_until = None
            if new_fails >= max_attempts:
                locked_until = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                (new_fails, locked_until, row["id"]),
            )
            conn.commit()
            log_audit("LOGIN_FAILED", "auth", str(row["id"]), f"Bad password (attempt {new_fails})", row["id"], row["username"], row["role"])
            return False, "Invalid username or password.", None

        # Success -> reset failed attempts & update last_login
        now = utc_now_str()
        conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login = ? WHERE id = ?",
            (now, row["id"]),
        )
        conn.commit()

        user_safe = _sanitize_user_row(row)
        user_safe["last_login"] = now
        user_safe["token"] = create_signed_token(row["id"], row["username"], row["role"], row["citizen_id"])
        log_audit("LOGIN_SUCCESS", "auth", str(row["id"]), f"Signed in as {row['role']}", row["id"], row["username"], row["role"])
        return True, "Authentication successful.", user_safe


def create_user(
    username: str,
    email: str,
    full_name: str,
    password: str,
    role: str = "citizen",
    citizen_id: Optional[int] = None,
    actor: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Optional[int]]:
    """Create a new admin or citizen user account with bcrypt-hashed password."""
    username = username.strip().lower()
    email = email.strip().lower()
    full_name = full_name.strip()

    if len(username) < 3:
        return False, "Username must be at least 3 characters.", None
    if "@" not in email or "." not in email:
        return False, "Please provide a valid email address.", None
    if role not in ("admin", "citizen"):
        return False, "Role must be 'admin' or 'citizen'.", None

    try:
        pw_hash = hash_password(password)
    except ValueError as e:
        return False, str(e), None

    now = utc_now_str()
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (username, email, full_name, password_hash, role, citizen_id, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (username, email, full_name, pw_hash, role, citizen_id, now),
            )
            uid = cur.lastrowid
            conn.commit()
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            return False, "A user with that username or email already exists.", None
        return False, f"Failed to create user: {e}", None

    log_audit(
        "USER_CREATED",
        "user",
        str(uid),
        f"Created {role} account '{username}'",
        actor.get("id") if actor else None,
        actor.get("username", "system") if actor else "system",
        actor.get("role", "system") if actor else "system",
    )
    return True, f"User '{username}' created successfully.", uid


def list_users(role_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all users without sensitive password hashes."""
    with get_connection() as conn:
        if role_filter and role_filter in ("admin", "citizen"):
            rows = conn.execute("SELECT * FROM users WHERE role = ? ORDER BY created_at DESC", (role_filter,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [_sanitize_user_row(r) for r in rows]


def toggle_user_active(user_id: int, is_active: bool, actor: Dict[str, Any]) -> Tuple[bool, str]:
    """Activate or deactivate a user account (Admin only)."""
    if actor.get("role") != "admin":
        return False, "Unauthorized: Admin privileges required."
    if actor.get("id") == user_id and not is_active:
        return False, "You cannot deactivate your own active administrator account."

    with get_connection() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return False, "User not found."
        conn.execute("UPDATE users SET is_active = ?, failed_attempts = 0, locked_until = NULL WHERE id = ?", (1 if is_active else 0, user_id))
        conn.commit()

    action = "USER_ACTIVATED" if is_active else "USER_DEACTIVATED"
    log_audit(action, "user", str(user_id), f"Changed active status of '{row['username']}' to {is_active}", actor["id"], actor["username"], actor["role"])
    return True, f"Account '{row['username']}' updated."


def reset_user_password(user_id: int, new_password: str, actor: Dict[str, Any]) -> Tuple[bool, str]:
    """Reset a user's password (Admin only)."""
    if actor.get("role") != "admin":
        return False, "Unauthorized: Admin privileges required."
    try:
        pw_hash = hash_password(new_password)
    except ValueError as e:
        return False, str(e)

    with get_connection() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return False, "User not found."
        conn.execute("UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL WHERE id = ?", (pw_hash, user_id))
        conn.commit()

    log_audit("PASSWORD_RESET", "user", str(user_id), f"Reset password for '{row['username']}'", actor["id"], actor["username"], actor["role"])
    return True, f"Password reset successfully for '{row['username']}'."

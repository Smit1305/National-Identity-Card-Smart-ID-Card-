"""
Database Layer for Smart NIC – National Identity Card Management and Verification System
Implements all 9 normalized SQLite tables with foreign keys, constraints, timestamps, and indexes.
"""

import os
import sqlite3
from datetime import datetime
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "smart_nic_identity.db")
PHOTOS_DIR = os.path.join(BASE_DIR, "data", "photos")


def get_db_path() -> str:
    """Return active SQLite database file path (supports env override for tests)."""
    return os.environ.get("SMART_NIC_DB_PATH", DEFAULT_DB_PATH)


def get_connection() -> sqlite3.Connection:
    """Open SQLite connection with foreign keys enabled and dict-like rows."""
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def utc_now_str() -> str:
    """Return current local/ISO timestamp string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db() -> None:
    """Create all 9 tables, indexes, and default system settings if not present."""
    with get_connection() as conn:
        cur = conn.cursor()

        # 1. Citizens
        cur.execute("""
            CREATE TABLE IF NOT EXISTS citizens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                citizen_code TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                date_of_birth TEXT NOT NULL,
                gender TEXT NOT NULL CHECK(gender IN ('Male', 'Female', 'Other')),
                email TEXT UNIQUE NOT NULL,
                mobile_number TEXT NOT NULL,
                residential_address TEXT NOT NULL,
                city TEXT NOT NULL,
                state TEXT NOT NULL,
                postal_code TEXT NOT NULL,
                blood_group TEXT DEFAULT 'Unknown',
                supporting_doc_ref TEXT DEFAULT '',
                photo_path TEXT DEFAULT '',
                account_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(account_status IN ('ACTIVE', 'INACTIVE')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # 2. Users (Admin & Citizen logins — passwords hashed with bcrypt)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'citizen')),
                citizen_id INTEGER NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT NULL,
                FOREIGN KEY (citizen_id) REFERENCES citizens(id) ON DELETE SET NULL
            )
        """)

        # 3. Applications
        cur.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id TEXT UNIQUE NOT NULL,
                citizen_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending'
                    CHECK(status IN ('Pending', 'Under Review', 'Approved', 'Rejected')),
                rejection_reason TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                reviewed_by INTEGER NULL,
                reviewed_at TEXT NULL,
                submitted_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (citizen_id) REFERENCES citizens(id) ON DELETE CASCADE,
                FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
            )
        """)

        # 4. IdentityCards
        cur.execute("""
            CREATE TABLE IF NOT EXISTS identity_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nic_number TEXT UNIQUE NOT NULL,
                citizen_id INTEGER NOT NULL,
                application_id INTEGER NULL,
                issue_date TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE'
                    CHECK(status IN ('ACTIVE', 'INACTIVE', 'REVOKED', 'EXPIRED')),
                verification_token TEXT UNIQUE NOT NULL,
                token_signature TEXT NOT NULL,
                revocation_reason TEXT DEFAULT '',
                revoked_at TEXT NULL,
                issued_by INTEGER NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (citizen_id) REFERENCES citizens(id) ON DELETE CASCADE,
                FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL,
                FOREIGN KEY (issued_by) REFERENCES users(id) ON DELETE SET NULL
            )
        """)

        # 5. CardVerifications
        cur.execute("""
            CREATE TABLE IF NOT EXISTS card_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NULL,
                nic_number_queried TEXT DEFAULT '',
                token_fingerprint TEXT DEFAULT '',
                method TEXT NOT NULL CHECK(method IN ('QR_SCAN', 'MANUAL_CODE', 'API')),
                result TEXT NOT NULL CHECK(result IN ('VALID', 'EXPIRED', 'REVOKED', 'INVALID', 'NOT FOUND')),
                verifier_info TEXT DEFAULT 'Public Portal',
                verified_at TEXT NOT NULL,
                FOREIGN KEY (card_id) REFERENCES identity_cards(id) ON DELETE SET NULL
            )
        """)

        # 6. RenewalRequests
        cur.execute("""
            CREATE TABLE IF NOT EXISTS renewal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_code TEXT UNIQUE NOT NULL,
                citizen_id INTEGER NOT NULL,
                card_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending', 'Approved', 'Rejected')),
                admin_notes TEXT DEFAULT '',
                reviewed_by INTEGER NULL,
                new_card_id INTEGER NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT NULL,
                FOREIGN KEY (citizen_id) REFERENCES citizens(id) ON DELETE CASCADE,
                FOREIGN KEY (card_id) REFERENCES identity_cards(id) ON DELETE CASCADE,
                FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (new_card_id) REFERENCES identity_cards(id) ON DELETE SET NULL
            )
        """)

        # 7. ReplacementRequests
        cur.execute("""
            CREATE TABLE IF NOT EXISTS replacement_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_code TEXT UNIQUE NOT NULL,
                citizen_id INTEGER NOT NULL,
                card_id INTEGER NOT NULL,
                request_type TEXT NOT NULL CHECK(request_type IN ('LOST', 'DAMAGED')),
                incident_details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending', 'Approved', 'Rejected')),
                admin_notes TEXT DEFAULT '',
                reviewed_by INTEGER NULL,
                new_card_id INTEGER NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT NULL,
                FOREIGN KEY (citizen_id) REFERENCES citizens(id) ON DELETE CASCADE,
                FOREIGN KEY (card_id) REFERENCES identity_cards(id) ON DELETE CASCADE,
                FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (new_card_id) REFERENCES identity_cards(id) ON DELETE SET NULL
            )
        """)

        # 8. AuditLogs
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NULL,
                username TEXT DEFAULT 'system',
                role TEXT DEFAULT 'system',
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT DEFAULT '',
                details TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)

        # 9. SystemSettings
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                description TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
        """)

        # Indexes for fast search, filtering, and verification lookups
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_citizens_email ON citizens(email);",
            "CREATE INDEX IF NOT EXISTS idx_citizens_name ON citizens(full_name);",
            "CREATE INDEX IF NOT EXISTS idx_apps_status ON applications(status);",
            "CREATE INDEX IF NOT EXISTS idx_apps_citizen ON applications(citizen_id);",
            "CREATE INDEX IF NOT EXISTS idx_cards_nic ON identity_cards(nic_number);",
            "CREATE INDEX IF NOT EXISTS idx_cards_token ON identity_cards(verification_token);",
            "CREATE INDEX IF NOT EXISTS idx_cards_status ON identity_cards(status);",
            "CREATE INDEX IF NOT EXISTS idx_cards_citizen ON identity_cards(citizen_id);",
            "CREATE INDEX IF NOT EXISTS idx_verif_result ON card_verifications(result);",
            "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);",
        ]
        for idx_sql in indexes:
            cur.execute(idx_sql)

        # Default System Settings (academic prototype defaults)
        now = utc_now_str()
        default_settings = [
            ("portal_name", "Smart NIC – National Identity Card System", "Display title of the platform"),
            ("issuing_authority_demo", "Academic Demo Identity Authority (Prototype)", "Fictional designation printed on demo cards"),
            ("card_validity_years", "5", "Default validity period (in years) for newly issued Smart NIC cards"),
            ("max_login_attempts", "5", "Maximum consecutive failed logins before temporary lockout"),
            ("rate_limit_verifications_per_min", "30", "Public QR verification rate limit per session/minute"),
            ("public_qr_verification_enabled", "true", "Allow unauthenticated citizens/verifiers to verify QR codes"),
            ("demo_watermark_text", "ACADEMIC PROTOTYPE — NOT AN OFFICIAL GOVERNMENT ID", "Mandatory disclaimer printed on card back"),
        ]
        for k, v, desc in default_settings:
            cur.execute(
                "INSERT OR IGNORE INTO system_settings (key, value, description, updated_at) VALUES (?, ?, ?, ?)",
                (k, v, desc, now),
            )

        conn.commit()


def get_setting(key: str, default: str = "") -> str:
    """Fetch a single setting value from system_settings."""
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def update_setting(key: str, value: str, description: Optional[str] = None) -> None:
    """Update or insert a system setting."""
    now = utc_now_str()
    with get_connection() as conn:
        if description is not None:
            conn.execute(
                """
                INSERT INTO system_settings (key, value, description, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, description = excluded.description, updated_at = excluded.updated_at
                """,
                (key, str(value), description, now),
            )
        else:
            conn.execute(
                "UPDATE system_settings SET value = ?, updated_at = ? WHERE key = ?",
                (str(value), now, key),
            )
        conn.commit()


def get_all_settings():
    """Return all rows from system_settings as a list of dicts."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM system_settings ORDER BY key ASC").fetchall()
        return [dict(r) for r in rows]


def log_audit(
    action: str,
    entity_type: str,
    entity_id: str = "",
    details: str = "",
    user_id: Optional[int] = None,
    username: str = "system",
    role: str = "system",
) -> None:
    """Write an immutable audit log entry."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (user_id, username, role, action, entity_type, entity_id, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, username, role, action, entity_type, str(entity_id), details, utc_now_str()),
        )
        conn.commit()

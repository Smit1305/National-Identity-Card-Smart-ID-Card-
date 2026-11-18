"""
Citizen Registration & Citizen Management Service
Handles registration validation, duplicate detection, photo validation & storage,
profile editing, account activation/deactivation, and search/filtering.
"""

import os
import re
import io
import uuid
from datetime import datetime, date
from typing import Optional, Tuple, Dict, Any, List

from PIL import Image

from modules.database import get_connection, utc_now_str, log_audit, PHOTOS_DIR
from modules.auth_service import create_user

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MOBILE_RE = re.compile(r"^[0-9+\-\s]{10,15}$")
POSTAL_RE = re.compile(r"^[A-Za-z0-9\-\s]{4,10}$")
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB


def validate_and_save_photo(photo_bytes: Optional[bytes], filename_hint: str = "photo") -> Tuple[bool, str, str]:
    """
    Validate uploaded photograph bytes (format, size, dimensions) and save as clean PNG/JPEG.
    Returns (ok, message, saved_relative_or_abs_path).
    """
    if not photo_bytes:
        return True, "No photo provided", ""

    if len(photo_bytes) > MAX_PHOTO_BYTES:
        return False, "Photograph exceeds maximum allowed size of 5 MB.", ""

    try:
        img = Image.open(io.BytesIO(photo_bytes))
        fmt = (img.format or "").upper()
        if fmt not in ALLOWED_IMAGE_FORMATS:
            return False, "Invalid image format. Only JPG, PNG, and WEBP photographs are allowed.", ""
        img = img.convert("RGB")
        # Resize neatly for consistent ID card portraits
        img.thumbnail((600, 600))
        os.makedirs(PHOTOS_DIR, exist_ok=True)
        safe_name = f"{filename_hint}_{uuid.uuid4().hex[:10]}.jpg"
        save_path = os.path.join(PHOTOS_DIR, safe_name)
        img.save(save_path, format="JPEG", quality=90)
        return True, "Photograph saved.", save_path
    except Exception as e:
        return False, f"Corrupted or unreadable image file: {e}", ""


def validate_citizen_payload(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate required citizen registration fields."""
    full_name = (data.get("full_name") or "").strip()
    if len(full_name) < 3:
        return False, "Full name must be at least 3 characters."

    dob_str = str(data.get("date_of_birth") or "").strip()
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
        if dob > date.today():
            return False, "Date of birth cannot be in the future."
        if dob.year < 1900:
            return False, "Date of birth year must be 1900 or later."
    except ValueError:
        return False, "Date of birth must be in YYYY-MM-DD format."

    gender = (data.get("gender") or "").strip()
    if gender not in ("Male", "Female", "Other"):
        return False, "Gender must be Male, Female, or Other."

    email = (data.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        return False, "Please enter a valid email address."

    mobile = (data.get("mobile_number") or "").strip()
    digits_only = re.sub(r"\D", "", mobile)
    if not MOBILE_RE.match(mobile) or len(digits_only) < 10:
        return False, "Mobile number must contain at least 10 digits."

    if len((data.get("residential_address") or "").strip()) < 5:
        return False, "Residential address must be at least 5 characters."
    if len((data.get("city") or "").strip()) < 2:
        return False, "City is required."
    if len((data.get("state") or "").strip()) < 2:
        return False, "State is required."

    postal = (data.get("postal_code") or "").strip()
    if not POSTAL_RE.match(postal):
        return False, "Postal code must be 4–10 alphanumeric characters."

    return True, "Valid"


def _generate_next_code(table: str, prefix: str) -> str:
    """Generate sequential readable code like CIT-2026-0001 or APP-2026-0001."""
    year = datetime.now().year
    with get_connection() as conn:
        row = conn.execute(f"SELECT MAX(id) AS max_id FROM {table}").fetchone()
        next_num = int(row["max_id"] or 0) + 1
    return f"{prefix}-{year}-{next_num:04d}"


def register_citizen(
    data: Dict[str, Any],
    photo_bytes: Optional[bytes] = None,
    portal_password: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Register a new citizen, detect duplicates, validate/save photograph,
    automatically create a Pending application, and optionally create a citizen login account.
    """
    ok, msg = validate_citizen_payload(data)
    if not ok:
        return False, msg, None

    full_name = data["full_name"].strip()
    dob = str(data["date_of_birth"]).strip()
    gender = data["gender"].strip()
    email = data["email"].strip().lower()
    mobile = data["mobile_number"].strip()
    address = data["residential_address"].strip()
    city = data["city"].strip()
    state = data["state"].strip()
    postal = data["postal_code"].strip()
    blood_group = (data.get("blood_group") or "Unknown").strip() or "Unknown"
    doc_ref = (data.get("supporting_doc_ref") or "").strip()

    # Duplicate detection (by email OR same name + DOB + mobile)
    with get_connection() as conn:
        dup_email = conn.execute("SELECT id, citizen_code FROM citizens WHERE LOWER(email) = LOWER(?)", (email,)).fetchone()
        if dup_email:
            return False, f"Duplicate registration detected: email '{email}' is already registered ({dup_email['citizen_code']}).", None

        dup_person = conn.execute(
            "SELECT id, citizen_code FROM citizens WHERE LOWER(full_name) = LOWER(?) AND date_of_birth = ? AND mobile_number = ?",
            (full_name, dob, mobile),
        ).fetchone()
        if dup_person:
            return False, f"Duplicate application detected for {full_name} ({dup_person['citizen_code']}).", None

    # Validate & save photograph
    photo_path = data.get("photo_path", "")
    if photo_bytes:
        p_ok, p_msg, saved_path = validate_and_save_photo(photo_bytes, filename_hint="citizen")
        if not p_ok:
            return False, p_msg, None
        photo_path = saved_path

    now = utc_now_str()
    citizen_code = _generate_next_code("citizens", "CIT")
    application_id = _generate_next_code("applications", "APP")

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO citizens (
                citizen_code, full_name, date_of_birth, gender, email, mobile_number,
                residential_address, city, state, postal_code, blood_group,
                supporting_doc_ref, photo_path, account_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (
                citizen_code, full_name, dob, gender, email, mobile,
                address, city, state, postal, blood_group, doc_ref, photo_path, now, now
            ),
        )
        citizen_db_id = cur.lastrowid

        cur_app = conn.execute(
            """
            INSERT INTO applications (application_id, citizen_id, status, submitted_at, updated_at)
            VALUES (?, ?, 'Pending', ?, ?)
            """,
            (application_id, citizen_db_id, now, now),
        )
        app_db_id = cur_app.lastrowid
        conn.commit()

    # Optional citizen portal account creation
    portal_username = None
    if portal_password:
        base_uname = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())[:14] or f"cit{citizen_db_id}"
        portal_username = base_uname
        u_ok, _, _ = create_user(
            username=portal_username,
            email=email,
            full_name=full_name,
            password=portal_password,
            role="citizen",
            citizen_id=citizen_db_id,
            actor=actor,
        )
        if not u_ok:
            portal_username = f"{base_uname}{citizen_db_id}"
            create_user(
                username=portal_username,
                email=email,
                full_name=full_name,
                password=portal_password,
                role="citizen",
                citizen_id=citizen_db_id,
                actor=actor,
            )

    log_audit(
        "CITIZEN_REGISTERED",
        "citizen",
        citizen_code,
        f"Registered citizen '{full_name}' with application '{application_id}'",
        actor.get("id") if actor else None,
        actor.get("username", "self-registration") if actor else "self-registration",
        actor.get("role", "citizen") if actor else "citizen",
    )

    return True, f"Citizen registered successfully! Application ID: {application_id}", {
        "citizen_db_id": citizen_db_id,
        "citizen_code": citizen_code,
        "application_db_id": app_db_id,
        "application_id": application_id,
        "portal_username": portal_username,
    }


def list_citizens(
    search: str = "",
    status_filter: str = "ALL",
    gender_filter: str = "ALL",
    sort_by: str = "created_at",
    descending: bool = True,
) -> List[Dict[str, Any]]:
    """Query citizens with search, filters, and safe column sorting."""
    allowed_sort = {"created_at", "full_name", "citizen_code", "city", "state", "account_status"}
    col = sort_by if sort_by in allowed_sort else "created_at"
    direction = "DESC" if descending else "ASC"

    clauses = ["1=1"]
    params: List[Any] = []

    if search and search.strip():
        q = f"%{search.strip()}%"
        clauses.append("(full_name LIKE ? OR citizen_code LIKE ? OR email LIKE ? OR mobile_number LIKE ? OR city LIKE ?)")
        params.extend([q, q, q, q, q])

    if status_filter and status_filter != "ALL":
        clauses.append("account_status = ?")
        params.append(status_filter)

    if gender_filter and gender_filter != "ALL":
        clauses.append("gender = ?")
        params.append(gender_filter)

    sql = f"SELECT * FROM citizens WHERE {' AND '.join(clauses)} ORDER BY {col} {direction}"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_citizen_by_id(citizen_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single citizen record by primary key."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM citizens WHERE id = ?", (citizen_id,)).fetchone()
        return dict(row) if row else None


def update_citizen_profile(
    citizen_id: int,
    updates: Dict[str, Any],
    photo_bytes: Optional[bytes] = None,
    actor: Optional[Dict[str, Any]] = None,
    citizen_self_service: bool = False,
) -> Tuple[bool, str]:
    """
    Update citizen profile.
    If citizen_self_service=True, restrict editable fields to permitted contact/address/photo fields.
    """
    existing = get_citizen_by_id(citizen_id)
    if not existing:
        return False, "Citizen record not found."

    if citizen_self_service:
        allowed_fields = {"mobile_number", "residential_address", "city", "state", "postal_code", "blood_group"}
    else:
        allowed_fields = {
            "full_name", "date_of_birth", "gender", "email", "mobile_number",
            "residential_address", "city", "state", "postal_code", "blood_group",
            "supporting_doc_ref", "account_status"
        }

    merged = dict(existing)
    for k, v in updates.items():
        if k in allowed_fields and v is not None:
            merged[k] = str(v).strip()

    ok, msg = validate_citizen_payload(merged)
    if not ok:
        return False, msg

    if photo_bytes:
        p_ok, p_msg, saved_path = validate_and_save_photo(photo_bytes, filename_hint=f"cit_{citizen_id}")
        if not p_ok:
            return False, p_msg
        merged["photo_path"] = saved_path

    now = utc_now_str()
    try:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE citizens SET
                    full_name = ?, date_of_birth = ?, gender = ?, email = ?, mobile_number = ?,
                    residential_address = ?, city = ?, state = ?, postal_code = ?,
                    blood_group = ?, supporting_doc_ref = ?, photo_path = ?, account_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    merged["full_name"], merged["date_of_birth"], merged["gender"], merged["email"].lower(),
                    merged["mobile_number"], merged["residential_address"], merged["city"], merged["state"],
                    merged["postal_code"], merged["blood_group"], merged["supporting_doc_ref"],
                    merged["photo_path"], merged["account_status"], now, citizen_id,
                ),
            )
            conn.commit()
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            return False, "Email address is already in use by another citizen."
        return False, f"Update failed: {e}"

    log_audit(
        "CITIZEN_UPDATED",
        "citizen",
        existing["citizen_code"],
        f"Updated profile ({'self-service' if citizen_self_service else 'admin'})",
        actor.get("id") if actor else None,
        actor.get("username", "system") if actor else "system",
        actor.get("role", "system") if actor else "system",
    )
    return True, "Citizen profile updated successfully."


def toggle_citizen_account_status(citizen_id: int, new_status: str, actor: Dict[str, Any]) -> Tuple[bool, str]:
    """Activate or deactivate a citizen account (Admin only)."""
    if actor.get("role") != "admin":
        return False, "Unauthorized: Admin access required."
    if new_status not in ("ACTIVE", "INACTIVE"):
        return False, "Status must be ACTIVE or INACTIVE."

    existing = get_citizen_by_id(citizen_id)
    if not existing:
        return False, "Citizen not found."

    now = utc_now_str()
    with get_connection() as conn:
        conn.execute("UPDATE citizens SET account_status = ?, updated_at = ? WHERE id = ?", (new_status, now, citizen_id))
        conn.execute("UPDATE users SET is_active = ? WHERE citizen_id = ?", (1 if new_status == "ACTIVE" else 0, citizen_id))
        conn.commit()

    log_audit(
        "CITIZEN_STATUS_CHANGED",
        "citizen",
        existing["citizen_code"],
        f"Account status changed to {new_status}",
        actor["id"],
        actor["username"],
        actor["role"],
    )
    return True, f"Citizen account {existing['citizen_code']} set to {new_status}."


def get_citizen_history(citizen_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """Return application history and issued cards for a given citizen."""
    with get_connection() as conn:
        apps = conn.execute(
            "SELECT * FROM applications WHERE citizen_id = ? ORDER BY submitted_at DESC",
            (citizen_id,),
        ).fetchall()
        cards = conn.execute(
            "SELECT * FROM identity_cards WHERE citizen_id = ? ORDER BY created_at DESC",
            (citizen_id,),
        ).fetchall()
        renewals = conn.execute(
            "SELECT * FROM renewal_requests WHERE citizen_id = ? ORDER BY created_at DESC",
            (citizen_id,),
        ).fetchall()
        replacements = conn.execute(
            "SELECT * FROM replacement_requests WHERE citizen_id = ? ORDER BY created_at DESC",
            (citizen_id,),
        ).fetchall()

    return {
        "applications": [dict(r) for r in apps],
        "cards": [dict(r) for r in cards],
        "renewals": [dict(r) for r in renewals],
        "replacements": [dict(r) for r in replacements],
    }

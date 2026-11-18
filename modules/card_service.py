"""
Identity Card Lifecycle, Renewal & Replacement Management Service
Handles unique NIC number generation, card issuance, activation/deactivation/revocation,
expiry tracking, and complete renewal & lost/damaged replacement workflows.
"""

import secrets
from datetime import datetime, date, timedelta
from typing import Optional, Tuple, Dict, Any, List

from modules.database import get_connection, utc_now_str, log_audit, get_setting
from modules.qr_service import generate_verification_credential


def _generate_unique_nic_number() -> str:
    """Generate a guaranteed-unique fictional Smart NIC number: SNIC-YYYY-XXXXXX."""
    year = datetime.now().year
    with get_connection() as conn:
        for _ in range(50):
            digits = secrets.randbelow(900000) + 100000
            candidate = f"SNIC-{year}-{digits}"
            exists = conn.execute("SELECT 1 FROM identity_cards WHERE nic_number = ?", (candidate,)).fetchone()
            if not exists:
                return candidate
    raise RuntimeError("Unable to generate unique NIC number.")


def _generate_request_code(table: str, prefix: str) -> str:
    year = datetime.now().year
    with get_connection() as conn:
        row = conn.execute(f"SELECT MAX(id) AS m FROM {table}").fetchone()
        nxt = int(row["m"] or 0) + 1
    return f"{prefix}-{year}-{nxt:04d}"


def sync_expired_cards() -> int:
    """Mark any ACTIVE card whose expiry_date < today as EXPIRED."""
    today_s = date.today().strftime("%Y-%m-%d")
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE identity_cards SET status = 'EXPIRED' WHERE status = 'ACTIVE' AND expiry_date < ?",
            (today_s,),
        )
        conn.commit()
        return cur.rowcount


def issue_card_for_citizen(
    citizen_id: int,
    actor: Dict[str, Any],
    application_id: Optional[int] = None,
    validity_years: Optional[int] = None,
    revoke_previous: bool = True,
    revoke_reason: str = "Superseded by newly issued card",
    custom_issue_date: Optional[str] = None,
    custom_expiry_date: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Issue a new Smart NIC card with unique NIC number and cryptographic QR verification token.
    Admin privileges required.
    """
    if actor.get("role") != "admin":
        return False, "Unauthorized: Only administrators can issue identity cards.", None

    years = validity_years if validity_years is not None else int(get_setting("card_validity_years", "5") or 5)
    issue_dt = custom_issue_date or date.today().strftime("%Y-%m-%d")
    if custom_expiry_date:
        expiry_dt = custom_expiry_date
    else:
        try:
            base = datetime.strptime(issue_dt, "%Y-%m-%d").date()
            expiry_dt = base.replace(year=base.year + years).strftime("%Y-%m-%d")
        except ValueError:
            expiry_dt = (date.today() + timedelta(days=365 * years)).strftime("%Y-%m-%d")

    nic_number = _generate_unique_nic_number()
    token, sig = generate_verification_credential(nic_number)
    now = utc_now_str()

    with get_connection() as conn:
        cit = conn.execute("SELECT id, full_name, citizen_code FROM citizens WHERE id = ?", (citizen_id,)).fetchone()
        if not cit:
            return False, "Citizen record not found.", None

        if revoke_previous:
            conn.execute(
                """
                UPDATE identity_cards
                SET status = 'REVOKED', revocation_reason = ?, revoked_at = ?
                WHERE citizen_id = ? AND status = 'ACTIVE'
                """,
                (revoke_reason, now, citizen_id),
            )

        status = "EXPIRED" if expiry_dt < date.today().strftime("%Y-%m-%d") else "ACTIVE"

        cur = conn.execute(
            """
            INSERT INTO identity_cards (
                nic_number, citizen_id, application_id, issue_date, expiry_date,
                status, verification_token, token_signature, issued_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (nic_number, citizen_id, application_id, issue_dt, expiry_dt, status, token, sig, actor.get("id"), now),
        )
        card_id = cur.lastrowid
        conn.commit()

    log_audit(
        "CARD_ISSUED",
        "identity_card",
        nic_number,
        f"Issued Smart NIC {nic_number} to {cit['full_name']} (expires {expiry_dt})",
        actor.get("id"),
        actor.get("username", "admin"),
        actor.get("role", "admin"),
    )

    return True, f"Smart NIC {nic_number} issued successfully!", {
        "id": card_id,
        "nic_number": nic_number,
        "issue_date": issue_dt,
        "expiry_date": expiry_dt,
        "status": status,
    }


def list_cards(
    search: str = "",
    status_filter: str = "ALL",
    citizen_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """List issued Smart NIC cards joined with citizen details."""
    sync_expired_cards()
    clauses = ["1=1"]
    params: List[Any] = []

    if citizen_id is not None:
        clauses.append("ic.citizen_id = ?")
        params.append(citizen_id)

    if search and search.strip():
        q = f"%{search.strip()}%"
        clauses.append("(ic.nic_number LIKE ? OR c.full_name LIKE ? OR c.citizen_code LIKE ? OR c.city LIKE ?)")
        params.extend([q, q, q, q])

    if status_filter and status_filter != "ALL":
        clauses.append("ic.status = ?")
        params.append(status_filter)

    sql = f"""
        SELECT ic.*, c.full_name, c.citizen_code, c.date_of_birth, c.gender, c.email,
               c.mobile_number, c.residential_address, c.city, c.state, c.postal_code,
               c.blood_group, c.photo_path
        FROM identity_cards ic
        JOIN citizens c ON ic.citizen_id = c.id
        WHERE {' AND '.join(clauses)}
        ORDER BY ic.created_at DESC
    """
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_card_by_id(card_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single card with complete citizen profile."""
    sync_expired_cards()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT ic.*, c.full_name, c.citizen_code, c.date_of_birth, c.gender, c.email,
                   c.mobile_number, c.residential_address, c.city, c.state, c.postal_code,
                   c.blood_group, c.photo_path
            FROM identity_cards ic
            JOIN citizens c ON ic.citizen_id = c.id
            WHERE ic.id = ?
            """,
            (card_id,),
        ).fetchone()
        return dict(row) if row else None


def update_card_status(
    card_id: int,
    new_status: str,
    actor: Dict[str, Any],
    reason: str = "",
) -> Tuple[bool, str]:
    """Activate, Deactivate, or Revoke an issued Smart NIC (Admin only)."""
    if actor.get("role") != "admin":
        return False, "Unauthorized: Admin privileges required."
    if new_status not in ("ACTIVE", "INACTIVE", "REVOKED"):
        return False, "Status must be ACTIVE, INACTIVE, or REVOKED."

    card = get_card_by_id(card_id)
    if not card:
        return False, "Identity card not found."

    if new_status == "ACTIVE" and card["status"] == "REVOKED":
        return False, "Revoked credentials cannot be reactivated. Please issue a replacement card instead."

    if new_status == "ACTIVE" and card["expiry_date"] < date.today().strftime("%Y-%m-%d"):
        return False, "Expired cards cannot be reactivated. Please process a renewal instead."

    now = utc_now_str()
    revoked_at = now if new_status == "REVOKED" else card["revoked_at"]
    rev_reason = reason.strip() if new_status == "REVOKED" else card["revocation_reason"]

    with get_connection() as conn:
        conn.execute(
            "UPDATE identity_cards SET status = ?, revocation_reason = ?, revoked_at = ? WHERE id = ?",
            (new_status, rev_reason, revoked_at, card_id),
        )
        conn.commit()

    log_audit(
        f"CARD_{new_status}",
        "identity_card",
        card["nic_number"],
        f"Status updated to {new_status}" + (f" (Reason: {rev_reason})" if rev_reason else ""),
        actor.get("id"),
        actor.get("username", "admin"),
        actor.get("role", "admin"),
    )
    return True, f"Card {card['nic_number']} status updated to {new_status}."


# -----------------------------------------------------------------------------
# RENEWAL WORKFLOW
# -----------------------------------------------------------------------------
def submit_renewal_request(citizen_id: int, card_id: int, reason: str, actor: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    """Submit a card renewal request (Citizen for own card, or Admin)."""
    if actor.get("role") == "citizen" and actor.get("citizen_id") != citizen_id:
        return False, "Unauthorized: You can only request renewal for your own Smart NIC.", None
    if len((reason or "").strip()) < 5:
        return False, "Please provide a brief reason for renewal (at least 5 characters).", None

    card = get_card_by_id(card_id)
    if not card or card["citizen_id"] != citizen_id:
        return False, "Card not found for this citizen.", None

    with get_connection() as conn:
        dup = conn.execute(
            "SELECT request_code FROM renewal_requests WHERE card_id = ? AND status = 'Pending'",
            (card_id,),
        ).fetchone()
        if dup:
            return False, f"A pending renewal request ({dup['request_code']}) already exists for this card.", None

    req_code = _generate_request_code("renewal_requests", "REN")
    now = utc_now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO renewal_requests (request_code, citizen_id, card_id, reason, status, created_at)
            VALUES (?, ?, ?, ?, 'Pending', ?)
            """,
            (req_code, citizen_id, card_id, reason.strip(), now),
        )
        conn.commit()

    log_audit("RENEWAL_SUBMITTED", "renewal_request", req_code, f"Renewal requested for {card['nic_number']}", actor.get("id"), actor.get("username", ""), actor.get("role", ""))
    return True, f"Renewal request {req_code} submitted successfully.", req_code


def list_renewal_requests(status_filter: str = "ALL", citizen_id: Optional[int] = None) -> List[Dict[str, Any]]:
    clauses = ["1=1"]
    params: List[Any] = []
    if status_filter != "ALL":
        clauses.append("rr.status = ?")
        params.append(status_filter)
    if citizen_id is not None:
        clauses.append("rr.citizen_id = ?")
        params.append(citizen_id)

    sql = f"""
        SELECT rr.*, c.full_name, c.citizen_code, ic.nic_number, ic.expiry_date, ic.status AS card_status,
               nc.nic_number AS new_nic_number
        FROM renewal_requests rr
        JOIN citizens c ON rr.citizen_id = c.id
        JOIN identity_cards ic ON rr.card_id = ic.id
        LEFT JOIN identity_cards nc ON rr.new_card_id = nc.id
        WHERE {' AND '.join(clauses)}
        ORDER BY rr.created_at DESC
    """
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def process_renewal_request(request_id: int, approve: bool, admin_notes: str, actor: Dict[str, Any]) -> Tuple[bool, str]:
    """Admin review of a renewal request: if approved, revoke old card & issue renewed Smart NIC."""
    if actor.get("role") != "admin":
        return False, "Unauthorized: Only administrators can review renewal requests."

    with get_connection() as conn:
        req = conn.execute("SELECT * FROM renewal_requests WHERE id = ?", (request_id,)).fetchone()
        if not req:
            return False, "Renewal request not found."
        if req["status"] != "Pending":
            return False, f"Request {req['request_code']} has already been processed ({req['status']})."

    now = utc_now_str()
    if approve:
        ok, msg, new_card = issue_card_for_citizen(
            citizen_id=req["citizen_id"],
            actor=actor,
            revoke_previous=True,
            revoke_reason=f"Replaced via Renewal {req['request_code']}",
        )
        if not ok or not new_card:
            return False, msg

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE renewal_requests
                SET status = 'Approved', admin_notes = ?, reviewed_by = ?, new_card_id = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (admin_notes.strip(), actor.get("id"), new_card["id"], now, request_id),
            )
            conn.commit()
        log_audit("RENEWAL_APPROVED", "renewal_request", req["request_code"], f"Approved renewal; issued {new_card['nic_number']}", actor["id"], actor["username"], actor["role"])
        return True, f"Renewal approved! New Smart NIC {new_card['nic_number']} issued and previous credential revoked."
    else:
        if not (admin_notes or "").strip():
            return False, "Please provide a reason in admin notes when rejecting a request."
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE renewal_requests
                SET status = 'Rejected', admin_notes = ?, reviewed_by = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (admin_notes.strip(), actor.get("id"), now, request_id),
            )
            conn.commit()
        log_audit("RENEWAL_REJECTED", "renewal_request", req["request_code"], f"Rejected: {admin_notes.strip()}", actor["id"], actor["username"], actor["role"])
        return True, f"Renewal request {req['request_code']} rejected."


# -----------------------------------------------------------------------------
# REPLACEMENT WORKFLOW (LOST / DAMAGED)
# -----------------------------------------------------------------------------
def submit_replacement_request(
    citizen_id: int,
    card_id: int,
    request_type: str,
    incident_details: str,
    actor: Dict[str, Any],
) -> Tuple[bool, str, Optional[str]]:
    """Submit a LOST or DAMAGED card replacement request."""
    if actor.get("role") == "citizen" and actor.get("citizen_id") != citizen_id:
        return False, "Unauthorized: You can only report your own Smart NIC.", None
    req_type = (request_type or "").upper()
    if req_type not in ("LOST", "DAMAGED"):
        return False, "Request type must be LOST or DAMAGED.", None
    if len((incident_details or "").strip()) < 5:
        return False, "Please provide incident details (at least 5 characters).", None

    card = get_card_by_id(card_id)
    if not card or card["citizen_id"] != citizen_id:
        return False, "Card not found for this citizen.", None

    with get_connection() as conn:
        dup = conn.execute(
            "SELECT request_code FROM replacement_requests WHERE card_id = ? AND status = 'Pending'",
            (card_id,),
        ).fetchone()
        if dup:
            return False, f"A pending replacement request ({dup['request_code']}) already exists for this card.", None

    req_code = _generate_request_code("replacement_requests", "REP")
    now = utc_now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO replacement_requests (request_code, citizen_id, card_id, request_type, incident_details, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'Pending', ?)
            """,
            (req_code, citizen_id, card_id, req_type, incident_details.strip(), now),
        )
        conn.commit()

    log_audit("REPLACEMENT_SUBMITTED", "replacement_request", req_code, f"{req_type} report for {card['nic_number']}", actor.get("id"), actor.get("username", ""), actor.get("role", ""))
    return True, f"Replacement request {req_code} ({req_type}) submitted successfully.", req_code


def list_replacement_requests(status_filter: str = "ALL", citizen_id: Optional[int] = None) -> List[Dict[str, Any]]:
    clauses = ["1=1"]
    params: List[Any] = []
    if status_filter != "ALL":
        clauses.append("rp.status = ?")
        params.append(status_filter)
    if citizen_id is not None:
        clauses.append("rp.citizen_id = ?")
        params.append(citizen_id)

    sql = f"""
        SELECT rp.*, c.full_name, c.citizen_code, ic.nic_number, ic.status AS card_status,
               nc.nic_number AS new_nic_number
        FROM replacement_requests rp
        JOIN citizens c ON rp.citizen_id = c.id
        JOIN identity_cards ic ON rp.card_id = ic.id
        LEFT JOIN identity_cards nc ON rp.new_card_id = nc.id
        WHERE {' AND '.join(clauses)}
        ORDER BY rp.created_at DESC
    """
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def process_replacement_request(request_id: int, approve: bool, admin_notes: str, actor: Dict[str, Any]) -> Tuple[bool, str]:
    """Admin review of a LOST/DAMAGED replacement request: revokes old credential & issues new card."""
    if actor.get("role") != "admin":
        return False, "Unauthorized: Only administrators can review replacement requests."

    with get_connection() as conn:
        req = conn.execute("SELECT * FROM replacement_requests WHERE id = ?", (request_id,)).fetchone()
        if not req:
            return False, "Replacement request not found."
        if req["status"] != "Pending":
            return False, f"Request {req['request_code']} has already been processed ({req['status']})."

    now = utc_now_str()
    if approve:
        ok, msg, new_card = issue_card_for_citizen(
            citizen_id=req["citizen_id"],
            actor=actor,
            revoke_previous=True,
            revoke_reason=f"Revoked due to {req['request_type']} report ({req['request_code']})",
        )
        if not ok or not new_card:
            return False, msg

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE replacement_requests
                SET status = 'Approved', admin_notes = ?, reviewed_by = ?, new_card_id = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (admin_notes.strip(), actor.get("id"), new_card["id"], now, request_id),
            )
            conn.commit()
        log_audit("REPLACEMENT_APPROVED", "replacement_request", req["request_code"], f"Approved {req['request_type']}; issued {new_card['nic_number']}", actor["id"], actor["username"], actor["role"])
        return True, f"Replacement approved! Previous card revoked and new Smart NIC {new_card['nic_number']} issued."
    else:
        if not (admin_notes or "").strip():
            return False, "Please provide a reason in admin notes when rejecting a replacement request."
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE replacement_requests
                SET status = 'Rejected', admin_notes = ?, reviewed_by = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (admin_notes.strip(), actor.get("id"), now, request_id),
            )
            conn.commit()
        log_audit("REPLACEMENT_REJECTED", "replacement_request", req["request_code"], f"Rejected: {admin_notes.strip()}", actor["id"], actor["username"], actor["role"])
        return True, f"Replacement request {req['request_code']} rejected."

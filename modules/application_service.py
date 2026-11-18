"""
Application Management Service
Handles Pending -> Under Review -> Approved / Rejected workflow,
role-based admin authorization, rejection reasons, and Smart NIC issuance upon approval.
"""

from typing import Optional, Tuple, Dict, Any, List

from modules.database import get_connection, utc_now_str, log_audit
from modules.card_service import issue_card_for_citizen


def list_applications(
    status_filter: str = "ALL",
    search: str = "",
    citizen_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """List submitted identity card applications joined with citizen details."""
    clauses = ["1=1"]
    params: List[Any] = []

    if status_filter and status_filter != "ALL":
        clauses.append("a.status = ?")
        params.append(status_filter)

    if citizen_id is not None:
        clauses.append("a.citizen_id = ?")
        params.append(citizen_id)

    if search and search.strip():
        q = f"%{search.strip()}%"
        clauses.append("(a.application_id LIKE ? OR c.full_name LIKE ? OR c.email LIKE ? OR c.citizen_code LIKE ?)")
        params.extend([q, q, q, q])

    sql = f"""
        SELECT a.*, c.citizen_code, c.full_name, c.date_of_birth, c.gender, c.email,
               c.mobile_number, c.residential_address, c.city, c.state, c.postal_code,
               c.blood_group, c.supporting_doc_ref, c.photo_path,
               u.username AS reviewed_by_username,
               (SELECT nic_number FROM identity_cards ic WHERE ic.application_id = a.id ORDER BY ic.id DESC LIMIT 1) AS issued_nic_number
        FROM applications a
        JOIN citizens c ON a.citizen_id = c.id
        LEFT JOIN users u ON a.reviewed_by = u.id
        WHERE {' AND '.join(clauses)}
        ORDER BY a.submitted_at DESC
    """
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_application_by_id(app_db_id: int) -> Optional[Dict[str, Any]]:
    """Return full details of a single application."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT a.*, c.citizen_code, c.full_name, c.date_of_birth, c.gender, c.email,
                   c.mobile_number, c.residential_address, c.city, c.state, c.postal_code,
                   c.blood_group, c.supporting_doc_ref, c.photo_path,
                   u.username AS reviewed_by_username,
                   (SELECT nic_number FROM identity_cards ic WHERE ic.application_id = a.id ORDER BY ic.id DESC LIMIT 1) AS issued_nic_number
            FROM applications a
            JOIN citizens c ON a.citizen_id = c.id
            LEFT JOIN users u ON a.reviewed_by = u.id
            WHERE a.id = ?
            """,
            (app_db_id,),
        ).fetchone()
        return dict(row) if row else None


def mark_under_review(app_db_id: int, actor: Dict[str, Any], notes: str = "") -> Tuple[bool, str]:
    """Move a Pending application into Under Review status (Admin only)."""
    if actor.get("role") != "admin":
        return False, "Unauthorized: Only administrators can review applications."

    app = get_application_by_id(app_db_id)
    if not app:
        return False, "Application not found."
    if app["status"] not in ("Pending", "Under Review"):
        return False, f"Cannot move application from '{app['status']}' to 'Under Review'."

    now = utc_now_str()
    with get_connection() as conn:
        conn.execute(
            "UPDATE applications SET status = 'Under Review', notes = ?, reviewed_by = ?, updated_at = ? WHERE id = ?",
            (notes.strip(), actor.get("id"), now, app_db_id),
        )
        conn.commit()

    log_audit("APPLICATION_UNDER_REVIEW", "application", app["application_id"], f"Marked Under Review for {app['full_name']}", actor["id"], actor["username"], actor["role"])
    return True, f"Application {app['application_id']} moved to Under Review."


def approve_application(
    app_db_id: int,
    actor: Dict[str, Any],
    issue_card_immediately: bool = True,
    notes: str = "",
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Approve an application and optionally issue the Smart NIC immediately (Admin only)."""
    if actor.get("role") != "admin":
        return False, "Unauthorized: Only administrators can approve applications.", None

    app = get_application_by_id(app_db_id)
    if not app:
        return False, "Application not found.", None
    if app["status"] == "Approved":
        return False, f"Application {app['application_id']} is already approved.", None

    now = utc_now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE applications
            SET status = 'Approved', rejection_reason = '', notes = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (notes.strip(), actor.get("id"), now, now, app_db_id),
        )
        conn.commit()

    log_audit("APPLICATION_APPROVED", "application", app["application_id"], f"Approved application for {app['full_name']}", actor["id"], actor["username"], actor["role"])

    issued_card = None
    if issue_card_immediately:
        ok, c_msg, issued_card = issue_card_for_citizen(
            citizen_id=app["citizen_id"],
            actor=actor,
            application_id=app_db_id,
            revoke_previous=True,
            revoke_reason=f"Superseded by approved application {app['application_id']}",
        )
        if not ok:
            return True, f"Application approved, but card issuance reported: {c_msg}", None
        return True, f"Application {app['application_id']} approved and Smart NIC {issued_card['nic_number']} issued!", issued_card

    return True, f"Application {app['application_id']} approved. You may now issue the Smart NIC.", None


def reject_application(
    app_db_id: int,
    rejection_reason: str,
    actor: Dict[str, Any],
) -> Tuple[bool, str]:
    """Reject an application with a mandatory reason (Admin only)."""
    if actor.get("role") != "admin":
        return False, "Unauthorized: Only administrators can reject applications."
    if len((rejection_reason or "").strip()) < 5:
        return False, "Please provide a clear rejection reason (at least 5 characters)."

    app = get_application_by_id(app_db_id)
    if not app:
        return False, "Application not found."
    if app["status"] == "Approved":
        return False, "Cannot reject an already approved application."

    now = utc_now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE applications
            SET status = 'Rejected', rejection_reason = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (rejection_reason.strip(), actor.get("id"), now, now, app_db_id),
        )
        conn.commit()

    log_audit("APPLICATION_REJECTED", "application", app["application_id"], f"Rejected: {rejection_reason.strip()}", actor["id"], actor["username"], actor["role"])
    return True, f"Application {app['application_id']} rejected."

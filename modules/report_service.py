"""
Analytics, Reports & Audit Logs Service
Generates real-time dashboard statistics from SQLite, date-filtered operational reports,
and downloadable CSV and PDF exports.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd
from fpdf import FPDF

from modules.database import get_connection
from modules.card_service import sync_expired_cards


def get_dashboard_metrics() -> Dict[str, Any]:
    """Compute all Admin Dashboard KPIs directly from SQLite."""
    sync_expired_cards()
    with get_connection() as conn:
        total_citizens = conn.execute("SELECT COUNT(*) FROM citizens").fetchone()[0]
        active_citizens = conn.execute("SELECT COUNT(*) FROM citizens WHERE account_status = 'ACTIVE'").fetchone()[0]
        active_cards = conn.execute("SELECT COUNT(*) FROM identity_cards WHERE status = 'ACTIVE'").fetchone()[0]
        expired_cards = conn.execute("SELECT COUNT(*) FROM identity_cards WHERE status = 'EXPIRED'").fetchone()[0]
        revoked_cards = conn.execute("SELECT COUNT(*) FROM identity_cards WHERE status = 'REVOKED'").fetchone()[0]
        total_cards = conn.execute("SELECT COUNT(*) FROM identity_cards").fetchone()[0]

        pending_apps = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('Pending', 'Under Review')").fetchone()[0]
        approved_apps = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'Approved'").fetchone()[0]
        rejected_apps = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'Rejected'").fetchone()[0]

        pending_renewals = conn.execute("SELECT COUNT(*) FROM renewal_requests WHERE status = 'Pending'").fetchone()[0]
        pending_replacements = conn.execute("SELECT COUNT(*) FROM replacement_requests WHERE status = 'Pending'").fetchone()[0]
        total_verifications = conn.execute("SELECT COUNT(*) FROM card_verifications").fetchone()[0]

        # Application status breakdown
        app_rows = conn.execute("SELECT status, COUNT(*) AS count FROM applications GROUP BY status").fetchall()
        app_status_df = pd.DataFrame([dict(r) for r in app_rows]) if app_rows else pd.DataFrame(columns=["status", "count"])

        # Card status breakdown
        card_rows = conn.execute("SELECT status, COUNT(*) AS count FROM identity_cards GROUP BY status").fetchall()
        card_status_df = pd.DataFrame([dict(r) for r in card_rows]) if card_rows else pd.DataFrame(columns=["status", "count"])

        # Monthly registration stats (YYYY-MM)
        monthly_rows = conn.execute(
            """
            SELECT substr(created_at, 1, 7) AS month, COUNT(*) AS registrations
            FROM citizens
            GROUP BY substr(created_at, 1, 7)
            ORDER BY month ASC
            """
        ).fetchall()
        monthly_df = pd.DataFrame([dict(r) for r in monthly_rows]) if monthly_rows else pd.DataFrame(columns=["month", "registrations"])

        # Verification breakdown
        verif_rows = conn.execute("SELECT result, COUNT(*) AS count FROM card_verifications GROUP BY result").fetchall()
        verif_df = pd.DataFrame([dict(r) for r in verif_rows]) if verif_rows else pd.DataFrame(columns=["result", "count"])

        # Recent registrations
        recent_reg = [
            dict(r) for r in conn.execute(
                "SELECT citizen_code, full_name, city, state, account_status, created_at FROM citizens ORDER BY created_at DESC LIMIT 6"
            ).fetchall()
        ]

        # Recent verification activity
        recent_verif = [
            dict(r) for r in conn.execute(
                """
                SELECT cv.nic_number_queried AS nic_number, cv.method, cv.result, cv.verifier_info, cv.verified_at
                FROM card_verifications cv
                ORDER BY cv.verified_at DESC LIMIT 6
                """
            ).fetchall()
        ]

    return {
        "total_citizens": total_citizens,
        "active_citizens": active_citizens,
        "active_cards": active_cards,
        "expired_cards": expired_cards,
        "revoked_cards": revoked_cards,
        "total_cards": total_cards,
        "pending_apps": pending_apps,
        "approved_apps": approved_apps,
        "rejected_apps": rejected_apps,
        "pending_renewals": pending_renewals,
        "pending_replacements": pending_replacements,
        "total_verifications": total_verifications,
        "app_status_df": app_status_df,
        "card_status_df": card_status_df,
        "monthly_df": monthly_df,
        "verif_df": verif_df,
        "recent_registrations": recent_reg,
        "recent_verifications": recent_verif,
    }


def get_report_dataframe(
    report_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Query date-filtered operational reports from SQLite.
    report_type options:
      - 'citizens'
      - 'issued_cards'
      - 'pending_applications'
      - 'expired_cards'
      - 'rejected_applications'
      - 'qr_verifications'
    """
    sync_expired_cards()
    sd = f"{start_date} 00:00:00" if start_date else "1900-01-01 00:00:00"
    ed = f"{end_date} 23:59:59" if end_date else "2999-12-31 23:59:59"

    with get_connection() as conn:
        if report_type == "citizens":
            rows = conn.execute(
                """
                SELECT citizen_code AS 'Citizen Code', full_name AS 'Full Name', date_of_birth AS 'DOB',
                       gender AS 'Gender', email AS 'Email', mobile_number AS 'Mobile',
                       city AS 'City', state AS 'State', account_status AS 'Status', created_at AS 'Registered At'
                FROM citizens
                WHERE created_at BETWEEN ? AND ?
                ORDER BY created_at DESC
                """,
                (sd, ed),
            ).fetchall()

        elif report_type == "issued_cards":
            rows = conn.execute(
                """
                SELECT ic.nic_number AS 'NIC Number', c.full_name AS 'Citizen Name', c.citizen_code AS 'Citizen Code',
                       ic.issue_date AS 'Issue Date', ic.expiry_date AS 'Expiry Date', ic.status AS 'Card Status',
                       ic.created_at AS 'Issued At'
                FROM identity_cards ic
                JOIN citizens c ON ic.citizen_id = c.id
                WHERE ic.created_at BETWEEN ? AND ?
                ORDER BY ic.created_at DESC
                """,
                (sd, ed),
            ).fetchall()

        elif report_type == "pending_applications":
            rows = conn.execute(
                """
                SELECT a.application_id AS 'Application ID', c.full_name AS 'Citizen Name', c.email AS 'Email',
                       c.city AS 'City', a.status AS 'Status', a.submitted_at AS 'Submitted At'
                FROM applications a
                JOIN citizens c ON a.citizen_id = c.id
                WHERE a.status IN ('Pending', 'Under Review') AND a.submitted_at BETWEEN ? AND ?
                ORDER BY a.submitted_at DESC
                """,
                (sd, ed),
            ).fetchall()

        elif report_type == "expired_cards":
            rows = conn.execute(
                """
                SELECT ic.nic_number AS 'NIC Number', c.full_name AS 'Citizen Name', c.mobile_number AS 'Mobile',
                       ic.issue_date AS 'Issue Date', ic.expiry_date AS 'Expiry Date', ic.status AS 'Status'
                FROM identity_cards ic
                JOIN citizens c ON ic.citizen_id = c.id
                WHERE ic.status = 'EXPIRED' AND ic.created_at BETWEEN ? AND ?
                ORDER BY ic.expiry_date ASC
                """,
                (sd, ed),
            ).fetchall()

        elif report_type == "rejected_applications":
            rows = conn.execute(
                """
                SELECT a.application_id AS 'Application ID', c.full_name AS 'Citizen Name', c.email AS 'Email',
                       a.rejection_reason AS 'Rejection Reason', a.reviewed_at AS 'Reviewed At'
                FROM applications a
                JOIN citizens c ON a.citizen_id = c.id
                WHERE a.status = 'Rejected' AND a.submitted_at BETWEEN ? AND ?
                ORDER BY a.submitted_at DESC
                """,
                (sd, ed),
            ).fetchall()

        elif report_type == "qr_verifications":
            rows = conn.execute(
                """
                SELECT cv.id AS 'Log ID', cv.nic_number_queried AS 'NIC Queried',
                       COALESCE(c.full_name, 'Unknown') AS 'Holder Name',
                       cv.method AS 'Method', cv.result AS 'Result',
                       cv.verifier_info AS 'Source', cv.verified_at AS 'Verified At'
                FROM card_verifications cv
                LEFT JOIN identity_cards ic ON cv.card_id = ic.id
                LEFT JOIN citizens c ON ic.citizen_id = c.id
                WHERE cv.verified_at BETWEEN ? AND ?
                ORDER BY cv.verified_at DESC
                """,
                (sd, ed),
            ).fetchall()
        else:
            rows = []

    return pd.DataFrame([dict(r) for r in rows])


def list_audit_logs(action_filter: str = "ALL", search: str = "", limit: int = 200) -> List[Dict[str, Any]]:
    """Retrieve immutable system audit logs."""
    clauses = ["1=1"]
    params: List[Any] = []
    if action_filter and action_filter != "ALL":
        clauses.append("action = ?")
        params.append(action_filter)
    if search and search.strip():
        q = f"%{search.strip()}%"
        clauses.append("(username LIKE ? OR action LIKE ? OR entity_id LIKE ? OR details LIKE ?)")
        params.extend([q, q, q, q])
    params.append(limit)

    sql = f"SELECT * FROM audit_logs WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Convert DataFrame to UTF-8 CSV bytes."""
    if df.empty:
        return b""
    return df.to_csv(index=False).encode("utf-8")


def _ascii_safe(val: Any, max_len: int = 28) -> str:
    s = str(val if val is not None else "").encode("latin-1", errors="replace").decode("latin-1")
    return (s[: max_len - 2] + "..") if len(s) > max_len else s


def dataframe_to_pdf_bytes(title: str, df: pd.DataFrame, subtitle: str = "") -> bytes:
    """Generate a clean landscape A4 tabular PDF report using FPDF."""
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 9, _ascii_safe(f"Smart NIC System - {title}", 90), ln=True, align="L")

    pdf.set_font("Arial", "", 9)
    pdf.set_text_color(100, 116, 139)
    meta = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  Records: {len(df)}"
    if subtitle:
        meta = f"{subtitle}  |  {meta}"
    pdf.cell(0, 6, _ascii_safe(meta, 120), ln=True, align="L")
    pdf.ln(3)

    if df.empty:
        pdf.set_font("Arial", "I", 11)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(0, 10, "No records matched the selected report filters.", ln=True)
    else:
        cols = list(df.columns)[:8]  # Fit neatly across landscape A4 (277 mm usable width)
        col_w = 275.0 / max(1, len(cols))

        # Header Row
        pdf.set_fill_color(37, 99, 235)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", "B", 8)
        for c in cols:
            pdf.cell(col_w, 8, _ascii_safe(c, 22), border=1, align="L", fill=True)
        pdf.ln()

        # Data Rows
        pdf.set_font("Arial", "", 8)
        pdf.set_text_color(15, 23, 42)
        for idx, (_, row) in enumerate(df.head(150).iterrows()):
            fill = idx % 2 == 1
            pdf.set_fill_color(248, 250, 252)
            for c in cols:
                pdf.cell(col_w, 7, _ascii_safe(row[c], 26), border=1, align="L", fill=fill)
            pdf.ln()

    out = pdf.output(dest="S")
    return out.encode("latin-1") if isinstance(out, str) else bytes(out)

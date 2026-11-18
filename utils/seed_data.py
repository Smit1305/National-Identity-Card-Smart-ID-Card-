"""
Fictional Demonstration Data Seeder for Smart NIC – National Identity Card System
Creates demo admin & citizen accounts (bcrypt-hashed), fictional citizens with generated
portrait avatars, applications across all statuses, active/expired/revoked Smart NIC cards,
renewal/replacement requests, and sample QR verification logs.

All records are 100% fictional for academic demonstration only.
"""

import os
from datetime import datetime, date, timedelta
from typing import Dict, Any

from PIL import Image, ImageDraw, ImageFont

from modules.database import init_db, get_connection, PHOTOS_DIR, log_audit
from modules.auth_service import hash_password
from modules.qr_service import generate_verification_credential, verify_credential, build_qr_payload


def _create_demo_avatar(filename: str, initials: str, bg_rgb: tuple) -> str:
    """Create a clean, stylized portrait placeholder image for fictional demo citizens."""
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    path = os.path.join(PHOTOS_DIR, filename)
    if os.path.exists(path):
        return path

    img = Image.new("RGB", (320, 380), bg_rgb)
    draw = ImageDraw.Draw(img)

    # Soft lighter gradient panel
    draw.rectangle([0, 260, 320, 380], fill=(max(bg_rgb[0] - 25, 0), max(bg_rgb[1] - 25, 0), max(bg_rgb[2] - 25, 0)))

    # Silhouette head & shoulders
    draw.ellipse([105, 70, 215, 180], fill=(255, 255, 255))
    draw.pieslice([55, 195, 265, 410], 180, 360, fill=(255, 255, 255))

    # Initials badge in top-right
    draw.rounded_rectangle([230, 18, 302, 54], radius=10, fill=(15, 23, 42))
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 20)
    except Exception:
        font = ImageFont.load_default()
    draw.text((248, 24), initials[:2].upper(), fill=(255, 255, 255), font=font)

    img.save(path, format="JPEG", quality=90)
    return path


def seed_demo_data_if_empty() -> bool:
    """
    Initialize database and populate fictional demo data ONLY if users table is empty.
    Returns True if seeded, False if already populated.
    """
    init_db()
    with get_connection() as conn:
        existing_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if existing_users > 0:
            return False

    now = datetime.now()
    admin_hash = hash_password("Admin@123")
    citizen_hash = hash_password("Citizen@123")

    with get_connection() as conn:
        cur = conn.cursor()

        # 1. Create Demo Administrator
        cur.execute(
            """
            INSERT INTO users (username, email, full_name, password_hash, role, citizen_id, is_active, created_at)
            VALUES (?, ?, ?, ?, 'admin', NULL, 1, ?)
            """,
            ("admin", "admin@smartnic.demo", "Dr. System Administrator", admin_hash, (now - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")),
        )
        admin_id = cur.lastrowid

        # 2. Fictional Demo Citizens (across 5 months for realistic monthly analytics)
        demo_citizens = [
            {
                "code": "CIT-2026-0001", "username": "aarav.sharma", "name": "Aarav Sharma",
                "dob": "1998-04-14", "gender": "Male", "email": "aarav.sharma@example.demo",
                "mobile": "9800011221", "address": "14 Lotus Enclave, Sector 7", "city": "Anand",
                "state": "Gujarat", "postal": "388001", "blood": "O+", "doc": "DEMO-DOC-1001",
                "color": (37, 99, 235), "days_ago": 110, "app_status": "Approved",
                "card_type": "ACTIVE",
            },
            {
                "code": "CIT-2026-0002", "username": "priya.desai", "name": "Priya Desai",
                "dob": "2000-09-22", "gender": "Female", "email": "priya.desai@example.demo",
                "mobile": "9800011222", "address": "204 Green Park Residency, Ring Road", "city": "Ahmedabad",
                "state": "Gujarat", "postal": "380015", "blood": "A+", "doc": "DEMO-DOC-1002",
                "color": (124, 58, 237), "days_ago": 85, "app_status": "Approved",
                "card_type": "ACTIVE_RENEWAL",
            },
            {
                "code": "CIT-2026-0003", "username": "kabir.mehta", "name": "Kabir Mehta",
                "dob": "1994-01-30", "gender": "Male", "email": "kabir.mehta@example.demo",
                "mobile": "9800011223", "address": "88 Horizon Towers, University Road", "city": "Vadodara",
                "state": "Gujarat", "postal": "390002", "blood": "B+", "doc": "DEMO-DOC-1003",
                "color": (217, 119, 6), "days_ago": 70, "app_status": "Approved",
                "card_type": "EXPIRED",
            },
            {
                "code": "CIT-2026-0004", "username": "meera.nair", "name": "Meera Nair",
                "dob": "1996-07-09", "gender": "Female", "email": "meera.nair@example.demo",
                "mobile": "9800011224", "address": "52 Maple Avenue, Tech Park", "city": "Surat",
                "state": "Gujarat", "postal": "395007", "blood": "AB+", "doc": "DEMO-DOC-1004",
                "color": (225, 29, 72), "days_ago": 55, "app_status": "Approved",
                "card_type": "REVOKED_LOST",
            },
            {
                "code": "CIT-2026-0005", "username": "nisha.patel", "name": "Nisha Patel",
                "dob": "2001-11-03", "gender": "Female", "email": "nisha.patel@example.demo",
                "mobile": "9800011225", "address": "7B Shanti Niketan, College Road", "city": "Nadiad",
                "state": "Gujarat", "postal": "387001", "blood": "O-", "doc": "DEMO-DOC-1005",
                "color": (5, 150, 105), "days_ago": 38, "app_status": "Approved",
                "card_type": "ACTIVE",
            },
            {
                "code": "CIT-2026-0006", "username": "rohan.verma", "name": "Rohan Verma",
                "dob": "1999-05-18", "gender": "Male", "email": "rohan.verma@example.demo",
                "mobile": "9800011226", "address": "310 Riverview Apartments", "city": "Rajkot",
                "state": "Gujarat", "postal": "360005", "blood": "A-", "doc": "DEMO-DOC-1006",
                "color": (8, 145, 178), "days_ago": 15, "app_status": "Pending",
                "card_type": None,
            },
            {
                "code": "CIT-2026-0007", "username": "ananya.iyer", "name": "Ananya Iyer",
                "dob": "2002-02-26", "gender": "Female", "email": "ananya.iyer@example.demo",
                "mobile": "9800011227", "address": "19 Cedar Lane, Knowledge City", "city": "Gandhinagar",
                "state": "Gujarat", "postal": "382010", "blood": "B-", "doc": "DEMO-DOC-1007",
                "color": (79, 70, 229), "days_ago": 8, "app_status": "Under Review",
                "card_type": None,
            },
            {
                "code": "CIT-2026-0008", "username": "dev.kulkarni", "name": "Dev Kulkarni",
                "dob": "1995-12-11", "gender": "Male", "email": "dev.kulkarni@example.demo",
                "mobile": "9800011228", "address": "402 Oakwood Heights", "city": "Pune",
                "state": "Maharashtra", "postal": "411004", "blood": "O+", "doc": "DEMO-DOC-1008",
                "color": (71, 85, 105), "days_ago": 4, "app_status": "Rejected",
                "card_type": None,
            },
        ]

        created_cards = []
        for idx, c in enumerate(demo_citizens, start=1):
            ts = (now - timedelta(days=c["days_ago"])).strftime("%Y-%m-%d %H:%M:%S")
            initials = "".join([w[0] for w in c["name"].split()[:2]])
            photo_path = _create_demo_avatar(f"demo_{c['username']}.jpg", initials, c["color"])

            cur.execute(
                """
                INSERT INTO citizens (
                    citizen_code, full_name, date_of_birth, gender, email, mobile_number,
                    residential_address, city, state, postal_code, blood_group,
                    supporting_doc_ref, photo_path, account_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
                """,
                (
                    c["code"], c["name"], c["dob"], c["gender"], c["email"], c["mobile"],
                    c["address"], c["city"], c["state"], c["postal"], c["blood"],
                    c["doc"], photo_path, ts, ts,
                ),
            )
            cit_id = cur.lastrowid

            # Citizen login account
            cur.execute(
                """
                INSERT INTO users (username, email, full_name, password_hash, role, citizen_id, is_active, created_at)
                VALUES (?, ?, ?, ?, 'citizen', ?, 1, ?)
                """,
                (c["username"], c["email"], c["name"], citizen_hash, cit_id, ts),
            )

            # Application record
            app_code = f"APP-2026-{idx:04d}"
            rej_reason = "Supporting residential document reference was incomplete. Please resubmit." if c["app_status"] == "Rejected" else ""
            rev_by = admin_id if c["app_status"] in ("Approved", "Rejected", "Under Review") else None
            rev_at = ts if c["app_status"] in ("Approved", "Rejected") else None

            cur.execute(
                """
                INSERT INTO applications (application_id, citizen_id, status, rejection_reason, reviewed_by, reviewed_at, submitted_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (app_code, cit_id, c["app_status"], rej_reason, rev_by, rev_at, ts, ts),
            )
            app_db_id = cur.lastrowid

            # Issue Smart NIC card for approved demo citizens
            if c["card_type"]:
                nic_num = f"SNIC-2026-{840000 + idx * 137}"
                token, sig = generate_verification_credential(nic_num)
                if c["card_type"] == "EXPIRED":
                    issue_d = (date.today() - timedelta(days=365 * 5 + 30)).strftime("%Y-%m-%d")
                    expiry_d = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
                    c_status = "EXPIRED"
                    rev_r, rev_t = "", None
                elif c["card_type"] == "REVOKED_LOST":
                    issue_d = (date.today() - timedelta(days=180)).strftime("%Y-%m-%d")
                    expiry_d = (date.today() + timedelta(days=365 * 4 + 180)).strftime("%Y-%m-%d")
                    c_status = "REVOKED"
                    rev_r = "Reported lost by cardholder"
                    rev_t = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    issue_d = (date.today() - timedelta(days=c["days_ago"])).strftime("%Y-%m-%d")
                    expiry_d = (date.today() + timedelta(days=365 * 5 - c["days_ago"])).strftime("%Y-%m-%d")
                    c_status = "ACTIVE"
                    rev_r, rev_t = "", None

                cur.execute(
                    """
                    INSERT INTO identity_cards (
                        nic_number, citizen_id, application_id, issue_date, expiry_date,
                        status, verification_token, token_signature, revocation_reason, revoked_at, issued_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (nic_num, cit_id, app_db_id, issue_d, expiry_d, c_status, token, sig, rev_r, rev_t, admin_id, ts),
                )
                card_id = cur.lastrowid
                created_cards.append((nic_num, token, sig, c_status))

                if c["card_type"] == "ACTIVE_RENEWAL":
                    cur.execute(
                        """
                        INSERT INTO renewal_requests (request_code, citizen_id, card_id, reason, status, created_at)
                        VALUES ('REN-2026-0001', ?, ?, 'Updating portrait photograph and extending card validity', 'Pending', ?)
                        """,
                        (cit_id, card_id, (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")),
                    )
                elif c["card_type"] == "REVOKED_LOST":
                    cur.execute(
                        """
                        INSERT INTO replacement_requests (request_code, citizen_id, card_id, request_type, incident_details, status, created_at)
                        VALUES ('REP-2026-0001', ?, ?, 'LOST', 'Card misplaced during campus transit; requesting replacement credential', 'Pending', ?)
                        """,
                        (cit_id, card_id, (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")),
                    )

        conn.commit()

    # 3. Seed realistic QR verification history via the real verification engine
    for nic_num, token, sig, _ in created_cards:
        payload = build_qr_payload(token, sig)
        verify_credential(payload, method="QR_SCAN", verifier_info="Campus Gate Terminal #1", rate_limit_key="seed")
    verify_credential("SNIC-2026-999999", method="MANUAL_CODE", verifier_info="Public Web Verifier", rate_limit_key="seed")

    log_audit("SYSTEM_SEEDED", "system", "init", "Populated fictional demonstration citizens, applications, cards, and verifications", None, "system", "system")
    return True

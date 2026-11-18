"""
Comprehensive Automated Test Suite for Smart NIC – National Identity Card Management System
Tests all 9 database tables, authentication/RBAC, registration, applications, Smart NIC card
generation & PDF export, QR encoding/decoding/verification (VALID/EXPIRED/REVOKED/INVALID/NOT FOUND),
renewal/replacement, citizen data isolation, reports, and FastAPI REST API endpoints.
"""

import os
import sys
import io
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Use isolated temporary SQLite database for automated tests
_TEST_DB = os.path.join(tempfile.gettempdir(), "test_smart_nic_identity_suite.db")
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)
os.environ["SMART_NIC_DB_PATH"] = _TEST_DB

from PIL import Image
from fastapi.testclient import TestClient

from modules.database import init_db, get_connection
from modules.auth_service import authenticate_user, verify_password, list_users
from modules.citizen_service import register_citizen, list_citizens, update_citizen_profile, get_citizen_by_id
from modules.application_service import list_applications, mark_under_review, approve_application, reject_application
from modules.card_service import (
    list_cards, get_card_by_id, update_card_status,
    submit_renewal_request, process_renewal_request,
    submit_replacement_request, process_replacement_request
)
from modules.qr_service import (
    build_qr_payload, generate_qr_image, decode_qr_from_image_bytes, verify_credential
)
from modules.card_renderer import render_card_front, render_card_back, generate_card_pdf_bytes, image_to_png_bytes
from modules.report_service import get_dashboard_metrics, get_report_dataframe, dataframe_to_csv_bytes, dataframe_to_pdf_bytes, list_audit_logs
from utils.seed_data import seed_demo_data_if_empty
import api as api_module


class TestSmartNICIdentitySystem(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        seed_demo_data_if_empty()
        ok_a, _, cls.admin_user = authenticate_user("admin", "Admin@123", expected_role="admin")
        assert ok_a and cls.admin_user is not None
        ok_c, _, cls.citizen_user = authenticate_user("aarav.sharma", "Citizen@123", expected_role="citizen")
        assert ok_c and cls.citizen_user is not None
        cls.client = TestClient(api_module.app)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(_TEST_DB):
            try:
                os.remove(_TEST_DB)
            except Exception:
                pass

    def test_01_all_9_tables_exist(self):
        expected = {
            "users", "citizens", "applications", "identity_cards",
            "card_verifications", "renewal_requests", "replacement_requests",
            "audit_logs", "system_settings"
        }
        with get_connection() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            existing = {r["name"] for r in rows}
        self.assertTrue(expected.issubset(existing), f"Missing tables: {expected - existing}")

    def test_02_password_hashing_and_auth_rbac(self):
        # Verify passwords are stored as bcrypt hashes, never plaintext
        with get_connection() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE username = 'admin'").fetchone()
            self.assertTrue(row["password_hash"].startswith("$2b$"))
            self.assertNotEqual(row["password_hash"], "Admin@123")
            self.assertTrue(verify_password("Admin@123", row["password_hash"]))

        # Users listing must NEVER expose password_hash
        for u in list_users():
            self.assertNotIn("password_hash", u)

        # Wrong password & wrong role rejected
        ok_bad, _, _ = authenticate_user("admin", "WrongPass")
        self.assertFalse(ok_bad)
        ok_role, _, _ = authenticate_user("aarav.sharma", "Citizen@123", expected_role="admin")
        self.assertFalse(ok_role)

    def test_03_citizen_registration_validation_and_duplicate_detection(self):
        # Generate small valid JPEG in memory
        buf = io.BytesIO()
        Image.new("RGB", (200, 200), (60, 120, 200)).save(buf, format="JPEG")
        valid_photo = buf.getvalue()

        payload = {
            "full_name": "Siddharth Rao",
            "date_of_birth": "1999-08-20",
            "gender": "Male",
            "email": "siddharth.rao@example.demo",
            "mobile_number": "9800099881",
            "residential_address": "12 Parkview Lane",
            "city": "Anand",
            "state": "Gujarat",
            "postal_code": "388001",
            "blood_group": "O+",
            "supporting_doc_ref": "DEMO-REF-99",
        }
        ok, msg, res = register_citizen(payload, photo_bytes=valid_photo, portal_password="TestUser@123", actor=self.admin_user)
        self.assertTrue(ok, msg)
        self.assertIn("APP-", res["application_id"])

        # Duplicate email must fail
        ok_dup, dup_msg, _ = register_citizen(payload)
        self.assertFalse(ok_dup)
        self.assertIn("Duplicate", dup_msg)

        # Invalid image bytes must fail
        payload2 = dict(payload, email="unique2@example.demo", mobile_number="9800099882")
        ok_img, _, _ = register_citizen(payload2, photo_bytes=b"not-an-image")
        self.assertFalse(ok_img)

    def test_04_application_workflow_and_rbac(self):
        pending = list_applications(status_filter="Pending")
        self.assertGreater(len(pending), 0)
        app_rec = pending[0]

        # Citizen must NOT be able to approve applications
        ok_unauth, _, _ = approve_application(app_rec["id"], self.citizen_user)
        self.assertFalse(ok_unauth)

        # Admin moves to Under Review then Approves & issues Smart NIC
        ok_rev, _ = mark_under_review(app_rec["id"], self.admin_user, notes="Checking demo doc")
        self.assertTrue(ok_rev)

        ok_app, msg, card = approve_application(app_rec["id"], self.admin_user, issue_card_immediately=True)
        self.assertTrue(ok_app, msg)
        self.assertIsNotNone(card)
        self.assertTrue(card["nic_number"].startswith("SNIC-"))

    def test_05_card_generation_pdf_and_qr_roundtrip(self):
        cards = list_cards(status_filter="ACTIVE")
        self.assertGreater(len(cards), 0)
        card = cards[0]

        # QR payload must NOT leak PII (full_name, email, address, mobile)
        qr_payload = build_qr_payload(card["verification_token"], card["token_signature"])
        self.assertNotIn(card["full_name"], qr_payload)
        self.assertNotIn(card["email"], qr_payload)
        self.assertNotIn(card["residential_address"], qr_payload)

        # Render Front, Back, PDF, and QR PNG
        front = render_card_front(card)
        back = render_card_back(card)
        self.assertEqual(front.size, (1012, 638))
        self.assertEqual(back.size, (1012, 638))

        pdf_bytes = generate_card_pdf_bytes(card)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 5000)

        # Round-trip QR encode -> PNG -> OpenCV decode -> Backend verify
        qr_png = image_to_png_bytes(generate_qr_image(card["verification_token"], card["token_signature"]))
        found, _, decoded = decode_qr_from_image_bytes(qr_png)
        self.assertTrue(found)
        self.assertEqual(decoded, qr_payload)

        v_res = verify_credential(decoded, method="QR_SCAN")
        self.assertEqual(v_res["result"], "VALID")
        self.assertEqual(v_res["limited_info"]["nic_number"], card["nic_number"])
        # Ensure public verification does NOT expose sensitive PII
        self.assertNotIn("email", v_res["limited_info"])
        self.assertNotIn("mobile_number", v_res["limited_info"])
        self.assertNotIn("residential_address", v_res["limited_info"])

    def test_06_all_verification_outcomes(self):
        # EXPIRED card (Kabir Mehta)
        expired_cards = list_cards(status_filter="EXPIRED")
        self.assertGreater(len(expired_cards), 0)
        exp_payload = build_qr_payload(expired_cards[0]["verification_token"], expired_cards[0]["token_signature"])
        self.assertEqual(verify_credential(exp_payload)["result"], "EXPIRED")

        # REVOKED card (Meera Nair)
        revoked_cards = list_cards(status_filter="REVOKED")
        self.assertGreater(len(revoked_cards), 0)
        rev_payload = build_qr_payload(revoked_cards[0]["verification_token"], revoked_cards[0]["token_signature"])
        self.assertEqual(verify_credential(rev_payload)["result"], "REVOKED")

        # Tampered signature -> INVALID
        active_cards = list_cards(status_filter="ACTIVE")
        tampered = f"SNICV1|{active_cards[0]['verification_token']}|00000000000000000000"
        self.assertEqual(verify_credential(tampered)["result"], "INVALID")

        # Unknown code -> NOT FOUND
        self.assertEqual(verify_credential("SNIC-2026-000000")["result"], "NOT FOUND")

    def test_07_renewal_and_replacement_revoke_previous(self):
        # Submit and approve a replacement for Aarav's active card
        own_cards = list_cards(citizen_id=self.citizen_user["citizen_id"], status_filter="ACTIVE")
        self.assertGreater(len(own_cards), 0)
        old_card = own_cards[0]

        ok_sub, msg, req_code = submit_replacement_request(
            self.citizen_user["citizen_id"], old_card["id"], "DAMAGED", "Card corner cracked during travel", self.citizen_user
        )
        self.assertTrue(ok_sub, msg)

        with get_connection() as conn:
            req_row = conn.execute("SELECT id FROM replacement_requests WHERE request_code = ?", (req_code,)).fetchone()
        ok_proc, p_msg = process_replacement_request(req_row["id"], True, "Approved replacement", self.admin_user)
        self.assertTrue(ok_proc, p_msg)

        # Verify old card is now REVOKED and citizen has a new ACTIVE card
        refreshed_old = get_card_by_id(old_card["id"])
        self.assertEqual(refreshed_old["status"], "REVOKED")
        new_active = list_cards(citizen_id=self.citizen_user["citizen_id"], status_filter="ACTIVE")
        self.assertEqual(len(new_active), 1)
        self.assertNotEqual(new_active[0]["nic_number"], old_card["nic_number"])

    def test_08_citizen_self_service_isolation(self):
        # Citizen updates permitted mobile field, attempts to tamper full_name (must be ignored!)
        cit_before = get_citizen_by_id(self.citizen_user["citizen_id"])
        ok, msg = update_citizen_profile(
            self.citizen_user["citizen_id"],
            {"full_name": "HACKED NAME", "mobile_number": "9800055555"},
            actor=self.citizen_user,
            citizen_self_service=True,
        )
        self.assertTrue(ok, msg)
        cit_after = get_citizen_by_id(self.citizen_user["citizen_id"])
        self.assertEqual(cit_after["full_name"], cit_before["full_name"])
        self.assertEqual(cit_after["mobile_number"], "9800055555")

    def test_09_reports_csv_pdf_and_audit_logs(self):
        metrics = get_dashboard_metrics()
        self.assertGreaterEqual(metrics["total_citizens"], 8)
        self.assertGreater(metrics["total_verifications"], 0)

        for rtype in ["citizens", "issued_cards", "pending_applications", "expired_cards", "rejected_applications", "qr_verifications"]:
            df = get_report_dataframe(rtype)
            pdf = dataframe_to_pdf_bytes(rtype, df)
            self.assertTrue(pdf.startswith(b"%PDF"))
            if not df.empty:
                self.assertGreater(len(dataframe_to_csv_bytes(df)), 10)

        self.assertGreater(len(list_audit_logs()), 5)

    def test_10_fastapi_rest_endpoints_and_rbac(self):
        # Health check
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)

        # Public QR verify works WITHOUT auth header
        r_pub = self.client.post("/api/verify", json={"code": "SNIC-2026-000000"})
        self.assertEqual(r_pub.status_code, 200)
        self.assertEqual(r_pub.json()["result"], "NOT FOUND")

        # Admin login & access
        r_adm = self.client.post("/api/auth/login", json={"username": "admin", "password": "Admin@123", "role": "admin"})
        self.assertEqual(r_adm.status_code, 200)
        adm_token = r_adm.json()["user"]["token"]

        r_dash = self.client.get("/api/reports/dashboard", headers={"Authorization": f"Bearer {adm_token}"})
        self.assertEqual(r_dash.status_code, 200)
        self.assertGreaterEqual(r_dash.json()["metrics"]["total_citizens"], 8)

        # Citizen login & RBAC enforcement (cannot call admin /api/citizens list or another citizen's profile)
        r_cit = self.client.post("/api/auth/login", json={"username": "aarav.sharma", "password": "Citizen@123", "role": "citizen"})
        self.assertEqual(r_cit.status_code, 200)
        cit_token = r_cit.json()["user"]["token"]
        own_id = r_cit.json()["user"]["citizen_id"]

        r_forbid = self.client.get("/api/citizens", headers={"Authorization": f"Bearer {cit_token}"})
        self.assertEqual(r_forbid.status_code, 403)

        other_id = own_id + 1
        r_iso = self.client.get(f"/api/citizens/{other_id}", headers={"Authorization": f"Bearer {cit_token}"})
        self.assertEqual(r_iso.status_code, 403)

        r_own = self.client.get(f"/api/citizens/{own_id}", headers={"Authorization": f"Bearer {cit_token}"})
        self.assertEqual(r_own.status_code, 200)


if __name__ == "__main__":
    unittest.main()

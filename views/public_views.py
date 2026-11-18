"""
Public & Shared Views: Top Header Bar, Authentication Portal, Public QR Verification,
and Citizen Registration Form.
"""

import os
from datetime import date
from typing import Optional, Dict, Any

import pandas as pd
import streamlit as st
from PIL import Image

from modules.auth_service import authenticate_user
from modules.citizen_service import register_citizen
from modules.qr_service import decode_qr_from_image_bytes, verify_credential, list_verifications
from utils.helpers import get_status_badge_html


def render_top_header_bar(title_text: str, subtitle_text: str = "", user: Optional[Dict[str, Any]] = None):
    """Consistent academic SaaS top header bar across every page."""
    sub_html = f'<div class="page-main-subtitle">{subtitle_text}</div>' if subtitle_text else ""

    if user and user.get("role") == "admin":
        role_badge = f'<div class="pill-admin-tag">🛡️ ADMIN: {user.get("username")}</div>'
    elif user and user.get("role") == "citizen":
        role_badge = f'<div class="pill-citizen-tag">👤 CITIZEN: {user.get("full_name")}</div>'
    else:
        role_badge = '<div class="pill-admin-tag">🪪 PUBLIC ACCESS PORTAL</div>'

    st.markdown(
        f"""
        <div class="top-header-bar">
            <div>
                <div class="page-main-title">🪪 {title_text}</div>
                {sub_html}
            </div>
            <div class="header-badge-container">
                <div class="pill-status-green">
                    <span class="status-dot-green"></span> Academic Prototype Online
                </div>
                {role_badge}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_login_page():
    """Authentication Portal supporting Administrator Login and Citizen Login."""
    render_top_header_bar(
        "Smart NIC – National Identity Card Portal",
        "Secure digital identity registration, credential issuance, and cryptographic QR verification (Academic Prototype)",
    )

    col_l, col_c, col_r = st.columns([0.5, 2.2, 0.5])
    with col_c:
        st.markdown(
            """
            <div class="dashboard-panel-card" style="text-align: center; padding: 24px 28px;">
                <div style="width: 54px; height: 54px; background: #2563EB; border-radius: 12px; display: inline-flex; align-items: center; justify-content: center; font-size: 1.6rem; color: white; margin-bottom: 10px; box-shadow: 0 4px 12px rgba(37,99,235,0.22);">🪪</div>
                <div style="font-size: 1.4rem; font-weight: 800; color: #0F172A;">Sign In to Smart NIC System</div>
                <div style="font-size: 0.84rem; color: #64748B; margin-top: 4px;">
                    National Identity Card Management & Verification Platform (B.Tech ECE Minor Project Prototype)
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        tab_admin, tab_citizen = st.tabs(["🛡️ Administrator Login", "👤 Citizen Login"])

        with tab_admin:
            with st.form("admin_login_form", clear_on_submit=False):
                admin_user = st.text_input("Admin Username or Email", placeholder="e.g. admin")
                admin_pass = st.text_input("Password", type="password", placeholder="Enter password")
                submitted = st.form_submit_button("🔐 Sign In as Administrator", type="primary", use_container_width=True)
                if submitted:
                    ok, msg, user_data = authenticate_user(admin_user, admin_pass, expected_role="admin")
                    if ok and user_data:
                        st.session_state["auth_user"] = user_data
                        st.session_state["nav_page"] = "Dashboard"
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        with tab_citizen:
            with st.form("citizen_login_form", clear_on_submit=False):
                cit_user = st.text_input("Citizen Username or Email", placeholder="e.g. aarav.sharma")
                cit_pass = st.text_input("Password", type="password", placeholder="Enter password")
                submitted_c = st.form_submit_button("🔐 Sign In as Citizen", type="primary", use_container_width=True)
                if submitted_c:
                    ok, msg, user_data = authenticate_user(cit_user, cit_pass, expected_role="citizen")
                    if ok and user_data:
                        st.session_state["auth_user"] = user_data
                        st.session_state["nav_page"] = "My Dashboard"
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        # Documented Fictional Demo Credentials Box
        st.markdown(
            """
            <div class="dashboard-panel-card" style="background: #F8FAFC; margin-top: 14px; padding: 16px 20px;">
                <div style="font-weight: 700; color: #0F172A; font-size: 0.88rem; margin-bottom: 8px;">🧪 Demonstration Credentials (100% Fictional Data)</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 0.8rem; color: #334155;">
                    <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 10px;">
                        <b style="color: #2563EB;">Admin Account</b><br>
                        Username: <code>admin</code><br>
                        Password: <code>Admin@123</code>
                    </div>
                    <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 10px;">
                        <b style="color: #059669;">Demo Citizen Accounts</b><br>
                        Active Card: <code>aarav.sharma</code> / <code>Citizen@123</code><br>
                        Expired Card: <code>kabir.mehta</code> / <code>Citizen@123</code><br>
                        Revoked Card: <code>meera.nair</code> / <code>Citizen@123</code>
                    </div>
                </div>
                <div style="font-size: 0.74rem; color: #64748B; margin-top: 10px;">
                    ⚠️ Academic prototype disclaimer: All identities, cards, and QR credentials are fictional demonstrations and do not represent official government documents.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _display_verification_outcome(res: Dict[str, Any]):
    """Render minimal, privacy-preserving verification result banner."""
    outcome = res.get("result", "INVALID")
    message = res.get("message", "")
    info = res.get("limited_info")

    css_map = {
        "VALID": ("verify-valid", "✅", "#059669"),
        "EXPIRED": ("verify-expired", "⚠️", "#D97706"),
        "REVOKED": ("verify-revoked", "🚫", "#DC2626"),
        "INVALID": ("verify-invalid", "❌", "#DC2626"),
        "NOT FOUND": ("verify-notfound", "🔎", "#475569"),
    }
    cls, icon, color = css_map.get(outcome, ("verify-invalid", "❌", "#DC2626"))

    st.markdown(
        f"""
        <div class="verify-banner {cls}">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div style="font-size: 1.25rem; font-weight: 800; color: {color};">{icon} VERIFICATION STATUS: {outcome}</div>
                {get_status_badge_html(outcome)}
            </div>
            <div style="font-size: 0.9rem; color: #1E293B; margin-top: 6px; font-weight: 500;">{message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if info:
        c1, c2 = st.columns([1, 2.5])
        with c1:
            p_path = info.get("photo_path", "")
            if outcome == "VALID" and p_path and os.path.exists(p_path):
                st.image(p_path, width=150, caption="Verified Cardholder")
            else:
                st.markdown(
                    """
                    <div style="background: #F1F5F9; border: 1px solid #E2E8F0; border-radius: 10px; padding: 26px 12px; text-align: center; color: #64748B; font-size: 0.82rem;">
                        Portrait hidden for non-valid credentials
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        with c2:
            st.markdown(
                f"""
                <div class="dashboard-panel-card" style="margin-bottom: 0;">
                    <div class="panel-card-title">Limited Public Credential Summary</div>
                    <div class="panel-card-subtitle">Privacy-protected output — sensitive personal contact & address details are withheld</div>
                    <div class="inner-session-box" style="margin-top: 12px; margin-bottom: 0;">
                        <div>
                            <div class="session-meta-label">NIC NUMBER</div>
                            <div class="session-meta-value-blue">{info['nic_number']}</div>
                        </div>
                        <div>
                            <div class="session-meta-label">CARDHOLDER NAME</div>
                            <div class="session-meta-value">{info['full_name']}</div>
                        </div>
                        <div>
                            <div class="session-meta-label">CARD STATUS</div>
                            <div class="session-meta-value">{info['card_status']}</div>
                        </div>
                        <div>
                            <div class="session-meta-label">ISSUE / EXPIRY</div>
                            <div class="session-meta-value">{info['issue_date']} → {info['expiry_date']}</div>
                        </div>
                    </div>
                    <div style="font-size: 0.74rem; color: #64748B; margin-top: 10px;">
                        Verified at: <code>{info['verification_timestamp']}</code> &nbsp;|&nbsp; {info['demo_notice']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_qr_verification_page(user: Optional[Dict[str, Any]] = None):
    """
    Public & Admin QR Code Verification Portal.
    Accessible WITHOUT administrator login; exposes ONLY minimum necessary credential status.
    Supports Camera QR scan, Uploaded QR image scan, and Manual verification code entry.
    """
    render_top_header_bar(
        "QR Code & Smart NIC Verification",
        "Verify card authenticity, expiry, and revocation status using cryptographic tokens (no sensitive PII inside QR)",
        user=user,
    )

    tab_manual, tab_camera, tab_upload = st.tabs([
        "⌨️ Manual Code / NIC Entry",
        "📷 Live Camera QR Scanner",
        "🖼️ Upload QR / Card Image",
    ])

    with tab_manual:
        st.markdown(
            """
            <div class="dashboard-panel-card" style="padding: 16px 20px;">
                <div class="panel-card-title">Verify by Verification Token or NIC Number</div>
                <div class="panel-card-subtitle">Paste a signed QR payload (<code>SNICV1|token|sig</code>) or enter a demo NIC number (e.g., <code>SNIC-2026-840137</code>)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("manual_verify_form"):
            code_in = st.text_input("Verification Code or NIC Number", placeholder="SNIC-2026-840137  or  SNICV1|...")
            verifier_label = st.text_input("Verifier / Checkpoint Label (Optional)", value="Public Web Portal")
            do_verify = st.form_submit_button("🔍 Verify Smart NIC Credential", type="primary", use_container_width=True)
            if do_verify:
                res = verify_credential(code_in, method="MANUAL_CODE", verifier_info=verifier_label or "Public Portal")
                st.session_state["last_verify_result"] = res

    with tab_camera:
        st.markdown(
            """
            <div class="dashboard-panel-card" style="padding: 16px 20px;">
                <div class="panel-card-title">Camera QR Scanner (OpenCV QRCodeDetector)</div>
                <div class="panel-card-subtitle">Hold the Smart NIC QR code steadily inside the camera frame and capture a snapshot</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        cam_photo = st.camera_input("Capture QR Code via Webcam")
        if cam_photo is not None:
            found, d_msg, decoded = decode_qr_from_image_bytes(cam_photo.getvalue())
            if found and decoded:
                st.success(f"QR payload scanned successfully.")
                res = verify_credential(decoded, method="QR_SCAN", verifier_info="Webcam QR Scanner")
                st.session_state["last_verify_result"] = res
            else:
                st.warning(d_msg)

    with tab_upload:
        st.markdown(
            """
            <div class="dashboard-panel-card" style="padding: 16px 20px;">
                <div class="panel-card-title">Verify from Downloaded Card Front or QR Image</div>
                <div class="panel-card-subtitle">Upload a Smart NIC front PNG or standalone QR code image (JPG/PNG) to scan and verify</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        up_img = st.file_uploader("Upload Card or QR Image", type=["png", "jpg", "jpeg"], key="qr_upload_verifier")
        if up_img is not None:
            if st.button("🔎 Decode & Verify Uploaded QR Image", type="primary", use_container_width=True):
                found, d_msg, decoded = decode_qr_from_image_bytes(up_img.getvalue())
                if found and decoded:
                    res = verify_credential(decoded, method="QR_SCAN", verifier_info="Uploaded Image QR Scanner")
                    st.session_state["last_verify_result"] = res
                else:
                    st.error(d_msg)

    # Render latest verification result
    if st.session_state.get("last_verify_result"):
        st.markdown("---")
        _display_verification_outcome(st.session_state["last_verify_result"])

    # Quick demo test codes helper
    with st.expander("🧪 Demo NIC Numbers for Quick Testing"):
        st.markdown("""
        - **VALID (Active Card):** `SNIC-2026-840137` (Aarav Sharma)
        - **EXPIRED Card:** `SNIC-2026-840411` (Kabir Mehta)
        - **REVOKED Card:** `SNIC-2026-840548` (Meera Nair)
        - **TAMPERED Signature (INVALID):** `SNICV1|fake_token|bad_sig`
        - **NOT FOUND:** `SNIC-2026-000000`
        """)

    # Admin-only verification history table on this page
    if user and user.get("role") == "admin":
        st.markdown("---")
        st.markdown(
            """
            <div class="dashboard-panel-card">
                <div class="panel-card-title">Recent Verification Audit Activity</div>
                <div class="panel-card-subtitle">All QR scan & manual lookup attempts logged in SQLite</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        logs = list_verifications(limit=25)
        if logs:
            st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
        else:
            st.info("No verification records yet.")


def render_citizen_registration_form(actor: Optional[Dict[str, Any]] = None):
    """Module 2: Complete Citizen Registration Form with validation, duplicate check & photo upload."""
    is_admin = actor is not None and actor.get("role") == "admin"
    render_top_header_bar(
        "Citizen Registration & Smart NIC Application",
        "Register a new fictional citizen profile and submit a National Identity Card application",
        user=actor,
    )

    with st.form("citizen_registration_form", clear_on_submit=False):
        st.markdown("#### 1. Personal Identity Information")
        c1, c2, c3 = st.columns(3)
        with c1:
            full_name = st.text_input("Full Name *", placeholder="e.g. Vikram Joshi")
        with c2:
            dob = st.date_input("Date of Birth *", value=date(2000, 1, 15), min_value=date(1920, 1, 1), max_value=date.today())
        with c3:
            gender = st.selectbox("Gender *", ["Male", "Female", "Other"])

        c4, c5, c6 = st.columns(3)
        with c4:
            email = st.text_input("Email Address *", placeholder="e.g. vikram.joshi@example.demo")
        with c5:
            mobile = st.text_input("Mobile Number *", placeholder="e.g. 9800012345")
        with c6:
            blood_group = st.selectbox("Blood Group (Optional)", ["Unknown", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"])

        st.markdown("#### 2. Residential Address")
        address = st.text_input("Residential Address *", placeholder="House/Flat No., Street, Locality")
        a1, a2, a3 = st.columns(3)
        with a1:
            city = st.text_input("City *", placeholder="e.g. Anand")
        with a2:
            state = st.text_input("State *", placeholder="e.g. Gujarat")
        with a3:
            postal_code = st.text_input("Postal Code *", placeholder="e.g. 388001")

        st.markdown("#### 3. Photograph, Supporting Reference & Portal Account")
        p1, p2 = st.columns(2)
        with p1:
            photo_file = st.file_uploader("Citizen Portrait Photograph (JPG/PNG/WEBP, max 5MB)", type=["jpg", "jpeg", "png", "webp"])
            supporting_doc = st.text_input("Supporting Document Reference (Optional)", placeholder="e.g. DEMO-REF-2026-01")
        with p2:
            create_portal_acc = st.checkbox("Create Citizen Self-Service Portal Login", value=True)
            portal_pw = st.text_input("Citizen Portal Password (min 6 chars)", type="password", value="Citizen@123" if is_admin else "")
            st.caption("⚠️ Use fictional demonstration data only. Do not enter real Aadhaar or government ID numbers.")

        submit_btn = st.form_submit_button("📝 Submit Registration & Smart NIC Application", type="primary", use_container_width=True)

        if submit_btn:
            photo_bytes = photo_file.getvalue() if photo_file is not None else None
            pw_to_use = portal_pw if create_portal_acc else None
            if create_portal_acc and len(portal_pw or "") < 6:
                st.error("Citizen portal password must be at least 6 characters long.")
            else:
                payload = {
                    "full_name": full_name,
                    "date_of_birth": dob.strftime("%Y-%m-%d"),
                    "gender": gender,
                    "email": email,
                    "mobile_number": mobile,
                    "residential_address": address,
                    "city": city,
                    "state": state,
                    "postal_code": postal_code,
                    "blood_group": blood_group,
                    "supporting_doc_ref": supporting_doc,
                }
                ok, msg, res = register_citizen(payload, photo_bytes=photo_bytes, portal_password=pw_to_use, actor=actor)
                if ok and res:
                    st.success(msg)
                    info_msg = f"**Citizen Code:** `{res['citizen_code']}`  |  **Application ID:** `{res['application_id']}`  |  **Status:** `Pending`"
                    if res.get("portal_username"):
                        info_msg += f"  |  **Citizen Login Username:** `{res['portal_username']}`"
                    st.info(info_msg)
                else:
                    st.error(msg)

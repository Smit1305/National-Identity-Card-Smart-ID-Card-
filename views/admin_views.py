"""
Administrator Portal Views for Smart NIC – National Identity Card Management System
Implements all 12 administrative pages with full SQLite backend operations and RBAC checks.
"""

import os
import base64
from datetime import date, timedelta
from typing import Dict, Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from modules.database import get_all_settings, update_setting, log_audit
from modules.auth_service import list_users, create_user, toggle_user_active, reset_user_password
from modules.citizen_service import (
    list_citizens, get_citizen_by_id, update_citizen_profile,
    toggle_citizen_account_status, get_citizen_history
)
from modules.application_service import (
    list_applications, mark_under_review, approve_application, reject_application
)
from modules.card_service import (
    issue_card_for_citizen, list_cards, get_card_by_id, update_card_status,
    list_renewal_requests, process_renewal_request,
    list_replacement_requests, process_replacement_request
)
from modules.qr_service import generate_qr_image, build_qr_payload
from modules.card_renderer import (
    render_card_front, render_card_back, image_to_png_bytes, generate_card_pdf_bytes
)
from modules.report_service import (
    get_dashboard_metrics, get_report_dataframe, list_audit_logs,
    dataframe_to_csv_bytes, dataframe_to_pdf_bytes
)
from utils.helpers import render_metric_card, get_status_badge_html
from utils.chart_helpers import (
    create_monthly_registrations_chart, create_application_status_chart,
    create_card_status_chart, create_verification_results_chart
)
from views.public_views import render_top_header_bar


# =============================================================================
# 1. ADMIN DASHBOARD
# =============================================================================
def render_admin_dashboard(user: Dict[str, Any]):
    render_top_header_bar(
        "Admin Overview Dashboard",
        "Live National Identity Card metrics, registration analytics, and verification telemetry",
        user=user,
    )

    m = get_dashboard_metrics()

    # Row 1: Primary KPI Cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(render_metric_card("Registered Citizens", f"{m['total_citizens']:,}", f"{m['active_citizens']} active accounts", "👥", "blue"), unsafe_allow_html=True)
    with c2:
        st.markdown(render_metric_card("Active Smart NICs", f"{m['active_cards']:,}", f"Out of {m['total_cards']} issued cards", "🪪", "green"), unsafe_allow_html=True)
    with c3:
        st.markdown(render_metric_card("Pending Applications", f"{m['pending_apps']:,}", "Awaiting admin review", "⏳", "amber"), unsafe_allow_html=True)
    with c4:
        st.markdown(render_metric_card("Approved Applications", f"{m['approved_apps']:,}", f"{m['rejected_apps']} rejected", "✅", "purple"), unsafe_allow_html=True)

    st.write("")

    # Row 2: Secondary Lifecycle KPI Cards
    c5, c6, c7 = st.columns(3)
    with c5:
        st.markdown(render_metric_card("Expired Cards", f"{m['expired_cards']:,}", f"{m['revoked_cards']} revoked credentials", "⚠️", "rose"), unsafe_allow_html=True)
    with c6:
        st.markdown(render_metric_card("Renewal / Replacement", f"{m['pending_renewals'] + m['pending_replacements']:,}", f"{m['pending_renewals']} renewals • {m['pending_replacements']} lost/damaged", "🔄", "cyan"), unsafe_allow_html=True)
    with c7:
        st.markdown(render_metric_card("QR Verifications", f"{m['total_verifications']:,}", "Total logged credential checks", "📷", "blue"), unsafe_allow_html=True)

    st.write("")

    # Row 3: Charts (Monthly Registrations + Application Status)
    ch1, ch2 = st.columns([1.3, 1])
    with ch1:
        st.markdown('<div class="dashboard-panel-card">', unsafe_allow_html=True)
        st.plotly_chart(create_monthly_registrations_chart(m["monthly_df"]), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with ch2:
        st.markdown('<div class="dashboard-panel-card">', unsafe_allow_html=True)
        st.plotly_chart(create_application_status_chart(m["app_status_df"]), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # Row 4: Recent Registrations & Recent Verification Activity
    t1, t2 = st.columns(2)
    with t1:
        st.markdown(
            """
            <div class="dashboard-panel-card">
                <div class="panel-card-title">Recent Citizen Registrations</div>
                <div class="panel-card-subtitle">Latest citizen profiles stored in SQLite</div>
            """,
            unsafe_allow_html=True,
        )
        if m["recent_registrations"]:
            st.dataframe(pd.DataFrame(m["recent_registrations"]), use_container_width=True, hide_index=True, height=220)
        else:
            st.info("No citizens registered yet.")
        st.markdown("</div>", unsafe_allow_html=True)

    with t2:
        st.markdown(
            """
            <div class="dashboard-panel-card">
                <div class="panel-card-title">Recent Verification Activity</div>
                <div class="panel-card-subtitle">Live QR scans and manual credential lookups</div>
            """,
            unsafe_allow_html=True,
        )
        if m["recent_verifications"]:
            st.dataframe(pd.DataFrame(m["recent_verifications"]), use_container_width=True, hide_index=True, height=220)
        else:
            st.info("No verification activity recorded yet.")
        st.markdown("</div>", unsafe_allow_html=True)

    # Row 5: Quick Action Shortcuts
    st.markdown(
        """
        <div class="dashboard-panel-card" style="padding: 16px 22px;">
            <div class="panel-card-title">Quick Administrative Actions</div>
            <div class="panel-card-subtitle">Direct shortcuts to common identity workflows</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    q1, q2, q3, q4 = st.columns(4)
    with q1:
        if st.button("📝 Register Citizen", type="primary", use_container_width=True):
            st.session_state["nav_page"] = "Citizen Registration"
            st.rerun()
    with q2:
        if st.button("📋 Review Applications", use_container_width=True):
            st.session_state["nav_page"] = "Applications"
            st.rerun()
    with q3:
        if st.button("🪪 Generate Smart NIC", use_container_width=True):
            st.session_state["nav_page"] = "Smart NIC Generator"
            st.rerun()
    with q4:
        if st.button("📷 QR Verification", use_container_width=True):
            st.session_state["nav_page"] = "QR Verification"
            st.rerun()


# =============================================================================
# 3. CITIZEN MANAGEMENT
# =============================================================================
def render_citizen_management(user: Dict[str, Any]):
    render_top_header_bar(
        "Citizen Directory & Profile Management",
        "Search, filter, sort, edit citizen profiles, update photographs, and manage account status",
        user=user,
    )

    f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
    with f1:
        search = st.text_input("Search Citizens", placeholder="Name, Citizen Code, Email, Mobile, City...")
    with f2:
        status_f = st.selectbox("Account Status", ["ALL", "ACTIVE", "INACTIVE"])
    with f3:
        gender_f = st.selectbox("Gender", ["ALL", "Male", "Female", "Other"])
    with f4:
        sort_by = st.selectbox("Sort By", ["created_at", "full_name", "citizen_code", "city", "state"])

    citizens = list_citizens(search=search, status_filter=status_f, gender_filter=gender_f, sort_by=sort_by)

    st.markdown(f"#### Registered Citizens ({len(citizens)})")
    if not citizens:
        st.info("No citizens match the current search or filter criteria.")
        return

    df_c = pd.DataFrame(citizens)[["id", "citizen_code", "full_name", "date_of_birth", "gender", "email", "mobile_number", "city", "state", "account_status", "created_at"]]
    st.dataframe(df_c, use_container_width=True, hide_index=True, height=260)

    st.markdown("---")
    options = {f"{c['citizen_code']} — {c['full_name']} ({c['account_status']})": c["id"] for c in citizens}
    sel_label = st.selectbox("Select Citizen to View / Edit", list(options.keys()))
    cit_id = options[sel_label]
    cit = get_citizen_by_id(cit_id)
    if not cit:
        return

    tab_prof, tab_edit, tab_hist = st.tabs(["👤 Profile & Status", "✏️ Edit Information & Photo", "📜 Application & Card History"])

    with tab_prof:
        col_img, col_det = st.columns([1, 2.5])
        with col_img:
            if cit["photo_path"] and os.path.exists(cit["photo_path"]):
                st.image(cit["photo_path"], width=180, caption=cit["citizen_code"])
            else:
                st.info("No photograph uploaded.")

            st.write("")
            if cit["account_status"] == "ACTIVE":
                if st.button("🚫 Deactivate Citizen Account", use_container_width=True):
                    ok, msg = toggle_citizen_account_status(cit_id, "INACTIVE", user)
                    st.success(msg) if ok else st.error(msg)
                    st.rerun()
            else:
                if st.button("✅ Activate Citizen Account", type="primary", use_container_width=True):
                    ok, msg = toggle_citizen_account_status(cit_id, "ACTIVE", user)
                    st.success(msg) if ok else st.error(msg)
                    st.rerun()

        with col_det:
            st.markdown(
                f"""
                <div class="dashboard-panel-card">
                    <div class="panel-header-row">
                        <div>
                            <div class="panel-card-title">{cit['full_name']}</div>
                            <div class="panel-card-subtitle">{cit['citizen_code']} • Registered {cit['created_at']}</div>
                        </div>
                        {get_status_badge_html(cit['account_status'])}
                    </div>
                    <div class="inner-session-box">
                        <div><div class="session-meta-label">DATE OF BIRTH</div><div class="session-meta-value">{cit['date_of_birth']}</div></div>
                        <div><div class="session-meta-label">GENDER</div><div class="session-meta-value">{cit['gender']}</div></div>
                        <div><div class="session-meta-label">BLOOD GROUP</div><div class="session-meta-value">{cit['blood_group']}</div></div>
                        <div><div class="session-meta-label">MOBILE</div><div class="session-meta-value">{cit['mobile_number']}</div></div>
                    </div>
                    <div><b>Email:</b> {cit['email']}</div>
                    <div style="margin-top: 6px;"><b>Address:</b> {cit['residential_address']}, {cit['city']}, {cit['state']} - {cit['postal_code']}</div>
                    <div style="margin-top: 6px;"><b>Supporting Document Ref:</b> <code>{cit['supporting_doc_ref'] or 'None'}</code></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with tab_edit:
        with st.form(f"edit_citizen_{cit_id}"):
            e1, e2, e3 = st.columns(3)
            with e1:
                new_name = st.text_input("Full Name", value=cit["full_name"])
            with e2:
                new_dob = st.text_input("Date of Birth (YYYY-MM-DD)", value=cit["date_of_birth"])
            with e3:
                g_opts = ["Male", "Female", "Other"]
                new_gender = st.selectbox("Gender", g_opts, index=g_opts.index(cit["gender"]) if cit["gender"] in g_opts else 0)

            e4, e5, e6 = st.columns(3)
            with e4:
                new_email = st.text_input("Email", value=cit["email"])
            with e5:
                new_mobile = st.text_input("Mobile", value=cit["mobile_number"])
            with e6:
                new_blood = st.text_input("Blood Group", value=cit["blood_group"])

            new_addr = st.text_input("Residential Address", value=cit["residential_address"])
            e7, e8, e9 = st.columns(3)
            with e7:
                new_city = st.text_input("City", value=cit["city"])
            with e8:
                new_state = st.text_input("State", value=cit["state"])
            with e9:
                new_postal = st.text_input("Postal Code", value=cit["postal_code"])

            new_doc = st.text_input("Supporting Document Reference", value=cit["supporting_doc_ref"] or "")
            new_photo = st.file_uploader("Replace Citizen Photograph (Optional)", type=["jpg", "jpeg", "png", "webp"], key=f"upd_photo_{cit_id}")

            if st.form_submit_button("💾 Save Citizen Changes", type="primary", use_container_width=True):
                ok, msg = update_citizen_profile(
                    cit_id,
                    {
                        "full_name": new_name, "date_of_birth": new_dob, "gender": new_gender,
                        "email": new_email, "mobile_number": new_mobile, "blood_group": new_blood,
                        "residential_address": new_addr, "city": new_city, "state": new_state,
                        "postal_code": new_postal, "supporting_doc_ref": new_doc,
                    },
                    photo_bytes=new_photo.getvalue() if new_photo else None,
                    actor=user,
                    citizen_self_service=False,
                )
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    with tab_hist:
        hist = get_citizen_history(cit_id)
        st.markdown("##### Application History")
        if hist["applications"]:
            st.dataframe(pd.DataFrame(hist["applications"])[["application_id", "status", "rejection_reason", "submitted_at", "reviewed_at"]], use_container_width=True, hide_index=True)
        else:
            st.info("No applications recorded.")

        st.markdown("##### Issued Smart NIC Cards")
        if hist["cards"]:
            st.dataframe(pd.DataFrame(hist["cards"])[["nic_number", "issue_date", "expiry_date", "status", "revocation_reason", "created_at"]], use_container_width=True, hide_index=True)
        else:
            st.info("No identity cards issued yet.")


# =============================================================================
# 4. APPLICATION MANAGEMENT
# =============================================================================
def render_application_management(user: Dict[str, Any]):
    render_top_header_bar(
        "Application Review & Approval Queue",
        "Review submitted citizen applications, approve and issue Smart NIC cards, or reject with reasons",
        user=user,
    )

    f1, f2 = st.columns([1, 2])
    with f1:
        st_filter = st.selectbox("Filter by Status", ["ALL", "Pending", "Under Review", "Approved", "Rejected"])
    with f2:
        q = st.text_input("Search Applications", placeholder="Application ID, Citizen Name, Email...")

    apps = list_applications(status_filter=st_filter, search=q)
    st.markdown(f"#### Applications ({len(apps)})")
    if not apps:
        st.info("No applications found for the selected filter.")
        return

    df_a = pd.DataFrame(apps)[["application_id", "full_name", "citizen_code", "city", "status", "issued_nic_number", "submitted_at"]]
    st.dataframe(df_a, use_container_width=True, hide_index=True, height=250)

    st.markdown("---")
    app_map = {f"{a['application_id']} — {a['full_name']} [{a['status']}]": a for a in apps}
    sel_app = app_map[st.selectbox("Select Application to Review", list(app_map.keys()))]

    col_info, col_act = st.columns([1.4, 1])
    with col_info:
        st.markdown(
            f"""
            <div class="dashboard-panel-card">
                <div class="panel-header-row">
                    <div>
                        <div class="panel-card-title">{sel_app['application_id']} — {sel_app['full_name']}</div>
                        <div class="panel-card-subtitle">Submitted: {sel_app['submitted_at']} • Citizen: {sel_app['citizen_code']}</div>
                    </div>
                    {get_status_badge_html(sel_app['status'])}
                </div>
                <div class="inner-session-box">
                    <div><div class="session-meta-label">DOB / GENDER</div><div class="session-meta-value">{sel_app['date_of_birth']} ({sel_app['gender']})</div></div>
                    <div><div class="session-meta-label">CONTACT</div><div class="session-meta-value">{sel_app['mobile_number']}</div></div>
                    <div><div class="session-meta-label">ISSUED NIC</div><div class="session-meta-value-blue">{sel_app['issued_nic_number'] or 'Not Issued Yet'}</div></div>
                </div>
                <div><b>Email:</b> {sel_app['email']}</div>
                <div style="margin-top: 4px;"><b>Address:</b> {sel_app['residential_address']}, {sel_app['city']}, {sel_app['state']} - {sel_app['postal_code']}</div>
                <div style="margin-top: 4px;"><b>Supporting Ref:</b> <code>{sel_app['supporting_doc_ref'] or 'None'}</code></div>
                {"<div style='margin-top: 8px; color: #DC2626;'><b>Rejection Reason:</b> " + sel_app['rejection_reason'] + "</div>" if sel_app.get('rejection_reason') else ""}
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_act:
        st.markdown('<div class="dashboard-panel-card"><div class="panel-card-title">Administrator Decision</div>', unsafe_allow_html=True)
        if sel_app["status"] in ("Pending", "Under Review"):
            notes = st.text_input("Reviewer Notes (Optional)", key=f"notes_{sel_app['id']}")
            issue_now = st.checkbox("Issue Smart NIC immediately upon approval", value=True, key=f"issue_now_{sel_app['id']}")

            b1, b2 = st.columns(2)
            with b1:
                if st.button("🔎 Mark Under Review", use_container_width=True, disabled=sel_app["status"] == "Under Review"):
                    ok, msg = mark_under_review(sel_app["id"], user, notes=notes)
                    st.success(msg) if ok else st.error(msg)
                    st.rerun()
            with b2:
                if st.button("✅ Approve Application", type="primary", use_container_width=True):
                    ok, msg, _ = approve_application(sel_app["id"], user, issue_card_immediately=issue_now, notes=notes)
                    st.success(msg) if ok else st.error(msg)
                    st.rerun()

            st.markdown("---")
            rej_reason = st.text_area("Rejection Reason (Required to Reject)", placeholder="Explain why this application cannot be approved...", key=f"rej_{sel_app['id']}")
            if st.button("❌ Reject Application", use_container_width=True):
                ok, msg = reject_application(sel_app["id"], rej_reason, user)
                if ok:
                    st.warning(msg)
                    st.rerun()
                else:
                    st.error(msg)

        elif sel_app["status"] == "Approved" and not sel_app.get("issued_nic_number"):
            st.info("Application is Approved. You can issue the Smart NIC credential below:")
            if st.button("🪪 Issue Smart NIC Now", type="primary", use_container_width=True):
                ok, msg, _ = issue_card_for_citizen(sel_app["citizen_id"], user, application_id=sel_app["id"])
                st.success(msg) if ok else st.error(msg)
                st.rerun()
        else:
            st.info(f"Application has reached final status: **{sel_app['status']}**.")
        st.markdown("</div>", unsafe_allow_html=True)


# =============================================================================
# 5. SMART NIC CARD GENERATOR
# =============================================================================
def render_smart_nic_generator(user: Dict[str, Any]):
    render_top_header_bar(
        "Smart NIC Digital Card Generator",
        "Generate high-resolution Front & Back National Identity Cards with cryptographic QR codes, print preview, and PDF export",
        user=user,
    )

    # Optional: Issue a fresh card for an approved citizen
    with st.expander("➕ Issue New Smart NIC for an Approved Citizen", expanded=False):
        approved_apps = list_applications(status_filter="Approved")
        if approved_apps:
            c_map = {f"{a['citizen_code']} — {a['full_name']} ({a['application_id']})": a for a in approved_apps}
            chosen = c_map[st.selectbox("Select Approved Citizen", list(c_map.keys()))]
            val_yrs = st.number_input("Validity Period (Years)", min_value=1, max_value=15, value=5)
            if st.button("🪪 Generate & Issue Smart NIC", type="primary"):
                ok, msg, _ = issue_card_for_citizen(chosen["citizen_id"], user, application_id=chosen["id"], validity_years=int(val_yrs))
                st.success(msg) if ok else st.error(msg)
                st.rerun()
        else:
            st.info("No approved applications found yet. Approve an application first.")

    cards = list_cards()
    if not cards:
        st.warning("No issued Smart NIC cards available yet.")
        return

    card_map = {f"{c['nic_number']} — {c['full_name']} [{c['status']}]": c["id"] for c in cards}
    selected_id = card_map[st.selectbox("Select Issued Smart NIC to Preview & Export", list(card_map.keys()))]
    card = get_card_by_id(selected_id)
    if not card:
        return

    front_img = render_card_front(card)
    back_img = render_card_back(card)
    front_bytes = image_to_png_bytes(front_img)
    back_bytes = image_to_png_bytes(back_img)
    pdf_bytes = generate_card_pdf_bytes(card)
    qr_bytes = image_to_png_bytes(generate_qr_image(card["verification_token"], card["token_signature"]))

    col_f, col_b = st.columns(2)
    with col_f:
        st.markdown('<div class="dashboard-panel-card"><div class="panel-card-title">Card Front Preview</div><div class="panel-card-subtitle">ISO/IEC 7810 ID-1 proportional layout with signed QR</div>', unsafe_allow_html=True)
        st.image(front_img, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col_b:
        st.markdown('<div class="dashboard-panel-card"><div class="panel-card-title">Card Back Preview</div><div class="panel-card-subtitle">Residential address, card status & prototype disclaimer</div>', unsafe_allow_html=True)
        st.image(back_img, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # Export & Print Controls
    d1, d2, d3, d4 = st.columns(4)
    with d1:
        st.download_button("📄 Download PDF Card", data=pdf_bytes, file_name=f"{card['nic_number']}.pdf", mime="application/pdf", type="primary", use_container_width=True)
    with d2:
        st.download_button("🖼️ Download Front PNG", data=front_bytes, file_name=f"{card['nic_number']}_front.png", mime="image/png", use_container_width=True)
    with d3:
        st.download_button("🖼️ Download Back PNG", data=back_bytes, file_name=f"{card['nic_number']}_back.png", mime="image/png", use_container_width=True)
    with d4:
        st.download_button("📷 Download QR PNG", data=qr_bytes, file_name=f"{card['nic_number']}_qr.png", mime="image/png", use_container_width=True)

    # Browser Print Functionality
    b64_front = base64.b64encode(front_bytes).decode("ascii")
    b64_back = base64.b64encode(back_bytes).decode("ascii")
    components.html(
        f"""
        <div style="text-align: right; margin-top: 4px;">
            <button onclick="
                var w = window.open('', '_blank', 'width=900,height=700');
                w.document.write('<html><head><title>Print Smart NIC - {card['nic_number']}</title></head><body style=\\'text-align:center;font-family:sans-serif;\\'>');
                w.document.write('<h3>Smart NIC Digital Credential ({card['nic_number']})</h3>');
                w.document.write('<img src=\\'data:image/png;base64,{b64_front}\\' style=\\'width:85%;max-width:640px;margin:10px;border:1px solid #ccc;border-radius:10px;\\'/><br/>');
                w.document.write('<img src=\\'data:image/png;base64,{b64_back}\\' style=\\'width:85%;max-width:640px;margin:10px;border:1px solid #ccc;border-radius:10px;\\'/>');
                w.document.write('<script>window.onload=function(){{window.print();}}</script></body></html>');
                w.document.close();
            " style="background:#0F172A;color:#FFFFFF;border:none;padding:9px 18px;border-radius:8px;font-weight:700;cursor:pointer;font-family:sans-serif;">
                🖨️ Open Print-Ready Card Sheet
            </button>
        </div>
        """,
        height=52,
    )

    with st.expander("🔐 Signed QR Verification Payload (Admin Diagnostic View)"):
        payload = build_qr_payload(card["verification_token"], card["token_signature"])
        st.code(payload, language="text")
        st.caption("Only this opaque cryptographically signed credential is encoded in the QR code — zero personal contact or address data is stored in the QR.")


# =============================================================================
# 6. CARD MANAGEMENT
# =============================================================================
def render_card_management(user: Dict[str, Any]):
    render_top_header_bar(
        "Issued Smart NIC Card Management",
        "Search issued cards, track expiry dates, activate/deactivate, or permanently revoke compromised credentials",
        user=user,
    )

    f1, f2 = st.columns([2, 1])
    with f1:
        search = st.text_input("Search Cards", placeholder="NIC Number, Citizen Name, City...")
    with f2:
        st_f = st.selectbox("Filter by Card Status", ["ALL", "ACTIVE", "INACTIVE", "EXPIRED", "REVOKED"])

    cards = list_cards(search=search, status_filter=st_f)
    st.markdown(f"#### Issued Cards ({len(cards)})")
    if not cards:
        st.info("No identity cards match your filter.")
        return

    df_cards = pd.DataFrame(cards)[["nic_number", "full_name", "citizen_code", "issue_date", "expiry_date", "status", "revocation_reason"]]
    st.dataframe(df_cards, use_container_width=True, hide_index=True, height=260)

    st.markdown("---")
    c_map = {f"{c['nic_number']} — {c['full_name']} [{c['status']}]": c["id"] for c in cards}
    sel_card_id = c_map[st.selectbox("Select Card to Manage", list(c_map.keys()))]
    card = get_card_by_id(sel_card_id)
    if not card:
        return

    c_left, c_right = st.columns([1.3, 1])
    with c_left:
        st.markdown(
            f"""
            <div class="dashboard-panel-card">
                <div class="panel-header-row">
                    <div>
                        <div class="panel-card-title">{card['nic_number']}</div>
                        <div class="panel-card-subtitle">Holder: {card['full_name']} ({card['citizen_code']})</div>
                    </div>
                    {get_status_badge_html(card['status'])}
                </div>
                <div class="inner-session-box">
                    <div><div class="session-meta-label">ISSUE DATE</div><div class="session-meta-value">{card['issue_date']}</div></div>
                    <div><div class="session-meta-label">EXPIRY DATE</div><div class="session-meta-value">{card['expiry_date']}</div></div>
                    <div><div class="session-meta-label">ISSUED AT</div><div class="session-meta-value">{card['created_at']}</div></div>
                </div>
                {"<div style='color:#DC2626;font-size:0.86rem;'><b>Revocation Reason:</b> " + card['revocation_reason'] + f" ({card['revoked_at']})</div>" if card.get('revocation_reason') else ""}
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c_right:
        st.markdown('<div class="dashboard-panel-card"><div class="panel-card-title">Lifecycle Controls</div>', unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("✅ Activate Card", type="primary", use_container_width=True, disabled=card["status"] in ("ACTIVE", "REVOKED", "EXPIRED")):
                ok, msg = update_card_status(card["id"], "ACTIVE", user)
                st.success(msg) if ok else st.error(msg)
                st.rerun()
        with b2:
            if st.button("⏸️ Deactivate Card", use_container_width=True, disabled=card["status"] != "ACTIVE"):
                ok, msg = update_card_status(card["id"], "INACTIVE", user)
                st.warning(msg) if ok else st.error(msg)
                st.rerun()

        st.markdown("---")
        rev_reason = st.text_input("Revocation Reason", placeholder="e.g. Reported lost / compromised credential", key=f"rev_r_{card['id']}")
        confirm_rev = st.checkbox("Confirm permanent revocation (cannot be undone)", key=f"conf_rev_{card['id']}")
        if st.button("🚫 Permanently Revoke Card", use_container_width=True, disabled=card["status"] == "REVOKED"):
            if not confirm_rev:
                st.error("Please check the confirmation box before revoking a credential.")
            elif len(rev_reason.strip()) < 4:
                st.error("Please enter a revocation reason.")
            else:
                ok, msg = update_card_status(card["id"], "REVOKED", user, reason=rev_reason)
                st.warning(msg) if ok else st.error(msg)
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# =============================================================================
# 8. RENEWAL & REPLACEMENT (ADMIN)
# =============================================================================
def render_renewal_replacement_admin(user: Dict[str, Any]):
    render_top_header_bar(
        "Card Renewal & Replacement Management",
        "Review renewal, lost-card, and damaged-card requests; revoke old credentials and issue replacements",
        user=user,
    )

    tab_ren, tab_rep = st.tabs(["🔄 Renewal Requests", "🆘 Lost / Damaged Replacement Requests"])

    with tab_ren:
        f_ren = st.selectbox("Filter Renewals", ["ALL", "Pending", "Approved", "Rejected"], key="f_ren_adm")
        reqs = list_renewal_requests(status_filter=f_ren)
        if not reqs:
            st.info("No renewal requests found.")
        else:
            st.dataframe(pd.DataFrame(reqs)[["request_code", "full_name", "nic_number", "expiry_date", "reason", "status", "new_nic_number", "created_at"]], use_container_width=True, hide_index=True)
            pending_r = [r for r in reqs if r["status"] == "Pending"]
            if pending_r:
                st.markdown("##### Process Pending Renewal Request")
                rmap = {f"{r['request_code']} — {r['full_name']} ({r['nic_number']})": r for r in pending_r}
                sel_r = rmap[st.selectbox("Select Pending Renewal", list(rmap.keys()))]
                notes = st.text_input("Admin Notes", value="Renewal verified and approved", key=f"ren_notes_{sel_r['id']}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Approve & Issue Renewed Smart NIC", type="primary", use_container_width=True):
                        ok, msg = process_renewal_request(sel_r["id"], True, notes, user)
                        st.success(msg) if ok else st.error(msg)
                        st.rerun()
                with c2:
                    if st.button("❌ Reject Renewal", use_container_width=True):
                        ok, msg = process_renewal_request(sel_r["id"], False, notes, user)
                        st.warning(msg) if ok else st.error(msg)
                        st.rerun()

    with tab_rep:
        f_rep = st.selectbox("Filter Replacements", ["ALL", "Pending", "Approved", "Rejected"], key="f_rep_adm")
        reps = list_replacement_requests(status_filter=f_rep)
        if not reps:
            st.info("No replacement requests found.")
        else:
            st.dataframe(pd.DataFrame(reps)[["request_code", "full_name", "nic_number", "request_type", "incident_details", "status", "new_nic_number", "created_at"]], use_container_width=True, hide_index=True)
            pending_p = [r for r in reps if r["status"] == "Pending"]
            if pending_p:
                st.markdown("##### Process Pending Lost/Damaged Replacement")
                pmap = {f"{r['request_code']} [{r['request_type']}] — {r['full_name']} ({r['nic_number']})": r for r in pending_p}
                sel_p = pmap[st.selectbox("Select Pending Replacement", list(pmap.keys()))]
                p_notes = st.text_input("Admin Notes", value="Previous credential revoked; replacement issued", key=f"rep_notes_{sel_p['id']}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Approve, Revoke Old & Issue Replacement", type="primary", use_container_width=True):
                        ok, msg = process_replacement_request(sel_p["id"], True, p_notes, user)
                        st.success(msg) if ok else st.error(msg)
                        st.rerun()
                with c2:
                    if st.button("❌ Reject Replacement", use_container_width=True):
                        ok, msg = process_replacement_request(sel_p["id"], False, p_notes, user)
                        st.warning(msg) if ok else st.error(msg)
                        st.rerun()


# =============================================================================
# 9. REPORTS & ANALYTICS
# =============================================================================
def render_reports_analytics(user: Dict[str, Any]):
    render_top_header_bar(
        "Reports & Operational Analytics",
        "Generate date-filtered citizen, card, application, and QR verification reports with CSV and PDF export",
        user=user,
    )

    m = get_dashboard_metrics()
    g1, g2 = st.columns(2)
    with g1:
        st.markdown('<div class="dashboard-panel-card">', unsafe_allow_html=True)
        st.plotly_chart(create_card_status_chart(m["card_status_df"]), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with g2:
        st.markdown('<div class="dashboard-panel-card">', unsafe_allow_html=True)
        st.plotly_chart(create_verification_results_chart(m["verif_df"]), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    report_choices = {
        "Citizen Registration Report": "citizens",
        "Issued Smart NIC Cards Report": "issued_cards",
        "Pending Applications Report": "pending_applications",
        "Expired Cards Report": "expired_cards",
        "Rejected Applications Report": "rejected_applications",
        "QR Verification History Report": "qr_verifications",
    }

    r1, r2, r3 = st.columns([2, 1, 1])
    with r1:
        sel_rep_name = st.selectbox("Select Report Category", list(report_choices.keys()))
    with r2:
        start_d = st.date_input("Start Date", value=date.today() - timedelta(days=365))
    with r3:
        end_d = st.date_input("End Date", value=date.today())

    rep_key = report_choices[sel_rep_name]
    df_rep = get_report_dataframe(rep_key, start_date=start_d.strftime("%Y-%m-%d"), end_date=end_d.strftime("%Y-%m-%d"))

    st.markdown(f"#### {sel_rep_name} ({len(df_rep)} records)")
    if df_rep.empty:
        st.info("No records matched the selected date range.")
    else:
        st.dataframe(df_rep, use_container_width=True, hide_index=True, height=320)

    e1, e2 = st.columns(2)
    with e1:
        st.download_button(
            "📥 Export Report as CSV",
            data=dataframe_to_csv_bytes(df_rep),
            file_name=f"smart_nic_{rep_key}.csv",
            mime="text/csv",
            disabled=df_rep.empty,
            use_container_width=True,
        )
    with e2:
        pdf_rep = dataframe_to_pdf_bytes(sel_rep_name, df_rep, subtitle=f"Period: {start_d} to {end_d}")
        st.download_button(
            "📄 Export Report as PDF",
            data=pdf_rep,
            file_name=f"smart_nic_{rep_key}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )


# =============================================================================
# 10. AUDIT LOGS
# =============================================================================
def render_audit_logs(user: Dict[str, Any]):
    render_top_header_bar(
        "Security & System Audit Logs",
        "Immutable chronological record of authentication, registrations, approvals, card issuances, and revocations",
        user=user,
    )

    c1, c2 = st.columns([1, 2])
    with c1:
        action_f = st.selectbox(
            "Filter by Event Type",
            [
                "ALL", "LOGIN_SUCCESS", "LOGIN_FAILED", "CITIZEN_REGISTERED", "CITIZEN_UPDATED",
                "APPLICATION_APPROVED", "APPLICATION_REJECTED", "CARD_ISSUED", "CARD_REVOKED",
                "RENEWAL_APPROVED", "REPLACEMENT_APPROVED", "USER_CREATED", "SETTINGS_UPDATED"
            ],
        )
    with c2:
        q = st.text_input("Search Audit Trail", placeholder="Username, Entity ID, Details...")

    logs = list_audit_logs(action_filter=action_f, search=q, limit=250)
    if logs:
        df_l = pd.DataFrame(logs)[["id", "created_at", "username", "role", "action", "entity_type", "entity_id", "details"]]
        st.dataframe(df_l, use_container_width=True, hide_index=True, height=440)
        st.download_button("📥 Download Audit Logs (CSV)", data=dataframe_to_csv_bytes(df_l), file_name="smart_nic_audit_logs.csv", mime="text/csv")
    else:
        st.info("No audit log entries match your filter.")


# =============================================================================
# 11. USER MANAGEMENT
# =============================================================================
def render_user_management(user: Dict[str, Any]):
    render_top_header_bar(
        "User & Role Management (RBAC)",
        "Manage Administrator and Citizen portal accounts with bcrypt password security",
        user=user,
    )

    with st.expander("➕ Create New Administrator or Citizen Account"):
        with st.form("create_user_form"):
            u1, u2, u3 = st.columns(3)
            with u1:
                uname = st.text_input("Username *")
            with u2:
                uemail = st.text_input("Email *")
            with u3:
                urole = st.selectbox("Role *", ["admin", "citizen"])
            u4, u5 = st.columns(2)
            with u4:
                ufull = st.text_input("Full Name *")
            with u5:
                upass = st.text_input("Initial Password (min 6 chars) *", type="password")
            if st.form_submit_button("Create Account", type="primary"):
                ok, msg, _ = create_user(uname, uemail, ufull, upass, role=urole, actor=user)
                st.success(msg) if ok else st.error(msg)
                if ok:
                    st.rerun()

    users = list_users()
    st.markdown(f"#### System Accounts ({len(users)})")
    df_u = pd.DataFrame(users)[["id", "username", "full_name", "email", "role", "is_active", "last_login", "created_at"]]
    st.dataframe(df_u, use_container_width=True, hide_index=True, height=280)

    st.markdown("---")
    umap = {f"{u['username']} ({u['role']}) — {'Active' if u['is_active'] else 'Inactive'}": u for u in users}
    sel_u = umap[st.selectbox("Select Account to Manage", list(umap.keys()))]

    a1, a2 = st.columns(2)
    with a1:
        if sel_u["is_active"]:
            if st.button("🚫 Deactivate Account", use_container_width=True):
                ok, msg = toggle_user_active(sel_u["id"], False, user)
                st.warning(msg) if ok else st.error(msg)
                st.rerun()
        else:
            if st.button("✅ Activate Account", type="primary", use_container_width=True):
                ok, msg = toggle_user_active(sel_u["id"], True, user)
                st.success(msg) if ok else st.error(msg)
                st.rerun()
    with a2:
        new_pw = st.text_input("Reset Password (min 6 chars)", type="password", key=f"rst_pw_{sel_u['id']}")
        if st.button("🔑 Reset Password", use_container_width=True):
            ok, msg = reset_user_password(sel_u["id"], new_pw, user)
            st.success(msg) if ok else st.error(msg)


# =============================================================================
# 12. SYSTEM SETTINGS
# =============================================================================
def render_settings(user: Dict[str, Any]):
    render_top_header_bar(
        "System Configuration & Security Settings",
        "Configure card validity rules, prototype disclaimers, lockout thresholds, and QR verification limits",
        user=user,
    )

    settings = get_all_settings()
    with st.form("system_settings_form"):
        updated_vals = {}
        for s in settings:
            updated_vals[s["key"]] = st.text_input(
                f"{s['key']}",
                value=s["value"],
                help=s["description"],
            )
        if st.form_submit_button("💾 Save System Settings", type="primary", use_container_width=True):
            for k, v in updated_vals.items():
                update_setting(k, v.strip())
            log_audit("SETTINGS_UPDATED", "system_settings", "global", "Updated system settings", user["id"], user["username"], user["role"])
            st.success("System settings saved successfully!")
            st.rerun()

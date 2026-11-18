"""
Citizen Self-Service Portal Views (Module 9)
Enforces strict citizen data isolation: citizens can ONLY view and manage their own records.
"""

import os
from datetime import datetime, date
from typing import Dict, Any

import pandas as pd
import streamlit as st

from modules.citizen_service import get_citizen_by_id, get_citizen_history, update_citizen_profile
from modules.card_service import (
    list_cards, submit_renewal_request, submit_replacement_request,
    list_renewal_requests, list_replacement_requests
)
from modules.card_renderer import (
    render_card_front, render_card_back, image_to_png_bytes, generate_card_pdf_bytes
)
from modules.qr_service import generate_qr_image, list_verifications
from utils.helpers import render_metric_card, get_status_badge_html
from views.public_views import render_top_header_bar


def _get_own_citizen(user: Dict[str, Any]):
    cid = user.get("citizen_id")
    if not cid:
        st.warning("This citizen account is not yet linked to a citizen identity profile.")
        return None
    cit = get_citizen_by_id(cid)
    if not cit:
        st.error("Linked citizen profile could not be found.")
        return None
    return cit


# =============================================================================
# 1. CITIZEN DASHBOARD
# =============================================================================
def render_citizen_dashboard(user: Dict[str, Any]):
    render_top_header_bar(
        "My Identity Dashboard",
        "View your Smart NIC status, application progress, expiry countdown, and recent activity",
        user=user,
    )
    cit = _get_own_citizen(user)
    if not cit:
        return

    hist = get_citizen_history(cit["id"])
    cards = list_cards(citizen_id=cit["id"])
    verifs = list_verifications(limit=50, citizen_id=cit["id"])

    latest_app = hist["applications"][0] if hist["applications"] else None
    active_card = next((c for c in cards if c["status"] == "ACTIVE"), cards[0] if cards else None)

    app_status = latest_app["status"] if latest_app else "Not Submitted"
    nic_display = active_card["nic_number"] if active_card else "Not Issued"
    card_status = active_card["status"] if active_card else "None"
    expiry_display = active_card["expiry_date"] if active_card else "—"

    days_sub = "No card issued"
    if active_card:
        try:
            exp_dt = datetime.strptime(active_card["expiry_date"], "%Y-%m-%d").date()
            delta = (exp_dt - date.today()).days
            days_sub = f"{delta} days remaining" if delta >= 0 else f"Expired {-delta} days ago"
        except ValueError:
            days_sub = card_status

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(render_metric_card("Application Status", app_status, latest_app["application_id"] if latest_app else "—", "📋", "blue"), unsafe_allow_html=True)
    with k2:
        st.markdown(render_metric_card("Card Status", card_status, nic_display, "🪪", "green" if card_status == "ACTIVE" else "amber"), unsafe_allow_html=True)
    with k3:
        st.markdown(render_metric_card("Card Expiry Date", expiry_display, days_sub, "📅", "purple"), unsafe_allow_html=True)
    with k4:
        st.markdown(render_metric_card("QR Verifications", f"{len(verifs)}", "Checks on your Smart NIC", "📷", "cyan"), unsafe_allow_html=True)

    st.write("")

    c_left, c_right = st.columns([1.2, 1])
    with c_left:
        st.markdown(
            f"""
            <div class="dashboard-panel-card">
                <div class="panel-header-row">
                    <div>
                        <div class="panel-card-title">{cit['full_name']}</div>
                        <div class="panel-card-subtitle">Citizen Code: {cit['citizen_code']}</div>
                    </div>
                    {get_status_badge_html(cit['account_status'])}
                </div>
                <div class="inner-session-box">
                    <div><div class="session-meta-label">DATE OF BIRTH</div><div class="session-meta-value">{cit['date_of_birth']}</div></div>
                    <div><div class="session-meta-label">GENDER</div><div class="session-meta-value">{cit['gender']}</div></div>
                    <div><div class="session-meta-label">BLOOD GROUP</div><div class="session-meta-value">{cit['blood_group']}</div></div>
                </div>
                <div><b>Email:</b> {cit['email']} &nbsp;|&nbsp; <b>Mobile:</b> {cit['mobile_number']}</div>
                <div style="margin-top: 6px;"><b>Address:</b> {cit['residential_address']}, {cit['city']}, {cit['state']} - {cit['postal_code']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c_right:
        st.markdown(
            """
            <div class="dashboard-panel-card">
                <div class="panel-card-title">Application Tracker</div>
                <div class="panel-card-subtitle">Status of your Smart NIC applications</div>
            """,
            unsafe_allow_html=True,
        )
        if hist["applications"]:
            st.dataframe(pd.DataFrame(hist["applications"])[["application_id", "status", "rejection_reason", "submitted_at"]], use_container_width=True, hide_index=True, height=175)
        else:
            st.info("No applications submitted.")
        st.markdown("</div>", unsafe_allow_html=True)

    q1, q2, q3 = st.columns(3)
    with q1:
        if st.button("🪪 View & Download My Smart NIC", type="primary", use_container_width=True):
            st.session_state["nav_page"] = "My Smart NIC"
            st.rerun()
    with q2:
        if st.button("🔄 Request Renewal / Report Lost", use_container_width=True):
            st.session_state["nav_page"] = "Renewal & Replacement"
            st.rerun()
    with q3:
        if st.button("👤 Update Contact / Address", use_container_width=True):
            st.session_state["nav_page"] = "My Profile"
            st.rerun()


# =============================================================================
# 2. MY SMART NIC (VIEW & DOWNLOAD DIGITAL CARD)
# =============================================================================
def render_citizen_smart_nic(user: Dict[str, Any]):
    render_top_header_bar(
        "My Digital Smart NIC",
        "Preview and download your issued Smart National Identity Card (Front, Back & PDF)",
        user=user,
    )
    cit = _get_own_citizen(user)
    if not cit:
        return

    cards = list_cards(citizen_id=cit["id"])
    if not cards:
        st.info("No Smart NIC has been issued for your account yet. Once an administrator approves your application, your digital card will appear here.")
        return

    cmap = {f"{c['nic_number']} [{c['status']}] — Issued {c['issue_date']}": c for c in cards}
    card = cmap[st.selectbox("Select Your Issued Card", list(cmap.keys()))]

    front_img = render_card_front(card)
    back_img = render_card_back(card)
    pdf_bytes = generate_card_pdf_bytes(card)
    qr_bytes = image_to_png_bytes(generate_qr_image(card["verification_token"], card["token_signature"]))

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="dashboard-panel-card"><div class="panel-card-title">Card Front</div>', unsafe_allow_html=True)
        st.image(front_img, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="dashboard-panel-card"><div class="panel-card-title">Card Back</div>', unsafe_allow_html=True)
        st.image(back_img, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button("📄 Download Digital Smart NIC (PDF)", data=pdf_bytes, file_name=f"{card['nic_number']}.pdf", mime="application/pdf", type="primary", use_container_width=True)
    with d2:
        st.download_button("🖼️ Download Card Front (PNG)", data=image_to_png_bytes(front_img), file_name=f"{card['nic_number']}_front.png", mime="image/png", use_container_width=True)
    with d3:
        st.download_button("📷 Download Verification QR (PNG)", data=qr_bytes, file_name=f"{card['nic_number']}_qr.png", mime="image/png", use_container_width=True)

    if len(cards) > 1:
        st.markdown("#### Historical Smart NIC Records")
        st.dataframe(pd.DataFrame(cards)[["nic_number", "issue_date", "expiry_date", "status", "revocation_reason"]], use_container_width=True, hide_index=True)


# =============================================================================
# 3. CITIZEN RENEWAL & LOST/DAMAGED REPLACEMENT
# =============================================================================
def render_citizen_renewal_replacement(user: Dict[str, Any]):
    render_top_header_bar(
        "Card Renewal & Lost/Damaged Replacement",
        "Submit renewal requests or report lost/damaged Smart NIC credentials for revocation and replacement",
        user=user,
    )
    cit = _get_own_citizen(user)
    if not cit:
        return

    cards = list_cards(citizen_id=cit["id"])
    if not cards:
        st.info("You do not have an issued Smart NIC eligible for renewal or replacement.")
        return

    tab_ren, tab_rep = st.tabs(["🔄 Request Card Renewal", "🆘 Report Lost / Damaged Card"])

    with tab_ren:
        with st.form("citizen_renewal_form"):
            cmap = {f"{c['nic_number']} [{c['status']} | Expires {c['expiry_date']}]": c["id"] for c in cards}
            sel_card_id = cmap[st.selectbox("Select Card to Renew", list(cmap.keys()))]
            reason = st.text_area("Reason for Renewal *", placeholder="e.g. Card approaching expiry / updating photograph")
            if st.form_submit_button("Submit Renewal Request", type="primary", use_container_width=True):
                ok, msg, _ = submit_renewal_request(cit["id"], sel_card_id, reason, user)
                st.success(msg) if ok else st.error(msg)
                if ok:
                    st.rerun()

        st.markdown("#### My Renewal Requests")
        my_rens = list_renewal_requests(citizen_id=cit["id"])
        if my_rens:
            st.dataframe(pd.DataFrame(my_rens)[["request_code", "nic_number", "reason", "status", "admin_notes", "new_nic_number", "created_at"]], use_container_width=True, hide_index=True)
        else:
            st.info("No renewal requests submitted.")

    with tab_rep:
        with st.form("citizen_replacement_form"):
            cmap2 = {f"{c['nic_number']} [{c['status']}]": c["id"] for c in cards}
            sel_card_id2 = cmap2[st.selectbox("Select Lost or Damaged Card", list(cmap2.keys()))]
            req_type = st.selectbox("Incident Type *", ["LOST", "DAMAGED"])
            details = st.text_area("Incident Details *", placeholder="Describe how/when the card was lost or damaged...")
            if st.form_submit_button("Submit Replacement Request", type="primary", use_container_width=True):
                ok, msg, _ = submit_replacement_request(cit["id"], sel_card_id2, req_type, details, user)
                st.success(msg) if ok else st.error(msg)
                if ok:
                    st.rerun()

        st.markdown("#### My Replacement Requests")
        my_reps = list_replacement_requests(citizen_id=cit["id"])
        if my_reps:
            st.dataframe(pd.DataFrame(my_reps)[["request_code", "nic_number", "request_type", "incident_details", "status", "admin_notes", "new_nic_number", "created_at"]], use_container_width=True, hide_index=True)
        else:
            st.info("No replacement requests submitted.")


# =============================================================================
# 4. CITIZEN VERIFICATION HISTORY
# =============================================================================
def render_citizen_verification_history(user: Dict[str, Any]):
    render_top_header_bar(
        "My Credential Verification History",
        "Audit log of QR code scans and manual verification checks performed on your Smart NIC",
        user=user,
    )
    cit = _get_own_citizen(user)
    if not cit:
        return

    logs = list_verifications(limit=100, citizen_id=cit["id"])
    if logs:
        st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
    else:
        st.info("No verification checks have been recorded on your Smart NIC yet.")


# =============================================================================
# 5. CITIZEN EDIT PERMITTED PROFILE DETAILS
# =============================================================================
def render_citizen_edit_profile(user: Dict[str, Any]):
    render_top_header_bar(
        "Update My Contact & Address Details",
        "Citizens may update permitted contact details and portrait photo; core legal identity fields require administrator verification",
        user=user,
    )
    cit = _get_own_citizen(user)
    if not cit:
        return

    st.info(f"Locked Identity Fields (Admin-verified): **Name:** {cit['full_name']} | **DOB:** {cit['date_of_birth']} | **Email:** {cit['email']}")

    with st.form("citizen_self_edit_form"):
        c1, c2 = st.columns(2)
        with c1:
            mobile = st.text_input("Mobile Number", value=cit["mobile_number"])
        with c2:
            bg_opts = ["Unknown", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
            blood = st.selectbox("Blood Group", bg_opts, index=bg_opts.index(cit["blood_group"]) if cit["blood_group"] in bg_opts else 0)

        address = st.text_input("Residential Address", value=cit["residential_address"])
        c3, c4, c5 = st.columns(3)
        with c3:
            city = st.text_input("City", value=cit["city"])
        with c4:
            state = st.text_input("State", value=cit["state"])
        with c5:
            postal = st.text_input("Postal Code", value=cit["postal_code"])

        new_photo = st.file_uploader("Update Portrait Photograph (JPG/PNG/WEBP, max 5MB)", type=["jpg", "jpeg", "png", "webp"])

        if st.form_submit_button("💾 Save Permitted Profile Updates", type="primary", use_container_width=True):
            ok, msg = update_citizen_profile(
                cit["id"],
                {
                    "mobile_number": mobile,
                    "blood_group": blood,
                    "residential_address": address,
                    "city": city,
                    "state": state,
                    "postal_code": postal,
                },
                photo_bytes=new_photo.getvalue() if new_photo else None,
                actor=user,
                citizen_self_service=True,
            )
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

"""
SMART NIC – National Identity Card Management and Verification System
Academic Prototype Web Platform built with Python, Streamlit, SQLite, Pillow, QRCode, OpenCV, Plotly & FPDF.
"""

import os
import sys
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.database import init_db, log_audit
from utils.seed_data import seed_demo_data_if_empty
from views.public_views import (
    render_login_page,
    render_qr_verification_page,
    render_citizen_registration_form,
)
from views.admin_views import (
    render_admin_dashboard,
    render_citizen_management,
    render_application_management,
    render_smart_nic_generator,
    render_card_management,
    render_renewal_replacement_admin,
    render_reports_analytics,
    render_audit_logs,
    render_user_management,
    render_settings,
)
from views.citizen_views import (
    render_citizen_dashboard,
    render_citizen_smart_nic,
    render_citizen_renewal_replacement,
    render_citizen_verification_history,
    render_citizen_edit_profile,
)

# -----------------------------------------------------------------------------
# 1. PAGE CONFIG & DESIGN SYSTEM
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Smart NIC | National Identity Card System",
    page_icon="🪪",
    layout="wide",
    initial_sidebar_state="expanded",
)

css_path = os.path.join(os.path.dirname(__file__), "assets", "style.css")
if os.path.exists(css_path):
    with open(css_path, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 2. DATABASE INITIALIZATION & DEMO SEEDING
# -----------------------------------------------------------------------------
@st.cache_resource
def bootstrap_database():
    init_db()
    seed_demo_data_if_empty()
    return True


bootstrap_database()

# -----------------------------------------------------------------------------
# 3. SESSION STATE & ROLE-BASED NAVIGATION
# -----------------------------------------------------------------------------
if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None
if "nav_page" not in st.session_state:
    st.session_state["nav_page"] = "Sign In Portal"

user = st.session_state.get("auth_user")

ADMIN_NAV = [
    ("Dashboard", "📊 Dashboard"),
    ("Citizen Registration", "📝 Citizen Registration"),
    ("Citizen Management", "👥 Citizen Management"),
    ("Applications", "📋 Applications"),
    ("Smart NIC Generator", "🪪 Smart NIC Generator"),
    ("Card Management", "🗂️ Card Management"),
    ("QR Verification", "📷 QR Verification"),
    ("Renewal & Replacement", "🔄 Renewal & Replacement"),
    ("Reports & Analytics", "📈 Reports & Analytics"),
    ("Audit Logs", "🛡️ Audit Logs"),
    ("User Management", "🔐 User Management"),
    ("Settings", "⚙️ Settings"),
]

CITIZEN_NAV = [
    ("My Dashboard", "🏠 My Dashboard"),
    ("My Smart NIC", "🪪 My Smart NIC"),
    ("Renewal & Replacement", "🔄 Renewal & Replacement"),
    ("Verification History", "📜 Verification History"),
    ("My Profile", "👤 My Profile"),
    ("QR Verification", "📷 QR Verification"),
]

PUBLIC_NAV = [
    ("Sign In Portal", "🔐 Sign In Portal"),
    ("QR Verification", "📷 Public QR Verification"),
    ("Citizen Registration", "📝 New Citizen Registration"),
]

if user and user.get("role") == "admin":
    nav_pairs = ADMIN_NAV
    section_label = "ADMINISTRATION MENU"
elif user and user.get("role") == "citizen":
    nav_pairs = CITIZEN_NAV
    section_label = "CITIZEN SELF-SERVICE"
else:
    nav_pairs = PUBLIC_NAV
    section_label = "PUBLIC ACCESS PORTAL"

nav_keys = [k for k, _ in nav_pairs]
nav_labels = {k: lbl for k, lbl in nav_pairs}

if st.session_state["nav_page"] not in nav_keys:
    st.session_state["nav_page"] = nav_keys[0]

# -----------------------------------------------------------------------------
# 4. SIDEBAR BRANDING & MENU
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand-box">
            <div class="sidebar-logo-icon">🪪</div>
            <div>
                <div class="sidebar-brand-title">Smart NIC</div>
                <div class="sidebar-brand-subtitle">National Identity Card System</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(f'<div class="sidebar-section-title">{section_label}</div>', unsafe_allow_html=True)

    current_idx = nav_keys.index(st.session_state["nav_page"])
    chosen = st.radio(
        "Navigation",
        options=nav_keys,
        index=current_idx,
        format_func=lambda k: nav_labels[k],
        label_visibility="collapsed",
    )

    if chosen != st.session_state["nav_page"]:
        st.session_state["nav_page"] = chosen
        st.rerun()

    st.markdown("---")
    if user:
        role_color = "#2563EB" if user["role"] == "admin" else "#059669"
        st.markdown(
            f"""
            <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:10px 12px;margin-bottom:10px;">
                <div style="font-size:0.72rem;font-weight:800;color:{role_color};text-transform:uppercase;">{user['role']} SESSION</div>
                <div style="font-size:0.86rem;font-weight:700;color:#0F172A;margin-top:2px;">{user['full_name']}</div>
                <div style="font-size:0.74rem;color:#64748B;">@{user['username']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("🚪 Sign Out", use_container_width=True):
            log_audit("LOGOUT", "auth", str(user["id"]), "User signed out", user["id"], user["username"], user["role"])
            st.session_state["auth_user"] = None
            st.session_state["nav_page"] = "Sign In Portal"
            st.session_state["last_verify_result"] = None
            st.rerun()
    else:
        st.markdown(
            """
            <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:10px 12px;font-size:0.75rem;color:#64748B;">
                <b style="color:#0F172A;">Academic Prototype</b><br>
                QR Verification works publicly without signing in.
            </div>
            """,
            unsafe_allow_html=True,
        )

# -----------------------------------------------------------------------------
# 5. PAGE ROUTER (WITH STRICT ROLE ENFORCEMENT)
# -----------------------------------------------------------------------------
page = st.session_state["nav_page"]

if user and user.get("role") == "admin":
    if page == "Dashboard":
        render_admin_dashboard(user)
    elif page == "Citizen Registration":
        render_citizen_registration_form(actor=user)
    elif page == "Citizen Management":
        render_citizen_management(user)
    elif page == "Applications":
        render_application_management(user)
    elif page == "Smart NIC Generator":
        render_smart_nic_generator(user)
    elif page == "Card Management":
        render_card_management(user)
    elif page == "QR Verification":
        render_qr_verification_page(user=user)
    elif page == "Renewal & Replacement":
        render_renewal_replacement_admin(user)
    elif page == "Reports & Analytics":
        render_reports_analytics(user)
    elif page == "Audit Logs":
        render_audit_logs(user)
    elif page == "User Management":
        render_user_management(user)
    elif page == "Settings":
        render_settings(user)

elif user and user.get("role") == "citizen":
    if page == "My Dashboard":
        render_citizen_dashboard(user)
    elif page == "My Smart NIC":
        render_citizen_smart_nic(user)
    elif page == "Renewal & Replacement":
        render_citizen_renewal_replacement(user)
    elif page == "Verification History":
        render_citizen_verification_history(user)
    elif page == "My Profile":
        render_citizen_edit_profile(user)
    elif page == "QR Verification":
        render_qr_verification_page(user=user)

else:
    if page == "Sign In Portal":
        render_login_page()
    elif page == "QR Verification":
        render_qr_verification_page(user=None)
    elif page == "Citizen Registration":
        render_citizen_registration_form(actor=None)

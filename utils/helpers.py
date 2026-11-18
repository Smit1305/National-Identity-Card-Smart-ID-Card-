"""
UI & Formatting Helpers for Smart NIC – National Identity Card Management System
Matches the academic SaaS light design system (#F8FAFC, #FFFFFF, #2563EB).
"""

from typing import Union

STATUS_COLORS = {
    "ACTIVE": "#059669",
    "VALID": "#059669",
    "APPROVED": "#059669",
    "PENDING": "#D97706",
    "UNDER REVIEW": "#2563EB",
    "EXPIRED": "#D97706",
    "REVOKED": "#DC2626",
    "REJECTED": "#DC2626",
    "INVALID": "#DC2626",
    "INACTIVE": "#64748B",
    "NOT FOUND": "#64748B",
}


def format_number(val: Union[int, float, None]) -> str:
    if val is None:
        return "0"
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)


def render_metric_card(
    label: str,
    value: str,
    subtext: str = "",
    icon: str = "🪪",
    icon_theme: str = "blue",
) -> str:
    """
    Render a KPI stat card matching the Sem_7_CV_Project SaaS light theme.
    icon_theme: 'blue', 'purple', 'amber', 'green', 'rose', 'cyan'
    """
    return f"""
    <div class="kpi-stat-card">
        <div>
            <div class="kpi-title">{label}</div>
            <div class="kpi-number">{value}</div>
            <div class="kpi-desc">{subtext}</div>
        </div>
        <div class="kpi-icon-box icon-box-{icon_theme}">{icon}</div>
    </div>
    """


def get_status_badge_html(status: str) -> str:
    """Render a semantic pill badge for card, application, or verification status."""
    s = str(status or "").strip().upper()
    if s in ("ACTIVE", "VALID", "APPROVED"):
        cls = "badge-allow"
    elif s in ("REVOKED", "REJECTED", "INVALID"):
        cls = "badge-drop"
    elif s in ("PENDING", "EXPIRED"):
        cls = "badge-udp"
    elif s in ("UNDER REVIEW",):
        cls = "badge-tcp"
    else:
        cls = "badge-other"
    return f'<span class="badge {cls}">{status}</span>'

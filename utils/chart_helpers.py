"""
Plotly Chart Helpers for Smart NIC – National Identity Card Management System
Consistent, light-themed SaaS visualizations matching Sem_7_CV_Project.
"""

import pandas as pd
import plotly.graph_objects as go

from utils.helpers import STATUS_COLORS

LIGHT_LAYOUT = dict(
    paper_bgcolor="#FFFFFF",
    plot_bgcolor="#F8FAFC",
    font=dict(family="Plus Jakarta Sans, sans-serif", color="#0F172A", size=12),
    margin=dict(l=40, r=30, t=48, b=40),
    legend=dict(
        bgcolor="rgba(255, 255, 255, 0.95)",
        bordercolor="#E2E8F0",
        borderwidth=1,
        font=dict(color="#334155", size=11),
    ),
    xaxis=dict(
        gridcolor="#E2E8F0",
        zerolinecolor="#CBD5E1",
        tickfont=dict(color="#64748B", size=11),
    ),
    yaxis=dict(
        gridcolor="#E2E8F0",
        zerolinecolor="#CBD5E1",
        tickfont=dict(color="#64748B", size=11),
    ),
)


def create_monthly_registrations_chart(monthly_df: pd.DataFrame) -> go.Figure:
    """Line + bar chart of monthly citizen registrations."""
    if monthly_df.empty:
        fig = go.Figure()
        fig.update_layout(title="No Registration Data", **LIGHT_LAYOUT)
        return fig

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=monthly_df["month"],
            y=monthly_df["registrations"],
            name="Registrations",
            marker=dict(color="#2563EB", line=dict(color="#FFFFFF", width=1)),
            text=monthly_df["registrations"],
            textposition="auto",
            hovertemplate="<b>%{x}</b><br>Citizens Registered: %{y:,}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=monthly_df["month"],
            y=monthly_df["registrations"],
            mode="lines+markers",
            name="Trend",
            line=dict(color="#059669", width=2.5),
            marker=dict(size=7, color="#059669"),
        )
    )
    fig.update_layout(
        title=dict(text="<b>Monthly Citizen Registrations</b>", font=dict(size=14, color="#0F172A")),
        xaxis_title="Month (YYYY-MM)",
        yaxis_title="Citizens Registered",
        **LIGHT_LAYOUT,
    )
    return fig


def create_application_status_chart(app_status_df: pd.DataFrame) -> go.Figure:
    """Donut chart showing application status distribution."""
    if app_status_df.empty:
        fig = go.Figure()
        fig.update_layout(title="No Application Data", **LIGHT_LAYOUT)
        return fig

    colors = [STATUS_COLORS.get(str(s).upper(), "#64748B") for s in app_status_df["status"]]
    fig = go.Figure(
        data=[
            go.Pie(
                labels=app_status_df["status"],
                values=app_status_df["count"],
                hole=0.58,
                marker=dict(colors=colors, line=dict(color="#FFFFFF", width=2)),
                textinfo="label+value",
                hovertemplate="<b>%{label}</b><br>Applications: %{value:,}<br>Share: %{percent}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title=dict(text="<b>Application Status Distribution</b>", font=dict(size=14, color="#0F172A")),
        showlegend=True,
        **LIGHT_LAYOUT,
    )
    return fig


def create_card_status_chart(card_status_df: pd.DataFrame) -> go.Figure:
    """Bar chart of issued Smart NIC card lifecycle statuses."""
    if card_status_df.empty:
        fig = go.Figure()
        fig.update_layout(title="No Issued Cards Yet", **LIGHT_LAYOUT)
        return fig

    colors = [STATUS_COLORS.get(str(s).upper(), "#2563EB") for s in card_status_df["status"]]
    fig = go.Figure(
        data=[
            go.Bar(
                x=card_status_df["status"],
                y=card_status_df["count"],
                marker=dict(color=colors, line=dict(color="#FFFFFF", width=1)),
                text=card_status_df["count"],
                textposition="auto",
                hovertemplate="<b>%{x}</b>: %{y:,} cards<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title=dict(text="<b>Issued Smart NIC Cards by Status</b>", font=dict(size=14, color="#0F172A")),
        xaxis_title="Card Status",
        yaxis_title="Card Count",
        **LIGHT_LAYOUT,
    )
    return fig


def create_verification_results_chart(verif_df: pd.DataFrame) -> go.Figure:
    """Donut chart of QR / manual verification outcomes."""
    if verif_df.empty:
        fig = go.Figure()
        fig.update_layout(title="No Verification Activity Yet", **LIGHT_LAYOUT)
        return fig

    colors = [STATUS_COLORS.get(str(r).upper(), "#64748B") for r in verif_df["result"]]
    fig = go.Figure(
        data=[
            go.Pie(
                labels=verif_df["result"],
                values=verif_df["count"],
                hole=0.55,
                marker=dict(colors=colors, line=dict(color="#FFFFFF", width=2)),
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>Checks: %{value:,}<br>Share: %{percent}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title=dict(text="<b>QR Verification Outcomes</b>", font=dict(size=14, color="#0F172A")),
        showlegend=True,
        **LIGHT_LAYOUT,
    )
    return fig

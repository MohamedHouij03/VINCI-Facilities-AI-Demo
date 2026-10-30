"""Shared visual components: styles, page headers, KPI cards, workflow stepper, badges, footer."""

from __future__ import annotations

import html

import streamlit as st

from components.api_client import ApiError, get_client

DISCLAIMER = (
    "Prototype indépendant développé dans le cadre d'une candidature de stage. "
    "Projet non affilié ni approuvé par VINCI Facilities."
)

STATUS_TONES = {"Terminée": "ok", "En cours": "info", "En attente": "warn"}

_CSS = """
<style>
:root { --brand: #1E4F93; --accent: #E92436; --ink: #1F2933; --ink-2: #52606D; --muted: #7B8794; --line: #E1E6EF; --soft: #F3F6FB; }
.block-container { padding-top: 1.6rem; padding-bottom: 1rem; max-width: 1380px; }
h1, h2, h3 { color: var(--brand); letter-spacing: -0.01em; }
.brand { line-height: 1.25; padding: 0.2rem 0 0.8rem 0; border-bottom: 1px solid var(--line); margin-bottom: 0.4rem; }
.brand-title { font-weight: 700; font-size: 1.08rem; color: var(--brand); }
.brand-title span { color: var(--accent); }
.brand-sub { font-size: 0.78rem; color: var(--ink-2); }
.page-title { font-size: 1.65rem; font-weight: 650; color: var(--brand); margin: 0; }
.page-sub { color: var(--ink-2); margin: 0.15rem 0 1.1rem 0; font-size: 0.95rem; }
.page-kicker { color: var(--accent); font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
.kpi { border: 1px solid var(--line); border-radius: 8px; padding: 0.8rem 0.95rem; background: #fff; min-height: 122px; }
.kpi.accent { border-left: 3px solid var(--accent); }
.kpi-label { font-size: 0.72rem; color: var(--ink-2); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
.kpi-value { font-size: 1.85rem; font-weight: 650; color: var(--brand); line-height: 1.2; margin-top: 0.15rem; }
.kpi-hint { font-size: 0.75rem; color: var(--muted); margin-top: 0.1rem; }
.stepper { display: flex; gap: 0.5rem; margin: 0.2rem 0 1.2rem 0; }
.step { flex: 1; border: 1px solid var(--line); border-radius: 8px; padding: 0.55rem 0.8rem; background: #fff; color: var(--muted); font-size: 0.85rem; }
.step b { display: block; font-size: 0.7rem; letter-spacing: 0.06em; text-transform: uppercase; }
.step.done { border-color: #C5D3E8; color: var(--brand); background: var(--soft); }
.step.current { border: 1px solid var(--brand); color: var(--brand); box-shadow: inset 0 -3px 0 var(--accent); }
.badge { display: inline-block; padding: 0.1rem 0.55rem; border-radius: 999px; font-size: 0.74rem; font-weight: 600; border: 1px solid transparent; white-space: nowrap; }
.badge.ok { background: #EAF4EA; color: #1E5E20; border-color: #CFE5CF; }
.badge.info { background: #EAF1FB; color: #1D4F91; border-color: #D3E1F5; }
.badge.warn { background: #FFF5E0; color: #7A4F00; border-color: #F5E2B8; }
.badge.danger { background: #FBEAEA; color: #8E1B16; border-color: #F2CFCD; }
.badge.neutral { background: var(--soft); color: var(--ink-2); border-color: var(--line); }
.panel { border: 1px solid var(--line); border-radius: 8px; padding: 0.9rem 1rem; background: #fff; }
.panel-title { font-weight: 650; color: var(--brand); margin-bottom: 0.35rem; }
.muted { color: var(--muted); font-size: 0.82rem; }
.hero { border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; padding: 1rem 1.2rem; background: linear-gradient(90deg, #EEF3FA 0%, #FFFFFF 65%); margin-bottom: 1rem; }
.hero h1 { font-size: 1.55rem; margin: 0 0 0.25rem 0; color: var(--brand); }
[data-testid="stSidebar"] { border-right: 3px solid var(--brand); }
[data-testid="stSidebarNav"] a[aria-current="page"], a[data-testid="stPageLink-NavLink"][aria-current="page"] { background: #E3ECF8; }
a[data-testid="stPageLink-NavLink"][aria-current="page"] p { color: var(--brand); font-weight: 650; }
.hero p { margin: 0; color: var(--ink-2); }
.app-footer { font-size: 0.75rem; color: var(--muted); border-top: 1px solid var(--line); margin-top: 2.2rem; padding-top: 0.7rem; }
div[data-testid="stMetric"] { border: 1px solid var(--line); border-radius: 8px; padding: 0.6rem 0.8rem; }
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def sidebar_brand() -> None:
    st.sidebar.markdown(
        '<div class="brand"><div class="brand-title">VINCI Facilities <span>|</span> AI Demo</div>'
        '<div class="brand-sub">Assistant intelligent de maintenance des bâtiments</div></div>',
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=20, show_spinner=False)
def _mode_status() -> dict | None:
    try:
        return get_client().automation_status()
    except ApiError:
        return None


def sidebar_mode_indicator() -> None:
    status = _mode_status()
    if status is None:
        st.sidebar.markdown(badge("API injoignable", "danger"), unsafe_allow_html=True)
        return
    llm = next((i for i in status["integrations"] if i["name"] == "IA générative"), None)
    if status["demo_mode"]:
        st.sidebar.markdown(
            badge("Mode démo", "warn") + '<div class="muted" style="margin-top:.3rem">Extraction par règles et '
            "automatisations simulées : aucune donnée n'est envoyée à des services externes.</div>",
            unsafe_allow_html=True,
        )
    elif llm and llm["state"] == "active":
        st.sidebar.markdown(badge(f"IA active - {llm['detail']}", "ok"), unsafe_allow_html=True)
    else:
        st.sidebar.markdown(badge("IA générative non configurée", "neutral"), unsafe_allow_html=True)


def page_header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="page-kicker">{html.escape(kicker)}</div><div class="page-title">{html.escape(title)}</div>'
        f'<div class="page-sub">{html.escape(subtitle)}</div>',
        unsafe_allow_html=True,
    )


def badge(text: str, tone: str = "neutral") -> str:
    return f'<span class="badge {tone}">{html.escape(text)}</span>'


def status_badge(label: str) -> str:
    return badge(label, STATUS_TONES.get(label, "neutral"))


def kpi_cards(items: list[tuple[str, object, str, bool]]) -> None:
    """items: (label, value, hint, accent)."""
    columns = st.columns(len(items))
    for column, (label, value, hint, accent) in zip(columns, items, strict=True):
        column.markdown(
            f'<div class="kpi{" accent" if accent else ""}"><div class="kpi-label">{html.escape(label)}</div>'
            f'<div class="kpi-value">{html.escape(str(value))}</div>'
            f'<div class="kpi-hint">{html.escape(hint)}</div></div>',
            unsafe_allow_html=True,
        )


WORKFLOW_STEPS = ("Téléverser", "Analyser", "Vérifier", "Enregistrer")


def stepper(current: int, completed: bool = False) -> None:
    """current: 0-based index of the active step. `completed` marks every step as done."""
    parts = []
    for index, name in enumerate(WORKFLOW_STEPS):
        state = "done" if completed or index < current else "current" if index == current else ""
        prefix = f"Étape {index + 1}" + (" - terminée" if state == "done" else "")
        parts.append(f'<div class="step {state}"><b>{prefix}</b>{name}</div>')
    st.markdown(f'<div class="stepper">{"".join(parts)}</div>', unsafe_allow_html=True)


def footer() -> None:
    st.markdown(f'<div class="app-footer">{html.escape(DISCLAIMER)}</div>', unsafe_allow_html=True)


def show_api_error(error: ApiError) -> None:
    st.error(error.message, icon=":material/error:")


def flash(message: str, kind: str = "success") -> None:
    """Store a message displayed once after the next rerun."""
    st.session_state["_flash"] = (message, kind)


def render_flash() -> None:
    if item := st.session_state.pop("_flash", None):
        message, kind = item
        {"success": st.success, "warning": st.warning, "info": st.info, "error": st.error}[kind](message)

"""Streamlit entry point: `streamlit run frontend/app.py`."""

from __future__ import annotations

import streamlit as st

from components.ui import footer, inject_css, sidebar_brand

st.set_page_config(
    page_title="VINCI Facilities | AI Demo",
    page_icon=":material/apartment:",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

pages = [
    st.Page("pages/dashboard.py", title="Tableau de bord", icon=":material/space_dashboard:", default=True),
    st.Page("pages/interventions.py", title="Interventions", icon=":material/build:"),
    st.Page("pages/report_analysis.py", title="Analyse IA", icon=":material/document_scanner:"),
    st.Page("pages/ai_assistant.py", title="Assistant IA", icon=":material/forum:"),
    st.Page("pages/documents.py", title="Documentation technique", icon=":material/menu_book:"),
    st.Page("pages/automation.py", title="Automatisations", icon=":material/account_tree:"),
]

# The default menu is hidden so that the brand block can sit above the page links.
navigation = st.navigation(pages, position="hidden")
with st.sidebar:
    sidebar_brand()
    for page in pages:
        st.page_link(page)

navigation.run()
footer()

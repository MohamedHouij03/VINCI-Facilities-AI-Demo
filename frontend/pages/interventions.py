"""Interventions: searchable table, detail view, corrections and follow-up completion."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from components.api_client import ApiError, get_client
from components.ui import badge, page_header, render_flash, show_api_error, status_badge, flash

STATUS_OPTIONS = {"en_attente": "En attente", "en_cours": "En cours", "terminee": "Terminée"}
CATEGORIES = ["CVC", "Électricité", "Plomberie", "Sécurité incendie", "Ascenseurs", "Autre"]

api = get_client()
page_header("Interventions", "Registre des interventions", "Toutes les interventions validées, avec recherche, filtres et suivi.")
render_flash()

try:
    buildings = {b["code"]: b["name"] for b in api.buildings()}
except ApiError as error:
    show_api_error(error)
    st.stop()

with st.container(border=True):
    c1, c2, c3, c4, c5 = st.columns([1.6, 1.2, 1.1, 1.1, 0.9])
    search = c1.text_input("Recherche", placeholder="Référence, équipement, problème, technicien…")
    building_filter = c2.multiselect("Bâtiment", list(buildings), format_func=lambda c: buildings[c], placeholder="Tous")
    category_filter = c3.multiselect("Catégorie", CATEGORIES, placeholder="Toutes")
    status_filter = c4.multiselect("Statut", list(STATUS_OPTIONS), format_func=STATUS_OPTIONS.get, placeholder="Tous")
    c5.write("")
    follow_up_only = c5.toggle("Suivi ouvert")

params = {"building": building_filter, "category": category_filter, "status": status_filter, "search": search or None}
if follow_up_only:
    params["follow_up_open"] = True

try:
    page = api.interventions(params)
except ApiError as error:
    show_api_error(error)
    st.stop()

items = page["items"]
st.caption(f"{page['total']} intervention(s) - sélectionnez une ligne pour afficher le détail.")
if not items:
    st.info("Aucune intervention ne correspond à la recherche.")
    st.stop()

table = pd.DataFrame(
    [
        {
            "Intervention": i["reference"],
            "Date": i["date"],
            "Bâtiment": i["building_code"],
            "Équipement": f"{i['equipment_code']} - {i['equipment_name']}",
            "Catégorie": i["equipment_category"],
            "Problème": i["problem_description"],
            "Statut": i["status_label"],
            "Suivi requis": "Oui" if i["follow_up_required"] else "Non",
            "Suivi ouvert": "Oui" if i["follow_up_open"] else "",
            "Source": {"seed": "Historique", "report": "Rapport analysé", "manual": "Saisie"}[i["source"]],
        }
        for i in items
    ]
)
selection = st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    height=min(420, 38 + 35 * len(table)),
    on_select="rerun",
    selection_mode="single-row",
    key="interventions_table",
    column_config={"Problème": st.column_config.TextColumn(width="large")},
)

selected_rows = selection.selection.rows if selection else []
if not selected_rows:
    st.stop()

item = items[selected_rows[0]]
st.write("")
with st.container(border=True):
    head_left, head_right = st.columns([3, 1.2])
    head_left.markdown(
        f"### {item['reference']} &nbsp; {status_badge(item['status_label'])} "
        + (badge("Suivi ouvert", "danger") if item["follow_up_open"] else ""),
        unsafe_allow_html=True,
    )
    head_left.caption(f"{item['building_name']} · {item['equipment_code']} - {item['equipment_name']} · {item['equipment_category']}")
    if item["follow_up_open"] and head_right.button("Marquer le suivi comme effectué", icon=":material/task_alt:", width="stretch"):
        try:
            api.complete_follow_up(item["id"])
            flash(f"Suivi de {item['reference']} marqué comme effectué.")
            st.rerun()
        except ApiError as error:
            show_api_error(error)

    details, edit = st.tabs(["Détail", "Modifier"])
    with details:
        d1, d2 = st.columns(2)
        d1.markdown(f"**Date :** {date.fromisoformat(item['date']).strftime('%d/%m/%Y')}")
        d1.markdown(f"**Technicien :** {item['technician'] or 'Non renseigné'}")
        d1.markdown(f"**Problème constaté :** {item['problem_description']}")
        d1.markdown(f"**Actions réalisées :** {item['actions_performed'] or 'Non documentées'}")
        d2.markdown(f"**Recommandations :** {item['recommendations'] or 'Aucune'}")
        d2.markdown(f"**Suivi requis :** {'Oui' if item['follow_up_required'] else 'Non'}"
                    + (f" (effectué le {item['follow_up_completed_at'][:10]})" if item["follow_up_completed_at"] else ""))
        d2.markdown(f"**Origine :** {'Rapport analysé par IA puis validé' if item['source'] == 'report' else 'Historique'}")
        if item["summary"]:
            with st.expander("Résumé généré lors de l'analyse", expanded=item["source"] == "report"):
                st.markdown(item["summary"])

    with edit, st.form(f"edit_{item['id']}"):
        e1, e2 = st.columns(2)
        new_date = e1.date_input("Date", value=date.fromisoformat(item["date"]), format="DD/MM/YYYY")
        new_status = e2.selectbox("Statut", list(STATUS_OPTIONS), index=list(STATUS_OPTIONS).index(item["status"]),
                                  format_func=STATUS_OPTIONS.get)
        new_technician = e1.text_input("Technicien", value=item["technician"] or "")
        new_follow_up = e2.checkbox("Suivi nécessaire", value=item["follow_up_required"])
        new_problem = st.text_area("Problème constaté", value=item["problem_description"])
        new_actions = st.text_area("Actions réalisées", value=item["actions_performed"] or "")
        new_recommendations = st.text_area("Recommandations", value=item["recommendations"] or "")
        if st.form_submit_button("Enregistrer les modifications", type="primary"):
            changes = {
                "date": new_date.isoformat(),
                "status": new_status,
                "technician": new_technician or None,
                "follow_up_required": new_follow_up,
                "problem_description": new_problem,
                "actions_performed": new_actions or None,
                "recommendations": new_recommendations or None,
            }
            try:
                api.update_intervention(item["id"], changes)
                flash(f"{item['reference']} mise à jour. Le tableau de bord reflète la modification.")
                st.rerun()
            except ApiError as error:
                show_api_error(error)

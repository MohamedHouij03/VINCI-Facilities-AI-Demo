"""Tableau de bord: KPIs and maintenance analytics computed by the backend from the database."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from components import charts
from components.api_client import ApiError, get_client
from components.ui import kpi_cards, show_api_error

api = get_client()

st.markdown(
    '<div class="hero"><h1>Assistant intelligent de maintenance des bâtiments</h1>'
    "<p>Les rapports d'intervention sont analysés par l'IA, vérifiés par un responsable puis centralisés : "
    "le suivi des équipements et des bâtiments se met à jour automatiquement.</p></div>",
    unsafe_allow_html=True,
)
cta_left, cta_right, _ = st.columns([1.4, 1.7, 2.6])
cta_left.page_link("pages/report_analysis.py", label="Analyser un rapport avec l'IA", icon=":material/arrow_forward:")
cta_right.page_link("pages/ai_assistant.py", label="Poser une question à l'assistant", icon=":material/forum:")

try:
    buildings = api.buildings()
    bounds = api.dashboard({})["date_bounds"]
except ApiError as error:
    show_api_error(error)
    st.stop()

building_names = {b["code"]: b["name"] for b in buildings}
min_date = date.fromisoformat(bounds["min"]) if bounds["min"] else date.today()
max_date = max(date.fromisoformat(bounds["max"]) if bounds["max"] else date.today(), date.today())

with st.container(border=True):
    f1, f2, f3, f4 = st.columns([1.4, 1.2, 1.2, 1.2])
    selected_buildings = f1.multiselect(
        "Bâtiment", list(building_names), format_func=lambda code: building_names[code], placeholder="Tous les bâtiments"
    )
    period = f2.date_input("Période", value=(min_date, max_date), min_value=date(2020, 1, 1), max_value=date.today(),
                           format="DD/MM/YYYY")
    categories = f3.multiselect(
        "Catégorie d'équipement",
        ["CVC", "Électricité", "Plomberie", "Sécurité incendie", "Ascenseurs", "Autre"],
        placeholder="Toutes les catégories",
    )
    statuses = f4.multiselect(
        "Statut",
        ["en_attente", "en_cours", "terminee"],
        format_func={"en_attente": "En attente", "en_cours": "En cours", "terminee": "Terminée"}.get,
        placeholder="Tous les statuts",
    )

params: dict = {"building": selected_buildings, "category": categories, "status": statuses}
if isinstance(period, tuple) and len(period) == 2:
    params["date_from"], params["date_to"] = period[0].isoformat(), period[1].isoformat()

try:
    data = api.dashboard(params)
except ApiError as error:
    show_api_error(error)
    st.stop()

kpis = data["kpis"]
rule = data["recurrence_rule"]
kpi_cards(
    [
        ("Interventions", kpis["total"], "sur la période filtrée", False),
        ("Terminées", kpis["completed"], f"{kpis['completed'] / kpis['total']:.0%} du total" if kpis["total"] else "-", False),
        ("Non terminées", kpis["pending"], f"{kpis['in_progress']} en cours, {kpis['waiting']} en attente", False),
        ("Suivis à traiter", kpis["follow_up_open"], "interventions avec suivi ouvert", True),
        ("Incidents récurrents", kpis["recurring_equipment"],
         f"équipements, ≥ {rule['threshold']} interventions / {rule['window_days']} j", True),
        ("Bâtiments suivis", kpis["buildings_monitored"], "dans le périmètre", False),
    ]
)

if kpis["total"] == 0:
    st.info("Aucune intervention ne correspond aux filtres sélectionnés.")
    st.stop()

st.write("")
left, right = st.columns(2)
with left, st.container(border=True):
    st.markdown("**Interventions par mois**")
    st.plotly_chart(charts.monthly_bar(data["by_month"]), width="stretch", config={"displayModeBar": False})
with right, st.container(border=True):
    st.markdown("**Interventions par bâtiment**")
    rows = data["by_building"]
    st.plotly_chart(
        charts.horizontal_bar([r["building_name"].split(" - ")[-1] + f" ({r['building_code'][-1]})" for r in rows],
                              [r["count"] for r in rows]),
        width="stretch", config={"displayModeBar": False},
    )

left, right = st.columns(2)
with left, st.container(border=True):
    st.markdown("**Répartition par catégorie d'équipement**")
    rows = data["by_category"]
    st.plotly_chart(charts.horizontal_bar([r["category"] for r in rows], [r["count"] for r in rows]),
                    width="stretch", config={"displayModeBar": False})
with right, st.container(border=True):
    st.markdown("**Statut des interventions**")
    rows = data["by_status"]
    st.plotly_chart(charts.horizontal_bar([r["label"] for r in rows], [r["count"] for r in rows]),
                    width="stretch", config={"displayModeBar": False})

left, right = st.columns([1.15, 1])
with left, st.container(border=True):
    st.markdown("**Équipements les plus sollicités**")
    st.plotly_chart(charts.top_equipment_bar(data["top_equipment"]), width="stretch",
                    config={"displayModeBar": False})
    st.caption(
        f"Règle de récurrence : au moins {rule['threshold']} interventions sur une fenêtre de "
        f"{rule['window_days']} jours (paramètres RECURRENCE_THRESHOLD et RECURRENCE_WINDOW_DAYS)."
    )
with right, st.container(border=True):
    st.markdown("**Équipements nécessitant un suivi**")
    follow_ups = data["follow_up_equipment"]
    if follow_ups:
        st.dataframe(
            pd.DataFrame(follow_ups).rename(
                columns={"equipment_code": "Équipement", "equipment_name": "Désignation", "building_code": "Bâtiment",
                         "open_follow_ups": "Suivis ouverts", "last_date": "Dernière intervention"}
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("Aucun suivi ouvert sur la sélection.")
    recurring = [r for r in data["recurring"] if r["recurring"]]
    if recurring:
        st.markdown("**Incidents récurrents détectés**")
        for item in recurring:
            st.markdown(
                f"- **{item['equipment_code']}** - {item['equipment_name']} ({item['building_code']}) : "
                f"{item['max_in_window']} interventions du {item['window_start']} au {item['window_end']}"
            )

with st.container(border=True):
    st.markdown("**Interventions récentes**")
    recent = pd.DataFrame(data["recent"])
    recent["follow_up_open"] = recent["follow_up_open"].map({True: "Oui", False: "Non"})
    st.dataframe(
        recent.drop(columns=["id"]).rename(
            columns={"reference": "Référence", "date": "Date", "building_code": "Bâtiment", "equipment": "Équipement",
                     "problem": "Problème", "status": "Statut", "follow_up_open": "Suivi ouvert"}
        ),
        hide_index=True,
        width="stretch",
    )
    st.page_link("pages/interventions.py", label="Voir toutes les interventions", icon=":material/arrow_forward:")

"""Automatisations: integration status, n8n workflow metrics, notifications and event log."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.api_client import ApiError, get_client
from components.ui import badge, flash, kpi_cards, page_header, render_flash, show_api_error

STATE_BADGES = {
    "active": ("Actif", "ok"),
    "demo": ("Mode démo", "warn"),
    "not_configured": ("Non configuré", "neutral"),
    "fallback": ("Mode de secours", "warn"),
    "unavailable": ("Indisponible", "danger"),
}
NOTIFICATION_LABELS = {
    "pending": "En attente", "dispatched": "Transmise à n8n", "sending": "Envoi en cours (n8n)", "sent": "Envoyée",
    "failed": "Échec", "simulated": "Simulée (démo)", "not_configured": "Non envoyée (configuration manquante)",
}
WORKFLOW = [
    ("Téléversement", "Le rapport PDF est envoyé à l'API FastAPI, qui crée un job de traitement."),
    ("Webhook n8n", "FastAPI notifie n8n (job_id) ; n8n rappelle l'API pour lancer l'analyse, avec reprise sur erreur."),
    ("Analyse", "Extraction du texte et des informations : le résultat est stocké comme brouillon."),
    ("Validation humaine", "Un responsable vérifie, corrige puis valide : seule une donnée validée est enregistrée."),
    ("Notification", "Si un suivi est requis, FastAPI déclenche le second webhook ; n8n envoie l'e-mail une seule fois."),
]

api = get_client()
page_header(
    "Automatisations",
    "Workflows n8n et intégrations",
    "État des intégrations et indicateurs mesurés à partir des événements réellement enregistrés.",
)
render_flash()

try:
    status = api.automation_status()
except ApiError as error:
    show_api_error(error)
    st.stop()

if status["demo_mode"]:
    st.info("Mode démo actif : les notifications sont simulées et aucun appel n'est fait vers n8n ou l'IA générative. "
            "Voir le README pour connecter les services réels.", icon=":material/info:")

st.markdown("**Intégrations**")
columns = st.columns(len(status["integrations"]))
for column, integration in zip(columns, status["integrations"], strict=True):
    label, tone = STATE_BADGES[integration["state"]]
    with column, st.container(border=True, height=150):
        st.markdown(f"**{integration['name']}**")
        st.markdown(badge(label, tone), unsafe_allow_html=True)
        st.caption(integration["detail"])

metrics = status["metrics"]
st.write("")
kpi_cards(
    [
        ("Rapports traités", metrics["jobs_processed_successfully"], "analyse terminée sans erreur", False),
        ("Échecs de traitement", metrics["processing_failures"], "erreurs enregistrées", False),
        ("Notifications envoyées", metrics["notifications_sent"], "confirmées par n8n", True),
        ("Notifications simulées", metrics["notifications_simulated"], "mode démo", False),
        ("Doublons évités", metrics["duplicates_prevented"], "traitements, e-mails ou saisies", True),
        ("Échecs de webhook", metrics["webhook_dispatch_failures"], "après nouvelles tentatives", False),
    ]
)

st.write("")
with st.container(border=True):
    st.markdown("**Scénario automatisé**")
    steps = st.columns(len(WORKFLOW))
    for index, (column, (title, text)) in enumerate(zip(steps, WORKFLOW, strict=True), start=1):
        column.markdown(f"**{index}. {title}**")
        column.caption(text)

left, right = st.columns([1.1, 1])
with left, st.container(border=True):
    st.markdown("**Notifications de suivi**")
    notifications = status["notifications"]
    if not notifications:
        st.caption("Aucune notification pour l'instant : elles sont créées lorsqu'une intervention validée requiert un suivi.")
    else:
        table = pd.DataFrame(
            [
                {
                    "Clé d'idempotence": n["idempotency_key"],
                    "Statut": NOTIFICATION_LABELS.get(n["status"], n["status"]),
                    "Destinataire": n["recipient"] or "-",
                    "Tentatives": n["attempts"],
                    "Créée le": n["created_at"][:16].replace("T", " "),
                    "Envoyée le": (n["sent_at"] or "")[:16].replace("T", " "),
                    "Erreur": n["last_error"] or "",
                }
                for n in notifications
            ]
        )
        selection = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun",
                                 selection_mode="single-row", key="notifications_table")
        if selection.selection.rows:
            notification = notifications[selection.selection.rows[0]]
            if notification["status"] in ("failed", "not_configured"):
                if st.button("Relancer la notification", icon=":material/send:"):
                    try:
                        result = api.retry_notification(notification["id"])
                        flash(f"Notification relancée : {NOTIFICATION_LABELS.get(result['status'], result['status'])}.")
                        st.rerun()
                    except ApiError as error:
                        show_api_error(error)
            else:
                st.caption("Relance possible uniquement pour une notification en échec ou non configurée "
                           "(protection contre les doublons).")

with right, st.container(border=True):
    st.markdown("**Journal des événements**")
    events = status["recent_events"]
    if events:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Date": e["created_at"][:19].replace("T", " "), "Niveau": e["level"], "Événement": e["event_type"],
                     "Détail": e["message"]}
                    for e in events
                ]
            ),
            hide_index=True,
            width="stretch",
            height=360,
        )
    else:
        st.caption("Aucun événement enregistré.")

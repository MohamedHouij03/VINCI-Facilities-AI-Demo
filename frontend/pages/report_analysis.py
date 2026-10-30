"""Analyse IA: upload -> AI extraction -> human verification -> database (core workflow)."""

from __future__ import annotations

import time
from datetime import date

import pandas as pd
import streamlit as st

from components.api_client import ApiError, get_client
from components.ui import badge, page_header, show_api_error, stepper

STATUS_OPTIONS = {"en_attente": "En attente", "en_cours": "En cours", "terminee": "Terminée"}
CATEGORIES = ["CVC", "Électricité", "Plomberie", "Sécurité incendie", "Ascenseurs", "Autre"]
PENDING_STATUSES = {"uploaded", "queued", "processing"}
METHODS = {"text": "Texte natif (PyMuPDF)", "ocr": "OCR Tesseract", "mixed": "Texte natif + OCR", "empty": "Aucun texte"}
GROUNDING = {
    "found": ":material/check_circle: Retrouvé dans le document",
    "check": ":material/warning: À vérifier : valeur non retrouvée telle quelle dans le texte",
    "interpreted": ":material/info: Valeur interprétée à partir du document",
    "missing": ":material/help: Absent du document : à compléter uniquement si l'information est connue",
}

api = get_client()
page_header(
    "Analyse IA",
    "Analyse automatique d'un rapport d'intervention",
    "L'IA extrait les informations du rapport ; un responsable vérifie et valide avant tout enregistrement.",
)


def format_duration(milliseconds: int | None) -> str:
    milliseconds = milliseconds or 0
    return f"{milliseconds} ms" if milliseconds < 1000 else f"{milliseconds / 1000:.1f} s"


def reset() -> None:
    for key in ("analysis_job_id", "analysis_result", "analysis_warning"):
        st.session_state.pop(key, None)


def start(response: dict) -> None:
    st.session_state["analysis_job_id"] = response["job"]["job_id"]
    st.session_state["analysis_warning"] = response.get("duplicate_warning")
    st.session_state.pop("analysis_result", None)
    st.rerun()


# ---------------------------------------------------------------------------------------------
# Step 4 - saved
# ---------------------------------------------------------------------------------------------


def render_saved(result: dict) -> None:
    stepper(3, completed=True)
    intervention = result["intervention"]
    notification = result["notification"]
    st.success(f"Intervention {intervention['reference']} validée et enregistrée dans la base de données.",
               icon=":material/check_circle:")
    left, right = st.columns([1.3, 1])
    with left, st.container(border=True):
        st.markdown(f"**{intervention['reference']}** · {intervention['building_name']}")
        st.markdown(f"{intervention['equipment_code']} - {intervention['equipment_name']} · {intervention['status_label']}")
        corrected = result["corrected_fields"]
        st.caption(
            f"Champs corrigés lors de la vérification : {', '.join(corrected)}"
            if corrected
            else "Aucune correction : l'extraction a été validée telle quelle."
        )
        if intervention["summary"]:
            st.markdown("---")
            st.markdown(intervention["summary"])
    with right, st.container(border=True):
        st.markdown("**Notification de suivi (n8n)**")
        if notification is None:
            st.info("Aucun suivi requis : aucune notification n'est déclenchée.")
        elif notification["status"] == "simulated":
            st.info("Mode démo : la notification de suivi a été simulée. Aucun e-mail n'a été envoyé.")
        elif notification["status"] == "dispatched":
            st.success("Notification transmise au workflow n8n. L'envoi de l'e-mail est confirmé par n8n (voir Automatisations).")
        elif notification["status"] == "not_configured":
            st.warning(f"Suivi requis, mais la notification n'a pas été envoyée : {notification['last_error']}.")
        else:
            st.error(f"Transmission à n8n en échec : {notification['last_error']}. Relance possible depuis Automatisations.")
        st.markdown("**Et ensuite ?**")
        st.page_link("pages/dashboard.py", label="Voir le tableau de bord mis à jour", icon=":material/space_dashboard:")
        st.page_link("pages/interventions.py", label="Voir le registre des interventions", icon=":material/build:")
        st.page_link("pages/ai_assistant.py", label="Interroger l'assistant IA", icon=":material/forum:")
        if st.button("Analyser un autre rapport", type="primary", icon=":material/upload_file:"):
            reset()
            st.rerun()


# ---------------------------------------------------------------------------------------------
# Step 1 - upload
# ---------------------------------------------------------------------------------------------


def render_upload() -> None:
    stepper(0)
    with st.container(border=True):
        st.markdown("**Téléverser un rapport PDF**")
        uploaded = st.file_uploader("Rapport d'intervention (PDF, 10 Mo maximum)", type=["pdf"])
        if st.button("Analyser ce rapport", type="primary", disabled=uploaded is None, icon=":material/auto_awesome:"):
            try:
                start(api.upload_report(uploaded.name, uploaded.getvalue()))
            except ApiError as error:
                show_api_error(error)

    try:
        status = api.automation_status()
        jobs = api.jobs(10)
    except ApiError:
        return
    metrics = status["metrics"]
    st.write("")
    with st.container(border=True):
        st.markdown("**Qualité mesurée sur les analyses réalisées**")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Rapports analysés", metrics["jobs_processed_successfully"])
        m2.metric("Validations humaines", metrics["approvals"])
        rate = metrics["field_correction_rate"]
        m3.metric("Taux de champs corrigés", f"{rate:.1%}" if rate is not None else "-",
                  help="Part des 12 champs modifiés par le valideur avant enregistrement.")
        avg = metrics["average_processing_ms"]
        m4.metric("Temps moyen d'analyse", format_duration(avg) if avg else "-")
        if jobs:
            history = pd.DataFrame(
                [
                    {
                        "Fichier": j["original_filename"],
                        "Statut": j["status"],
                        "Moteur": j["ai_engine"] or "-",
                        "Méthode": METHODS.get(j["extraction_method"] or "", "-"),
                        "Champs corrigés": len(j["corrected_fields"]) if j["corrected_fields"] is not None else "",
                        "Durée (ms)": j["processing_ms"],
                        "Créé le": j["created_at"][:16].replace("T", " "),
                    }
                    for j in jobs
                ]
            )
            with st.expander("Historique des analyses"):
                st.dataframe(history, hide_index=True, width="stretch")


# ---------------------------------------------------------------------------------------------
# Step 2 - processing
# ---------------------------------------------------------------------------------------------


def wait_for_processing(job: dict) -> dict:
    stepper(1)
    route = "transmis au workflow n8n" if job["dispatch_mode"] == "n8n" else "traité directement par l'API"
    with st.status(f"Analyse de « {job['original_filename']} » en cours…", expanded=True) as status:
        st.write(f"Document reçu et {route}.")
        st.write("Extraction du texte (PyMuPDF, OCR si nécessaire), puis extraction structurée des informations.")
        deadline = time.monotonic() + 180
        while job["status"] in PENDING_STATUSES and time.monotonic() < deadline:
            time.sleep(1.0)
            job = api.job(job["job_id"])
        if job["status"] in PENDING_STATUSES:
            status.update(label="L'analyse prend plus de temps que prévu.", state="error")
        else:
            status.update(label="Analyse terminée", state="complete", expanded=False)
    return job


# ---------------------------------------------------------------------------------------------
# Step 3 - review
# ---------------------------------------------------------------------------------------------


def hint(job: dict, field: str) -> None:
    state = (job.get("grounding") or {}).get(field, "missing")
    st.caption(GROUNDING[state])


def render_review(job: dict, buildings: dict[str, str]) -> None:
    stepper(2)
    draft = job["draft"] or {}
    context = job["review_context"] or {}

    engine = job["ai_engine"] or ""
    engine_badge = (
        badge(f"IA générative : {engine.replace(':', ' · ', 1)}", "ok")
        if engine and engine != "rules"
        else badge("Extraction par règles (sans IA générative)", "warn")
    )
    st.markdown(
        " ".join(
            [
                engine_badge,
                badge(METHODS.get(job["extraction_method"] or "", "-"), "neutral"),
                badge(f"{job['page_count']} page(s)", "neutral"),
                badge(format_duration(job["processing_ms"]), "neutral"),
                badge("Orchestré par n8n" if job["dispatch_mode"] == "n8n" else "Traitement direct", "neutral"),
            ]
        ),
        unsafe_allow_html=True,
    )
    if job["ai_engine_note"]:
        st.caption(job["ai_engine_note"])
    if warning := st.session_state.get("analysis_warning"):
        st.warning(warning)
    if context.get("duplicate_reference"):
        st.warning("Une intervention avec cette référence existe déjà : l'enregistrement sera refusé (doublon).")
    if job["missing_fields"]:
        st.info(f"{len(job['missing_fields'])} information(s) absente(s) du document : laissées vides, sans invention.")

    form_column, context_column = st.columns([1.45, 1])

    with context_column:
        with st.container(border=True):
            st.markdown("**Contexte issu de la base de données**")
            equipment = context.get("matched_equipment")
            if equipment:
                st.markdown(f"Équipement reconnu : **{equipment['code']}** - {equipment['name']}  \n"
                            f"{equipment['building_name']} · {equipment['category']}")
            elif draft.get("equipment_id"):
                st.markdown(f"Équipement **{draft['equipment_id']}** inconnu : il sera créé lors de l'enregistrement.")
            else:
                st.markdown("Aucun identifiant d'équipement extrait.")
            if context.get("equipment_recurring"):
                st.error("Incidents récurrents : cet équipement atteint le seuil de récurrence avec ce rapport.",
                         icon=":material/repeat:")
            if context.get("equipment_history"):
                st.markdown("Dernières interventions sur cet équipement :")
                st.dataframe(
                    pd.DataFrame(context["equipment_history"]).rename(
                        columns={"reference": "Réf.", "date": "Date", "problem_description": "Problème", "status_label": "Statut"}
                    ),
                    hide_index=True,
                    width="stretch",
                )
        with st.expander("Texte extrait du document (transparence)"):
            st.text(job["extracted_text"] or "")

    with form_column, st.form("review_form"):
        st.markdown("**Vérifier et corriger les informations extraites**")
        c1, c2 = st.columns(2)
        with c1:
            reference = st.text_input("N° d'intervention *", value=draft.get("intervention_id") or "")
            hint(job, "intervention_id")
        with c2:
            parsed_date = date.fromisoformat(draft["date"]) if draft.get("date") else None
            intervention_date = st.date_input("Date *", value=parsed_date, format="DD/MM/YYYY")
            hint(job, "date")
        codes = list(buildings)
        resolved = context.get("resolved_building_code")
        with c1:
            building_code = st.selectbox(
                "Bâtiment *", codes, index=codes.index(resolved) if resolved in codes else None,
                format_func=lambda c: buildings[c], placeholder="Sélectionner le bâtiment",
            )
            hint(job, "building")
            if draft.get("building"):
                st.caption(f"Texte du rapport : « {draft['building']} »")
        with c2:
            category = st.selectbox(
                "Catégorie *", CATEGORIES,
                index=CATEGORIES.index(draft["equipment_category"]) if draft.get("equipment_category") in CATEGORIES else None,
                placeholder="Sélectionner la catégorie",
            )
            hint(job, "equipment_category")
        with c1:
            equipment_code = st.text_input("Identifiant équipement *", value=draft.get("equipment_id") or "")
            hint(job, "equipment_id")
        with c2:
            equipment_name = st.text_input("Désignation de l'équipement *", value=draft.get("equipment_name") or "")
            hint(job, "equipment_name")
        with c1:
            technician = st.text_input("Technicien", value=draft.get("technician") or "")
            hint(job, "technician")
        with c2:
            statuses = list(STATUS_OPTIONS)
            status = st.selectbox(
                "Statut *", statuses, format_func=STATUS_OPTIONS.get,
                index=statuses.index(draft["status"]) if draft.get("status") in statuses else None,
                placeholder="Sélectionner le statut",
            )
            hint(job, "status")
        follow_up_value = draft.get("follow_up_required")
        follow_up = st.radio(
            "Suivi nécessaire *", ["Oui", "Non"], horizontal=True,
            index=None if follow_up_value is None else (0 if follow_up_value else 1),
        )
        hint(job, "follow_up_required")
        problem = st.text_area("Problème constaté *", value=draft.get("problem_description") or "")
        hint(job, "problem_description")
        actions = st.text_area("Actions réalisées", value=draft.get("actions_performed") or "")
        hint(job, "actions_performed")
        recommendations = st.text_area("Recommandations du rapport", value=draft.get("recommendations") or "")
        hint(job, "recommendations")

        with st.container(border=True):
            st.markdown("**Résumé de l'intervention (brouillon)**")
            st.markdown(job["draft_summary"] or "-")
            st.caption("Si vous corrigez des champs, le résumé est régénéré à partir des valeurs validées.")

        submitted = st.form_submit_button("Valider et enregistrer l'intervention", type="primary", icon=":material/save:")

    if submitted:
        required = {
            "N° d'intervention": reference.strip(), "Date": intervention_date, "Bâtiment": building_code,
            "Catégorie": category, "Identifiant équipement": equipment_code.strip(),
            "Désignation de l'équipement": equipment_name.strip(), "Statut": status, "Suivi nécessaire": follow_up,
            "Problème constaté": problem.strip(),
        }
        missing = [label for label, value in required.items() if not value]
        if missing:
            st.error("Champs obligatoires à compléter : " + ", ".join(missing))
        else:
            payload = {
                "reference": reference.strip(),
                "date": intervention_date.isoformat(),
                "building_code": building_code,
                "equipment_code": equipment_code.strip(),
                "equipment_name": equipment_name.strip(),
                "equipment_category": category,
                "technician": technician.strip() or None,
                "problem_description": problem.strip(),
                "actions_performed": actions.strip() or None,
                "status": status,
                "follow_up_required": follow_up == "Oui",
                "recommendations": recommendations.strip() or None,
            }
            try:
                st.session_state["analysis_result"] = api.approve(job["job_id"], payload)
                st.rerun()
            except ApiError as error:
                show_api_error(error)

    with st.expander("Rejeter l'extraction"):
        reason = st.text_input("Motif du rejet", placeholder="Ex. document illisible, mauvais rapport…")
        if st.button("Rejeter sans enregistrer", icon=":material/block:"):
            try:
                api.reject(job["job_id"], reason or None)
                reset()
                st.toast("Extraction rejetée : aucune donnée n'a été enregistrée.")
                st.rerun()
            except ApiError as error:
                show_api_error(error)


# ---------------------------------------------------------------------------------------------
# Page state machine
# ---------------------------------------------------------------------------------------------

if result := st.session_state.get("analysis_result"):
    render_saved(result)
    st.stop()

job_id = st.session_state.get("analysis_job_id")
if job_id is None:
    render_upload()
    st.stop()

try:
    job = api.job(job_id)
    if job["status"] in PENDING_STATUSES:
        job = wait_for_processing(job)
        if job["status"] not in PENDING_STATUSES:
            st.rerun()
    buildings = {b["code"]: b["name"] for b in api.buildings()}
except ApiError as error:
    show_api_error(error)
    if st.button("Recommencer"):
        reset()
        st.rerun()
    st.stop()

if job["status"] == "awaiting_review":
    render_review(job, buildings)
elif job["status"] == "failed":
    stepper(1)
    st.error(f"L'analyse a échoué : {job['error_message']}")
    if st.button("Analyser un autre rapport", type="primary"):
        reset()
        st.rerun()
elif job["status"] in PENDING_STATUSES:
    st.warning("Le traitement est toujours en cours. Si n8n orchestre le traitement, vérifiez que le workflow est actif.")
    if st.button("Actualiser"):
        st.rerun()
else:
    st.info(f"Ce traitement est au statut « {job['status']} ».")
    if st.button("Analyser un autre rapport", type="primary"):
        reset()
        st.rerun()

"""Documentation technique: manual library, indexing status, semantic search and removal."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.api_client import ApiError, get_client
from components.ui import flash, page_header, render_flash, show_api_error

STATUS_LABELS = {"indexed": "Indexé", "pending": "Indexation en cours", "failed": "Échec"}

api = get_client()
page_header(
    "Documentation technique",
    "Bibliothèque documentaire",
    "Manuels et procédures indexés (embeddings multilingues + ChromaDB) et utilisés comme sources par l'assistant.",
)
render_flash()

try:
    documents = api.documents()
except ApiError as error:
    show_api_error(error)
    st.stop()

left, right = st.columns([1.6, 1])
with left, st.container(border=True):
    head, refresh = st.columns([4, 1])
    head.markdown(f"**Documents ({len(documents)})**")
    if refresh.button("Actualiser", icon=":material/refresh:"):
        st.rerun()
    if documents:
        table = pd.DataFrame(
            [
                {
                    "Titre": d["title"],
                    "Fichier": d["original_filename"],
                    "Pages": d["page_count"],
                    "Passages indexés": d["chunk_count"],
                    "Statut": STATUS_LABELS.get(d["status"], d["status"]),
                    "Origine": "Exemple fictif" if d["is_sample"] else "Ajouté",
                    "Ajouté le": d["created_at"][:10],
                }
                for d in documents
            ]
        )
        selection = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun",
                                 selection_mode="single-row", key="documents_table")
        if any(d["status"] == "pending" for d in documents):
            st.caption("Indexation en cours (le premier chargement du modèle d'embeddings peut prendre une minute).")
        failed = [d for d in documents if d["status"] == "failed"]
        for document in failed:
            st.error(f"{document['title']} : {document['error_message']}")
        if selection.selection.rows:
            document = documents[selection.selection.rows[0]]
            a1, a2, _ = st.columns([1, 1, 2])
            if a1.button("Réindexer", icon=":material/sync:"):
                try:
                    api.reindex_document(document["id"])
                    flash(f"Réindexation de « {document['title']} » lancée.", "info")
                    st.rerun()
                except ApiError as error:
                    show_api_error(error)
            if a2.button("Supprimer", icon=":material/delete:"):
                try:
                    api.delete_document(document["id"])
                    flash(f"« {document['title']} » supprimé de la bibliothèque et de l'index.")
                    st.rerun()
                except ApiError as error:
                    show_api_error(error)
        else:
            st.caption("Sélectionnez un document pour le réindexer ou le supprimer.")
    else:
        st.info("Aucun document. Ajoutez un manuel technique au format PDF.")

with right, st.container(border=True):
    st.markdown("**Ajouter un document**")
    uploaded = st.file_uploader("Manuel technique (PDF)", type=["pdf"], key="manual_upload")
    if st.button("Ajouter à la bibliothèque", type="primary", disabled=uploaded is None, icon=":material/upload:"):
        try:
            created = api.upload_document(uploaded.name, uploaded.getvalue())
            flash(f"« {created['title']} » ajouté : indexation lancée.")
            st.rerun()
        except ApiError as error:
            show_api_error(error)
    st.caption("N'ajoutez que des documents dont vous détenez les droits d'utilisation.")

st.write("")
with st.container(border=True):
    st.markdown("**Recherche dans la documentation**")
    query = st.text_input("Recherche sémantique", placeholder="Ex. causes d'un déclenchement de disjoncteur")
    if query:
        try:
            result = api.search_documents(query)
        except ApiError as error:
            show_api_error(error)
            st.stop()
        st.caption(f"Modèle d'embeddings : {result['embedding_backend']}")
        if not result["hits"]:
            st.info("Aucun passage indexé.")
        for hit in result["hits"]:
            section = f" · {hit['section']}" if hit["section"] else ""
            st.markdown(f"**{hit['title']}**, page {hit['page']}{section} · similarité {hit['score']:.2f}")
            st.caption(hit["text"][:500] + ("…" if len(hit["text"]) > 500 else ""))

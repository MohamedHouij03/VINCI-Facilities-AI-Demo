"""Assistant IA: questions answered from the maintenance database or the technical documentation (RAG)."""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from components.api_client import ApiError, get_client
from components.ui import badge, page_header

SUGGESTIONS = [
    "Quels équipements présentent le plus de pannes ?",
    "Combien d'interventions ont été réalisées ce mois-ci ?",
    "Quels bâtiments nécessitent le plus de maintenance ?",
    "Quelles interventions nécessitent un suivi ?",
    "Quels problèmes ont été rencontrés sur la climatisation du bâtiment A ?",
    "Que recommande le manuel technique concernant les vibrations anormales ?",
]
MODE_BADGES = {
    "analytics": ("Données de maintenance", "info"),
    "documents": ("Documentation technique", "ok"),
    "unsupported": ("Information non disponible", "neutral"),
}

api = get_client()
page_header(
    "Assistant IA",
    "Assistant de maintenance",
    "Statistiques calculées sur la base des interventions et réponses sourcées issues de la documentation technique.",
)

history: list[dict] = st.session_state.setdefault("assistant_history", [])


def render_answer(response: dict) -> None:
    label, tone = MODE_BADGES[response["mode"]]
    st.markdown(badge(label, tone), unsafe_allow_html=True)
    st.markdown(response["answer"])
    if response["data"]:
        with st.expander(f"Données ({len(response['data'])} ligne(s))", expanded=False):
            st.dataframe(pd.DataFrame(response["data"]), hide_index=True, width="stretch")
    if response["sources"]:
        # Extractive answers already quote the passages: keep the source list collapsed.
        with st.expander(f"Sources ({len(response['sources'])})", expanded="extractive" not in response["engine"]):
            for index, source in enumerate(response["sources"], start=1):
                page = f", page {source['page']}" if source["page"] else ""
                section = f" · {source['section']}" if source["section"] else ""
                st.markdown(f"**[S{index}] {source['title']}**{page}{section}  \n"
                            f"<span class='muted'>Score de similarité : {source['score']:.2f}</span>",
                            unsafe_allow_html=True)
                st.caption(re.sub(r"^(\d+)\.", r"\1\\.", source["excerpt"]))
    if response["disclaimer"]:
        st.caption(f":material/shield: {response['disclaimer']}")
    st.caption(f"{response['engine']} · fonction : {response['tool']}")


top_left, top_right = st.columns([4, 1])
top_left.markdown("**Questions suggérées**")
if history and top_right.button("Effacer la conversation", icon=":material/delete:"):
    history.clear()
    st.rerun()

pending: str | None = None
columns = st.columns(3)
for index, suggestion in enumerate(SUGGESTIONS):
    if columns[index % 3].button(suggestion, key=f"suggestion_{index}", width="stretch"):
        pending = suggestion

for message in history:
    with st.chat_message(message["role"], avatar=":material/person:" if message["role"] == "user" else ":material/smart_toy:"):
        if message["role"] == "user":
            st.markdown(message["content"])
        else:
            render_answer(message["content"])

question = st.chat_input("Posez une question sur les interventions ou la documentation technique…") or pending
if question:
    history.append({"role": "user", "content": question})
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(question)
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        try:
            with st.spinner("Recherche de la réponse…"):
                response = api.ask(question)
            history.append({"role": "assistant", "content": response})
            render_answer(response)
        except ApiError as error:
            history.pop()
            st.error(error.message)

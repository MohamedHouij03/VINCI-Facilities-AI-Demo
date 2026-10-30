"""Plotly figures with one consistent, restrained style.

Single-series charts use the deep marine blue; crimson is reserved for emphasis (recurring incidents,
follow-ups). Values are direct-labelled so identity never relies on colour alone.
"""

from __future__ import annotations

import plotly.graph_objects as go

BASE = "#1E4F93"  # Deep Marine
ACCENT = "#E92436"  # Alizarin Crimson
INK = "#1F2933"
INK_2 = "#52606D"
GRID = "#E1E0D9"
AXIS = "#C3C2B7"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _layout(figure: go.Figure, height: int, horizontal: bool = False) -> go.Figure:
    figure.update_layout(
        height=height,
        margin={"l": 8, "r": 16, "t": 8, "b": 8},
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font={"family": FONT, "size": 12, "color": INK_2},
        hoverlabel={"bgcolor": "#FFFFFF", "bordercolor": GRID, "font": {"color": INK, "family": FONT}},
        bargap=0.35,
        showlegend=False,
    )
    value_axis = {"showgrid": True, "gridcolor": GRID, "gridwidth": 1, "zeroline": False, "tickfont": {"size": 11},
                  "rangemode": "tozero", "dtick": None}
    category_axis = {"showgrid": False, "linecolor": AXIS, "tickfont": {"size": 11, "color": INK_2}}
    if horizontal:
        figure.update_xaxes(**value_axis, visible=False)
        figure.update_yaxes(**category_axis, autorange="reversed", ticksuffix="  ")
    else:
        figure.update_yaxes(**value_axis)
        figure.update_xaxes(**category_axis)
    return figure


def monthly_bar(rows: list[dict]) -> go.Figure:
    figure = go.Figure(
        go.Bar(
            x=[r["label"] for r in rows],
            y=[r["count"] for r in rows],
            marker={"color": BASE, "cornerradius": 4},
            text=[r["count"] for r in rows],
            textposition="outside",
            textfont={"color": INK_2, "size": 11},
            hovertemplate="%{x} : %{y} intervention(s)<extra></extra>",
            cliponaxis=False,
        )
    )
    return _layout(figure, 260)


def horizontal_bar(labels: list[str], values: list[int], colors: list[str] | None = None, unit: str = "intervention(s)") -> go.Figure:
    figure = go.Figure(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker={"color": colors or BASE, "cornerradius": 4},
            text=values,
            textposition="outside",
            textfont={"color": INK_2, "size": 11},
            hovertemplate=f"%{{y}} : %{{x}} {unit}<extra></extra>",
            cliponaxis=False,
            showlegend=False,
        )
    )
    return _layout(figure, max(170, 34 * len(labels) + 30), horizontal=True)


def top_equipment_bar(rows: list[dict]) -> go.Figure:
    labels = [f"{r['equipment_code']} ({r['building_code']})" for r in rows]
    values = [r["count"] for r in rows]
    colors = [ACCENT if r["recurring"] else BASE for r in rows]
    figure = horizontal_bar(labels, values, colors)
    # Legend entries (two series): identity is also given by the "récurrent" mention in the hover.
    figure.update_traces(
        customdata=["incidents récurrents" if r["recurring"] else "" for r in rows],
        hovertemplate="%{y} : %{x} intervention(s) %{customdata}<extra></extra>",
    )
    for name, color in (("Incidents récurrents", ACCENT), ("Autres équipements", BASE)):
        figure.add_trace(go.Bar(x=[None], y=[None], marker={"color": color}, name=name, orientation="h", showlegend=True))
    figure.update_layout(
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "font": {"size": 11}},
        margin={"l": 8, "r": 16, "t": 30, "b": 8},
    )
    return figure

"""Generate the fictional dataset: CSV files, maintenance report PDFs, technical manuals and evaluation sets.

Usage:  python scripts/generate_sample_data.py [--output sample_data]

The output is deterministic (fixed PDF metadata), so regenerating does not change file hashes.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dataset_definition import BUILDINGS, EQUIPMENT, HISTORY, REPORTS  # noqa: E402
from manuals_content import MANUALS  # noqa: E402

PAGE = pymupdf.paper_rect("a4")
CONTENT_RECT = pymupdf.Rect(56, 64, PAGE.width - 56, PAGE.height - 60)
FIXED_DATE = "D:20261029000000"
FOOTER = "Document fictif généré pour une démonstration - aucune donnée réelle - non affilié à VINCI Facilities"

BASE_CSS = """
body { font-family: sans-serif; font-size: 10.5pt; color: #222; line-height: 1.35; }
h1 { font-size: 16pt; color: #9b1c1c; margin: 0 0 6pt 0; }
h2 { font-size: 12pt; color: #333; margin: 12pt 0 4pt 0; }
h3 { font-size: 11pt; color: #444; margin: 8pt 0 3pt 0; }
p { margin: 0 0 6pt 0; }
.note { font-size: 9pt; color: #777; font-style: italic; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 8pt 0; }
th { background-color: #f1f1f1; text-align: left; padding: 3pt; border: 1px solid #ccc; font-size: 9.5pt; }
td { padding: 3pt; border: 1px solid #ccc; font-size: 9.5pt; vertical-align: top; }
.fields { background-color: #f7f7f7; border: 1px solid #d5d5d5; padding: 6pt 8pt; margin-bottom: 6pt; }
p.field { margin: 0 0 4pt 0; border-bottom: 1px solid #e3e3e3; padding-bottom: 3pt; }
.banner { font-size: 9pt; color: #555; margin-bottom: 10pt; }
"""


def _new_document() -> pymupdf.Document:
    return pymupdf.open()


def _add_html_page(document: pymupdf.Document, body: str) -> None:
    page = document.new_page(width=PAGE.width, height=PAGE.height)
    spare, _scale = page.insert_htmlbox(CONTENT_RECT, body, css=BASE_CSS, scale_low=1)
    if spare < 0:
        raise ValueError("Page content does not fit on one page; shorten it or split it.")


def _decorate(document: pymupdf.Document, header: str) -> None:
    total = document.page_count
    for number, page in enumerate(document, start=1):
        page.insert_text((56, 40), header, fontsize=8, color=(0.45, 0.45, 0.45))
        page.insert_text((56, PAGE.height - 30), FOOTER, fontsize=7, color=(0.5, 0.5, 0.5))
        page.insert_text((PAGE.width - 100, PAGE.height - 30), f"Page {number}/{total}", fontsize=8, color=(0.4, 0.4, 0.4))


def _save(document: pymupdf.Document, path: Path, title: str) -> None:
    document.set_metadata(
        {
            "title": title,
            "author": "Données fictives - prototype de démonstration",
            "subject": "Document fictif",
            "creator": "generate_sample_data.py",
            "producer": "PyMuPDF",
            "creationDate": FIXED_DATE,
            "modDate": FIXED_DATE,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path, garbage=4, deflate=True, no_new_id=True)
    document.close()


# ---------------------------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------------------------


def _structured_report_html(report: dict) -> str:
    rows = "".join(
        f'<p class="field"><b>{html.escape(label)} :</b> {html.escape(value)}</p>'
        for label, value in report["fields"].items()
    )
    sections = "".join(
        f"<h2>{html.escape(title)} :</h2><p>{html.escape(text)}</p>" for title, text in report["sections"].items()
    )
    return (
        "<h1>RAPPORT D'INTERVENTION - MAINTENANCE</h1>"
        '<p class="banner">Service maintenance multitechnique (prestataire fictif) - formulaire de démonstration</p>'
        f'<div class="fields">{rows}</div>{sections}'
        "<p>&nbsp;</p><p>Signature du technicien : ____________________</p>"
        "<p>Visa du responsable de site : ____________________</p>"
    )


def _narrative_report_html(report: dict) -> str:
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in report["paragraphs"])
    return f"<h1>{html.escape(report['heading'])}</h1>{paragraphs}"


def render_report(report: dict, path: Path) -> None:
    document = _new_document()
    if report["layout"] == "narrative":
        _add_html_page(document, _narrative_report_html(report))
    else:
        _add_html_page(document, _structured_report_html(report))
    _decorate(document, "Maintenance multitechnique - rapport d'intervention (fictif)")
    if report["layout"] == "scanned":
        # Rasterise the page and rebuild an image-only PDF, as a scanner would: no text layer remains.
        pixmap = document[0].get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
        document.close()
        document = _new_document()
        page = document.new_page(width=PAGE.width, height=PAGE.height)
        page.insert_image(page.rect, pixmap=pixmap)
    _save(document, path, report["title"])


# ---------------------------------------------------------------------------------------------
# Manuals and CSV files
# ---------------------------------------------------------------------------------------------


def render_manual(manual: dict, path: Path) -> None:
    document = _new_document()
    for body in manual["pages"]:
        _add_html_page(document, body)
    _decorate(document, manual["title"])
    _save(document, path, manual["title"])


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def history_rows() -> list[dict]:
    equipment_building = {e["code"]: e["building_code"] for e in EQUIPMENT}
    rows = []
    for number, item in enumerate(sorted(HISTORY, key=lambda h: (h[0], h[1])), start=1001):
        date, equipment, technician, problem, actions, status, follow_up, completed, recommendations = item
        rows.append(
            {
                "reference": f"RI-2026-{number}",
                "date": date,
                "building_code": equipment_building[equipment],
                "equipment_code": equipment,
                "technician": technician,
                "problem_description": problem,
                "actions_performed": actions,
                "status": status,
                "follow_up_required": "oui" if follow_up else "non",
                "follow_up_completed_at": completed or "",
                "recommendations": recommendations or "",
            }
        )
    return rows


RAG_QUESTIONS = [
    {"question": "Que recommande le manuel technique concernant les vibrations anormales ?", "document": "manuel_cta_ax400.pdf", "evidence": "remplacer les roulements"},
    {"question": "Quelles sont les causes possibles d'une vibration anormale sur une CTA ?", "document": "manuel_cta_ax400.pdf", "evidence": "desequilibre de la turbine"},
    {"question": "À quelle fréquence faut-il remplacer les filtres de la centrale de traitement d'air ?", "document": "manuel_cta_ax400.pdf", "evidence": "tous les 6 mois"},
    {"question": "Pourquoi une climatisation ne refroidit plus ?", "document": "guide_groupes_froids_climatisation.pdf", "evidence": "condenseur encrasse"},
    {"question": "Qui est autorisé à manipuler les fluides frigorigènes ?", "document": "guide_groupes_froids_climatisation.pdf", "evidence": "attestation de capacite"},
    {"question": "Que faire en cas de déclenchement haute pression du groupe froid ?", "document": "guide_groupes_froids_climatisation.pdf", "evidence": "pressostat hp"},
    {"question": "Comment identifier la cause d'un déclenchement récurrent de disjoncteur ?", "document": "guide_tableaux_electriques_bt.pdf", "evidence": "sectionnement"},
    {"question": "Quelle habilitation faut-il pour intervenir sur un tableau électrique ?", "document": "guide_tableaux_electriques_bt.pdf", "evidence": "habilitation electrique"},
    {"question": "Comment rechercher une fuite sur un circuit de chauffage ?", "document": "guide_reseaux_hydrauliques_chauffage.pdf", "evidence": "par troncons"},
    {"question": "Quelle est la pression de service habituelle d'un circuit de chauffage ?", "document": "guide_reseaux_hydrauliques_chauffage.pdf", "evidence": "entre 1 et 2 bar"},
    {"question": "Quelle est la température maximale recommandée dans une salle serveurs ?", "document": "procedure_salles_techniques_serveurs.pdf", "evidence": "18 a 27"},
    {"question": "Que faire si la température de la salle serveurs dépasse le seuil d'alarme ?", "document": "procedure_salles_techniques_serveurs.pdf", "evidence": "climatiseur mobile"},
    {"question": "Quel est le prix d'un ascenseur neuf ?", "document": None, "evidence": None},
    {"question": "Quelle est la procédure de nettoyage des panneaux photovoltaïques ?", "document": None, "evidence": None},
    {"question": "Combien coûte un contrat de maintenance annuel ?", "document": None, "evidence": None},
    {"question": "Comment entretenir une toiture végétalisée ?", "document": None, "evidence": None},
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "sample_data")
    args = parser.parse_args()
    out: Path = args.output

    write_csv(out / "buildings.csv", BUILDINGS)
    write_csv(out / "equipment.csv", EQUIPMENT)
    write_csv(out / "interventions.csv", history_rows())

    for report in REPORTS:
        render_report(report, out / "reports" / report["file"])
    catalog = [{"file": r["file"], "title": r["title"], "layout": r["layout"]} for r in REPORTS]
    (out / "reports" / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    truth = {r["file"]: r["truth"] for r in REPORTS}
    (out / "evaluation").mkdir(parents=True, exist_ok=True)
    (out / "evaluation" / "extraction_ground_truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "evaluation" / "rag_questions.json").write_text(
        json.dumps(RAG_QUESTIONS, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for manual in MANUALS:
        render_manual(manual, out / "manuals" / manual["file"])

    print(
        f"Generated {len(BUILDINGS)} buildings, {len(EQUIPMENT)} equipment, {len(HISTORY)} interventions, "
        f"{len(REPORTS)} reports and {len(MANUALS)} manuals in {out}"
    )


if __name__ == "__main__":
    main()

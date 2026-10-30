"""Evaluate information extraction on the labelled sample reports.

Usage:
    python scripts/evaluate_extraction.py --engine rules
    python scripts/evaluate_extraction.py --engine gemini      # requires GEMINI_API_KEY (DEMO_MODE is ignored here)
    python scripts/evaluate_extraction.py --engine mistral     # requires MISTRAL_API_KEY

Each of the 12 fields of each report is classified as:
  correct        value extracted and matching the ground truth
  correct_null   field absent from the document and correctly left null
  wrong          value extracted but different from the ground truth
  missed         value present in the document but not extracted
  hallucinated   value extracted although the document does not contain it
Results are written to evaluation/results/extraction_<engine>.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.domain import simplify  # noqa: E402
from backend.schemas.extraction import EXTRACTION_FIELDS, ExtractionResult  # noqa: E402
from backend.services.extraction_service import LLMExtractor, RuleBasedExtractor  # noqa: E402
from backend.services.gemini_service import GeminiClient  # noqa: E402
from backend.services.mistral_service import MistralClient  # noqa: E402
from backend.services.pdf_service import extract_pdf_text  # noqa: E402

EXACT_FIELDS = {"intervention_id", "equipment_id", "date", "status", "equipment_category", "follow_up_required"}
SHORT_TEXT_FIELDS = {"equipment_name", "technician"}
LONG_TEXT_FIELDS = {"problem_description", "actions_performed", "recommendations"}
SHORT_TEXT_THRESHOLD = 0.6
LONG_TEXT_THRESHOLD = 0.5
STOPWORDS = {"de", "du", "des", "la", "le", "les", "et", "a", "au", "aux", "en", "un", "une", "sur", "pour", "par", "l", "d"}


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", simplify(text)) if t not in STOPWORDS]


def token_f1(expected: str, predicted: str) -> float:
    expected_tokens, predicted_tokens = Counter(tokens(expected)), Counter(tokens(predicted))
    overlap = sum((expected_tokens & predicted_tokens).values())
    if not overlap:
        return 0.0
    precision = overlap / sum(predicted_tokens.values())
    recall = overlap / sum(expected_tokens.values())
    return 2 * precision * recall / (precision + recall)


def load_building_resolver() -> callable:
    with (ROOT / "sample_data" / "buildings.csv").open(encoding="utf-8") as handle:
        buildings = list(csv.DictReader(handle))

    def resolve(text: str | None) -> str | None:
        if not text:
            return None
        simplified = simplify(text)
        if match := re.search(r"\bbatiment\s+([a-z])\b", simplified):
            return f"BAT-{match.group(1).upper()}"
        for building in buildings:
            if simplify(building["name"]).split(" - ", 1)[-1] in simplified:
                return building["code"]
        return None

    return resolve


def compare(field: str, expected: object, predicted: object, resolve_building) -> tuple[str, float | None]:
    if field == "building":
        predicted = resolve_building(predicted)  # compared at the level of the building code
    if expected is None:
        return ("correct_null" if predicted is None else "hallucinated"), None
    if predicted is None:
        return "missed", 0.0 if field in LONG_TEXT_FIELDS | SHORT_TEXT_FIELDS else None
    if field in SHORT_TEXT_FIELDS | LONG_TEXT_FIELDS:
        score = token_f1(str(expected), str(predicted))
        threshold = SHORT_TEXT_THRESHOLD if field in SHORT_TEXT_FIELDS else LONG_TEXT_THRESHOLD
        return ("correct" if score >= threshold else "wrong"), round(score, 3)
    return ("correct" if str(expected) == str(predicted) else "wrong"), None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engine", choices=["rules", "gemini", "mistral"], default="rules")
    parser.add_argument("--model", default=None, help="model name (defaults to GEMINI_MODEL / MISTRAL_MODEL)")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="pause between documents in seconds (free tier: about 13 s for 5 requests/minute)")
    args = parser.parse_args()

    settings = Settings()
    if args.engine == "gemini":
        if not settings.gemini_api_key:
            sys.exit("GEMINI_API_KEY is not set: cannot evaluate the Gemini engine.")
        extractor = LLMExtractor(GeminiClient(settings.gemini_api_key, args.model or settings.gemini_model, max_attempts=5))
        engine_name = extractor.name
    elif args.engine == "mistral":
        if not settings.mistral_api_key:
            sys.exit("MISTRAL_API_KEY is not set: cannot evaluate the Mistral engine.")
        extractor = LLMExtractor(MistralClient(settings.mistral_api_key, args.model or settings.mistral_model, max_attempts=5))
        engine_name = extractor.name
    else:
        extractor = RuleBasedExtractor()
        engine_name = "rules"

    truth = json.loads((ROOT / "sample_data" / "evaluation" / "extraction_ground_truth.json").read_text(encoding="utf-8"))
    catalog = {e["file"]: e["layout"] for e in json.loads((ROOT / "sample_data" / "reports" / "catalog.json").read_text(encoding="utf-8"))}
    resolve_building = load_building_resolver()

    per_document = []
    outcome_by_field: dict[str, Counter] = defaultdict(Counter)
    outcome_by_layout: dict[str, Counter] = defaultdict(Counter)
    text_scores: dict[str, list[float]] = defaultdict(list)
    timings = []

    for index, (filename, expected) in enumerate(truth.items()):
        if index and args.delay:
            time.sleep(args.delay)  # pacing is excluded from the measured processing time
        data = (ROOT / "sample_data" / "reports" / filename).read_bytes()
        started = time.perf_counter()
        pdf = extract_pdf_text(data, settings)
        extracted_at = time.perf_counter()
        output = extractor.extract(pdf.text)
        result: ExtractionResult = output[0] if isinstance(output, tuple) else output
        finished = time.perf_counter()
        predicted = result.model_dump(mode="json")

        fields = {}
        for field in EXTRACTION_FIELDS:
            outcome, score = compare(field, expected[field], predicted[field], resolve_building)
            fields[field] = {"expected": expected[field], "predicted": predicted[field], "outcome": outcome, "token_f1": score}
            outcome_by_field[field][outcome] += 1
            outcome_by_layout[catalog[filename]][outcome] += 1
            if score is not None:
                text_scores[field].append(score)
        timing = {"pdf_ms": round((extracted_at - started) * 1000, 1), "extraction_ms": round((finished - extracted_at) * 1000, 1)}
        timings.append(timing["pdf_ms"] + timing["extraction_ms"])
        per_document.append({"file": filename, "layout": catalog[filename], "method": pdf.method, **timing, "fields": fields})

    total = Counter()
    for counter in outcome_by_field.values():
        total.update(counter)
    n_fields = sum(total.values())
    correct = total["correct"] + total["correct_null"]
    expected_null = total["correct_null"] + total["hallucinated"]

    def accuracy(counter: Counter) -> float:
        return round((counter["correct"] + counter["correct_null"]) / sum(counter.values()), 4)

    summary = {
        "engine": engine_name,
        "evaluated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "documents": len(per_document),
        "fields_evaluated": n_fields,
        "field_accuracy": round(correct / n_fields, 4),
        "accuracy_by_field": {field: accuracy(counter) for field, counter in outcome_by_field.items()},
        "accuracy_by_layout": {layout: accuracy(counter) for layout, counter in outcome_by_layout.items()},
        "outcomes": dict(total),
        "missing_field_detection": {
            "fields_absent_from_documents": expected_null,
            "correctly_left_null": total["correct_null"],
            "hallucinated_values": total["hallucinated"],
            "null_recall": round(total["correct_null"] / expected_null, 4) if expected_null else None,
        },
        "estimated_correction_rate": round(1 - correct / n_fields, 4),
        "mean_token_f1": {field: round(statistics.mean(scores), 3) for field, scores in text_scores.items()},
        "processing_time_ms": {
            "mean": round(statistics.mean(timings), 1),
            "median": round(statistics.median(timings), 1),
            "max": round(max(timings), 1),
        },
        "documents_detail": per_document,
    }

    out_dir = ROOT / "evaluation" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"extraction_{args.engine}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"Engine: {engine_name} - {len(per_document)} documents, {n_fields} fields")
    print(f"Field-level accuracy: {summary['field_accuracy']:.1%}")
    print("Accuracy by layout: " + ", ".join(f"{k} {v:.1%}" for k, v in summary["accuracy_by_layout"].items()))
    print(f"Outcomes: {dict(total)}")
    print(f"Missing-field detection: {summary['missing_field_detection']}")
    print(f"Processing time (ms): {summary['processing_time_ms']}")
    print("Per field: " + ", ".join(f"{k} {v:.0%}" for k, v in summary["accuracy_by_field"].items()))
    print(f"Saved to {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

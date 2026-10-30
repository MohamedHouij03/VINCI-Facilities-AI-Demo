"""Evaluate retrieval (Recall@k, MRR), source citation and rejection of unsupported questions.

Usage:
    python scripts/evaluate_rag.py                       # sentence-transformers model from EMBEDDING_MODEL
    python scripts/evaluate_rag.py --backend hashing     # lexical baseline

The manuals are indexed in a temporary ChromaDB directory (application data is not modified).
A retrieved passage counts as relevant when it comes from the expected document AND contains the
expected evidence phrase (accent- and case-insensitive).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.domain import simplify  # noqa: E402
from backend.services.pdf_service import extract_page_blocks  # noqa: E402
from backend.services.rag_service import HashingEmbedder, RagService, SentenceTransformerEmbedder  # noqa: E402

K_VALUES = (1, 3, 5)
THRESHOLDS = {
    "sentence-transformers": (0.80, 0.82, 0.83, 0.84, 0.85, 0.86),
    "hashing": (0.25, 0.30, 0.35, 0.40),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=["sentence-transformers", "hashing"], default="sentence-transformers")
    args = parser.parse_args()

    # ChromaDB keeps its files open on Windows: tolerate a failed cleanup of the temporary index.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(data_dir=Path(tmp), embedding_backend=args.backend)
        embedder = HashingEmbedder() if args.backend == "hashing" else SentenceTransformerEmbedder(settings.embedding_model)
        rag = RagService(settings, embedder)
        rag_min_score = rag.min_score

        manuals = sorted((ROOT / "sample_data" / "manuals").glob("*.pdf"))
        document_files: dict[int, str] = {}
        started = time.perf_counter()
        for document_id, path in enumerate(manuals, start=1):
            rag.index_document(document_id, path.stem, extract_page_blocks(path.read_bytes(), settings))
            document_files[document_id] = path.name
        indexing_seconds = time.perf_counter() - started

        questions = json.loads((ROOT / "sample_data" / "evaluation" / "rag_questions.json").read_text(encoding="utf-8"))
        rows = []
        latencies = []
        for item in questions:
            started = time.perf_counter()
            hits = rag.search(item["question"], top_k=max(K_VALUES))
            latencies.append((time.perf_counter() - started) * 1000)
            relevant_rank = None
            document_rank = None
            for rank, hit in enumerate(hits, start=1):
                same_document = document_files[hit.document_id] == item["document"]
                if same_document and document_rank is None:
                    document_rank = rank
                if same_document and item["evidence"] and simplify(item["evidence"]) in simplify(hit.text):
                    relevant_rank = relevant_rank or rank
            context = rag.select_context(hits)
            extractive = rag._extractive(item["question"], context) if context else None
            rows.append(
                {
                    "question": item["question"],
                    "answerable": item["document"] is not None,
                    "expected_document": item["document"],
                    "relevant_rank": relevant_rank,
                    "document_rank": document_rank,
                    "top1_score": hits[0].score if hits else 0.0,
                    "top1_document": document_files[hits[0].document_id] if hits else None,
                    "top1_page": hits[0].page if hits else None,
                    "context_passages": len(context),
                    "cited_document": document_files[extractive.sources[0].document_id] if extractive else None,
                    "cited_evidence": bool(
                        extractive and item["evidence"] and simplify(item["evidence"]) in simplify(extractive.answer)
                    ),
                }
            )

    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]

    def recall(key: str, k: int) -> float:
        return round(sum(1 for r in answerable if r[key] and r[key] <= k) / len(answerable), 4)

    def rejection(threshold: float) -> dict:
        accepted_answerable = sum(1 for r in answerable if r["top1_score"] >= threshold)
        rejected_unanswerable = sum(1 for r in unanswerable if r["top1_score"] < threshold)
        return {
            "threshold": threshold,
            "answerable_accepted": f"{accepted_answerable}/{len(answerable)}",
            "unsupported_rejected": f"{rejected_unanswerable}/{len(unanswerable)}",
            "accuracy": round((accepted_answerable + rejected_unanswerable) / len(rows), 4),
        }

    summary = {
        "embedding_backend": args.backend,
        "embedding_model": embedder.name,
        "evaluated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "questions": {"answerable": len(answerable), "unsupported": len(unanswerable)},
        "recall_at_k": {f"@{k}": recall("relevant_rank", k) for k in K_VALUES},
        "document_recall_at_k": {f"@{k}": recall("document_rank", k) for k in K_VALUES},
        "mrr": round(statistics.mean(1 / r["relevant_rank"] if r["relevant_rank"] else 0 for r in answerable), 4),
        "citation_correct_top_source": round(sum(1 for r in answerable if r["cited_document"] == r["expected_document"]) / len(answerable), 4),
        "extractive_answer_contains_evidence": round(sum(1 for r in answerable if r["cited_evidence"]) / len(answerable), 4),
        "score_distribution": {
            "answerable_top1_min": min(r["top1_score"] for r in answerable),
            "answerable_top1_mean": round(statistics.mean(r["top1_score"] for r in answerable), 4),
            "unsupported_top1_max": max(r["top1_score"] for r in unanswerable),
            "unsupported_top1_mean": round(statistics.mean(r["top1_score"] for r in unanswerable), 4),
        },
        "rejection_by_threshold": [rejection(t) for t in THRESHOLDS[args.backend]],
        "configured_threshold": rejection(rag_min_score),
        "indexing_seconds": round(indexing_seconds, 2),
        "search_latency_ms_mean": round(statistics.mean(latencies), 1),
        "details": rows,
    }

    out_dir = ROOT / "evaluation" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"rag_{args.backend}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Backend: {args.backend} ({embedder.name}) - {len(answerable)} answerable + {len(unanswerable)} unsupported questions")
    print(f"Passage Recall@k: {summary['recall_at_k']}  |  Document Recall@k: {summary['document_recall_at_k']}  |  MRR: {summary['mrr']}")
    print(f"Top cited source is the expected document: {summary['citation_correct_top_source']:.0%}")
    print(f"Extractive answer quotes the expected evidence: {summary['extractive_answer_contains_evidence']:.0%}")
    print(f"Top-1 scores: {summary['score_distribution']}")
    for line in summary["rejection_by_threshold"]:
        print(f"  threshold {line['threshold']:.2f}: answerable accepted {line['answerable_accepted']}, "
              f"unsupported rejected {line['unsupported_rejected']}, accuracy {line['accuracy']:.0%}")
    print(f"Configured threshold (RAG_MIN_SCORE): {summary['configured_threshold']}")
    print(f"Saved to {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

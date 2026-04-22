"""
Retrieval evaluation script for the Danish Legal RAG system.

Compares dense vs hybrid retrieval on a fixed set of evaluation questions.
Primary metrics: MRR (Mean Reciprocal Rank) and Recall@1.

Usage (inside docker):
  docker compose exec api python -m tests.eval_retrieval --strategy dense
  docker compose exec api python -m tests.eval_retrieval --strategy hybrid

Or run both:
  docker compose exec api python -m tests.eval_retrieval --compare
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def load_questions() -> list[dict]:
    """Load eval questions from JSON fixture."""
    candidates = [
        Path(__file__).parent / "eval_questions.json",
        Path("/app/tests/eval_questions.json"),
    ]
    for p in candidates:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError("eval_questions.json not found")


def run_eval(strategy: str, limit: int = 5) -> dict:
    """
    Run retrieval evaluation for one strategy.

    Returns dict with:
      - per_question: list of {id, category, hypothesis, rank, hit}
      - mrr: float
      - recall_at_1: float
      - by_category: {category: {mrr, recall_at_1, count}}
    """
    from ingest.embedder import get_embedding_provider
    from shared.qdrant_utils import get_qdrant_client, search_similar

    embedder = get_embedding_provider()
    qdrant = get_qdrant_client()

    # For hybrid, we also need the sparse provider
    sparse_provider = None
    if strategy == "hybrid":
        from shared.sparse import get_sparse_provider
        sparse_provider = get_sparse_provider()

    questions = load_questions()
    per_question = []

    for q in questions:
        query_vector = embedder.embed_single(q["question"])

        sparse_vec = None
        if sparse_provider is not None:
            sparse_vec = sparse_provider.embed_single(q["question"])

        results = search_similar(
            qdrant,
            query_vector=query_vector,
            limit=limit,
            sparse_vector=sparse_vec,
        )

        # Find rank of first acceptable section in results
        acceptable = set(q["acceptable_sections"])
        rank = None
        for i, r in enumerate(results, 1):
            section = r["payload"].get("section", "")
            if section in acceptable:
                rank = i
                break

        per_question.append({
            "id": q["id"],
            "category": q["category"],
            "hypothesis": q["hypothesis"],
            "rank": rank,
            "hit": rank is not None,
            "top_section": results[0]["payload"].get("section", "") if results else "",
            "top_score": results[0]["score"] if results else 0.0,
        })

    # Compute metrics
    mrr = _compute_mrr(per_question)
    recall_at_1 = _compute_recall_at_k(per_question, k=1)

    # Break down by category
    categories = {}
    for cat in ("terminology", "paraphrase", "mixed"):
        cat_qs = [pq for pq in per_question if pq["category"] == cat]
        if cat_qs:
            categories[cat] = {
                "mrr": _compute_mrr(cat_qs),
                "recall_at_1": _compute_recall_at_k(cat_qs, k=1),
                "count": len(cat_qs),
            }

    return {
        "strategy": strategy,
        "per_question": per_question,
        "mrr": mrr,
        "recall_at_1": recall_at_1,
        "by_category": categories,
        "total_questions": len(questions),
    }


def _compute_mrr(results: list[dict]) -> float:
    """Mean Reciprocal Rank."""
    if not results:
        return 0.0
    rr_sum = 0.0
    for r in results:
        if r["rank"] is not None:
            rr_sum += 1.0 / r["rank"]
    return rr_sum / len(results)


def _compute_recall_at_k(results: list[dict], k: int = 1) -> float:
    """Recall@k: fraction of questions where a relevant section is in top-k."""
    if not results:
        return 0.0
    hits = sum(1 for r in results if r["rank"] is not None and r["rank"] <= k)
    return hits / len(results)


def print_report(result: dict) -> None:
    """Pretty-print eval results."""
    print(f"\n{'='*60}")
    print(f"Strategy: {result['strategy'].upper()}")
    print(f"{'='*60}")
    print(f"  MRR:        {result['mrr']:.3f}")
    print(f"  Recall@1:   {result['recall_at_1']:.3f}")
    print(f"  Questions:  {result['total_questions']}")
    print()

    for cat, stats in result["by_category"].items():
        print(f"  [{cat}] (n={stats['count']})")
        print(f"    MRR:      {stats['mrr']:.3f}")
        print(f"    Recall@1: {stats['recall_at_1']:.3f}")

    print(f"\n  Per-question detail:")
    for pq in result["per_question"]:
        rank_str = str(pq["rank"]) if pq["rank"] is not None else "MISS"
        print(
            f"    {pq['id']:10s}  rank={rank_str:>4s}  "
            f"top={pq['top_section']:>8s}  "
            f"score={pq['top_score']:.3f}  "
            f"cat={pq['category']}"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality")
    parser.add_argument(
        "--strategy",
        choices=["dense", "hybrid"],
        help="Run a single strategy",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run both dense and hybrid, then compare",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of results to retrieve per question (default: 5)",
    )
    args = parser.parse_args()

    if not args.strategy and not args.compare:
        parser.error("Specify --strategy or --compare")

    if args.compare:
        dense_result = run_eval("dense", limit=args.limit)
        print_report(dense_result)

        # Check if hybrid is possible
        from qdrant_client import QdrantClient
        from shared.qdrant_utils import COLLECTION_NAME
        host = os.environ.get("QDRANT_HOST", "localhost")
        port = int(os.environ.get("QDRANT_PORT", "6333"))
        client = QdrantClient(host=host, port=port)
        info = client.get_collection(COLLECTION_NAME)
        has_sparse = (
            info.config.params.sparse_vectors is not None
            and "bm25" in (info.config.params.sparse_vectors or {})
        )

        if not has_sparse:
            print("SKIP: Cannot run hybrid eval — collection has no sparse vectors.")
            print("Re-ingest with RETRIEVAL_STRATEGY=hybrid to enable.")
            return

        hybrid_result = run_eval("hybrid", limit=args.limit)
        print_report(hybrid_result)

        # Summary comparison
        print(f"\n{'='*60}")
        print("COMPARISON SUMMARY")
        print(f"{'='*60}")
        print(f"  {'Metric':<15s} {'Dense':>8s} {'Hybrid':>8s} {'Delta':>8s}")
        print(f"  {'-'*15} {'-'*8} {'-'*8} {'-'*8}")

        for metric in ("mrr", "recall_at_1"):
            d = dense_result[metric]
            h = hybrid_result[metric]
            delta = h - d
            sign = "+" if delta >= 0 else ""
            print(f"  {metric:<15s} {d:>8.3f} {h:>8.3f} {sign}{delta:>7.3f}")

        # Terminology split check
        term_dense = dense_result["by_category"].get("terminology", {})
        term_hybrid = hybrid_result["by_category"].get("terminology", {})
        if term_dense and term_hybrid:
            d_mrr = term_dense["mrr"]
            h_mrr = term_hybrid["mrr"]
            print(f"\n  Terminology split: dense MRR={d_mrr:.3f}, hybrid MRR={h_mrr:.3f}")
            if h_mrr <= d_mrr:
                print("  WARNING: Hybrid does NOT beat dense on terminology questions.")
                print("  Do NOT switch default to hybrid.")
            else:
                print(f"  Hybrid wins on terminology by +{h_mrr - d_mrr:.3f} MRR.")

    else:
        result = run_eval(args.strategy, limit=args.limit)
        print_report(result)


if __name__ == "__main__":
    main()

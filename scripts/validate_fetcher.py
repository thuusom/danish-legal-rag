"""
Live validation script for the law fetcher (Issue #20).

Hits retsinformation-api.dk against AFL, ARL and SFL, transforms each into
our cached law JSON shape, and prints a structural comparison against the
existing seed file at ``ingest/data/<file>.json``.

This script is intended to be run by hand once per fetcher change. It is
NOT part of CI — running it costs at most 6 calls against the live API
(2 per law: ``versions/latest`` + base for ``eli_uri``), well under the
20/h budget.

Usage::

    LAW_CACHE_DIR=/tmp/lawfetch_validate \\
    python -m scripts.validate_fetcher

The fetched JSON files are written to the cache dir for inspection. The
script prints a per-law summary plus any structural issues that need
human attention before flipping the live fetcher on by default.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Repo root on sys.path so ``ingest.*`` imports work when invoked as a script.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ingest.cache import get_cache_dir, load_sources_manifest  # noqa: E402
from ingest.law_fetcher import (  # noqa: E402
    RetsinformationClient,
    fetch_one,
    write_currency_report,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

WANTED = {"AFL", "ARL", "SFL"}


def _summarise_structure(data: dict) -> dict:
    """Compute a small set of structural counts from a cached law JSON."""
    provisions = data.get("provisions", [])
    sections = sorted({p["section"] for p in provisions if p.get("section")})
    chapters = sorted({p["chapter"] for p in provisions if p.get("chapter")})
    with_subsection = sum(1 for p in provisions if p.get("subsection"))
    return {
        "provisions": len(provisions),
        "sections": len(sections),
        "chapters": len(chapters),
        "with_subsection": with_subsection,
        "law_version_number": data.get("law_version_number"),
        "law_version_date": data.get("law_version_date"),
    }


def main() -> int:
    sources = [s for s in load_sources_manifest() if s.law_code in WANTED]
    if len(sources) != len(WANTED):
        missing = WANTED - {s.law_code for s in sources}
        logger.error(f"sources.yaml missing law codes: {missing}")
        return 1

    cache_dir = get_cache_dir()
    logger.info(f"Validating against cache_dir={cache_dir}")

    report = {"checked_at": None, "sources": []}
    with RetsinformationClient() as client:
        for source in sources:
            entry = fetch_one(source, client, cache_dir, force=True)
            report["sources"].append(entry)

            seed = REPO_ROOT / source.seed_file
            cached = cache_dir / f"{source.law_code}.json"

            seed_data = json.loads(seed.read_text(encoding="utf-8"))
            seed_summary = _summarise_structure(seed_data)

            if entry["status"] in {"new", "updated"}:
                fetched = json.loads(cached.read_text(encoding="utf-8"))
                fetched_summary = _summarise_structure(fetched)
            else:
                fetched_summary = {"status": entry["status"], "error": entry.get("error")}

            logger.info(
                f"\n=== {source.law_code} ({source.short_name}) ===\n"
                f"  status: {entry['status']}\n"
                f"  error: {entry.get('error')}\n"
                f"  seed   {seed_summary}\n"
                f"  fetch  {fetched_summary}"
            )

    write_currency_report(report, cache_dir)
    logger.info(f"Currency report at {cache_dir / 'currency-report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

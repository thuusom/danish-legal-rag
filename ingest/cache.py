"""
Law cache layer.

Introduces a single source of truth for ingestion: the cache directory.
On first boot, the cache is empty and is seeded from the in-repo
``ingest/data/*.json`` files declared in ``ingest/sources.yaml``.
On subsequent boots the cache is reused; the live retsinformation fetcher
(#20) will eventually overwrite cache files with fresh upstream data.

JSON shape inside the cache is identical to the existing seed files —
this module is purely an indirection layer, not a format change.

Cache location is configurable via the ``LAW_CACHE_DIR`` env var.
Default (host): ``./law_cache/``.
Default (Docker, when env is set by compose): ``/cache/laws``.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

# Project root is two levels up from this file (ingest/cache.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CACHE_DIR = REPO_ROOT / "law_cache"
DEFAULT_SOURCES_FILE = REPO_ROOT / "ingest" / "sources.yaml"


class RetsinformationRef(BaseModel):
    """retsinformation-api.dk identifier components used by the live fetcher (#20)."""
    year: int = Field(ge=1900, le=2100)
    number: int = Field(ge=1)


class LawSource(BaseModel):
    """One entry in the sources.yaml manifest."""
    law_code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    short_name: str = Field(min_length=1)
    retsinformation: RetsinformationRef
    seed_file: Path


def get_cache_dir() -> Path:
    """
    Resolve the cache directory.

    Priority:
    1. ``LAW_CACHE_DIR`` env var (set by docker-compose to ``/cache/laws``).
    2. ``./law_cache/`` at the repo root (host-side dev default).

    The directory is created if it does not exist.
    """
    env_value = os.environ.get("LAW_CACHE_DIR")
    cache_dir = Path(env_value) if env_value else DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _resolve_sources_file(path: Optional[Path | str]) -> Path:
    if path is None:
        return DEFAULT_SOURCES_FILE
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def _resolve_seed_file(seed_file: Path) -> Path:
    """Seed file paths in sources.yaml are relative to the repo root."""
    return seed_file if seed_file.is_absolute() else REPO_ROOT / seed_file


def load_sources_manifest(path: Optional[Path | str] = None) -> list[LawSource]:
    """
    Read and validate the sources.yaml manifest.

    Raises:
        FileNotFoundError: if the manifest does not exist.
        ValueError: if the manifest is malformed (missing fields, duplicate
                    law_code, invalid YAML, etc.).
    """
    import yaml  # local import: yaml is only needed when loading the manifest

    manifest_path = _resolve_sources_file(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"sources manifest not found: {manifest_path}")

    with manifest_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict) or "sources" not in raw:
        raise ValueError(f"sources manifest must have a top-level 'sources:' key ({manifest_path})")

    entries = raw["sources"]
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"sources manifest must contain a non-empty list of sources ({manifest_path})")

    parsed: list[LawSource] = []
    seen_codes: set[str] = set()
    for idx, entry in enumerate(entries):
        try:
            source = LawSource.model_validate(entry)
        except ValidationError as exc:
            raise ValueError(f"invalid source entry at index {idx} in {manifest_path}: {exc}") from exc

        if source.law_code in seen_codes:
            raise ValueError(f"duplicate law_code '{source.law_code}' in {manifest_path}")
        seen_codes.add(source.law_code)
        parsed.append(source)

    return parsed


def seed_cache_from_repo(sources_file: Optional[Path | str] = None) -> list[str]:
    """
    Populate the cache from in-repo seed files.

    For each source in the manifest:
      * if ``<cache>/<law_code>.json`` exists, leave it alone (the cache
        wins — it may contain fresher data written by the live fetcher).
      * otherwise, copy ``seed_file`` into the cache.

    Idempotent: calling this on an already-seeded cache is a no-op.

    Returns:
        list of law_codes that were freshly seeded on this call.
    """
    sources = load_sources_manifest(sources_file)
    cache_dir = get_cache_dir()
    seeded: list[str] = []

    for source in sources:
        target = cache_dir / f"{source.law_code}.json"
        if target.exists():
            logger.debug(f"Cache hit for {source.law_code}, leaving in place: {target}")
            continue

        seed_path = _resolve_seed_file(source.seed_file)
        if not seed_path.exists():
            raise FileNotFoundError(
                f"seed file for {source.law_code} not found: {seed_path}"
            )

        shutil.copyfile(seed_path, target)
        logger.info(f"Seeded cache for {source.law_code} from {seed_path.name}")
        seeded.append(source.law_code)

    if seeded:
        logger.info(f"Seeded {len(seeded)} law(s) into cache at {cache_dir}: {seeded}")
    else:
        logger.info(f"Cache already populated at {cache_dir} ({len(sources)} sources)")

    return seeded


def list_cached_laws() -> list[Path]:
    """
    Return paths to every JSON file currently in the cache, sorted by law_code.

    Each entry is a ``<law_code>.json`` file written by either
    :func:`seed_cache_from_repo` or the live fetcher.
    """
    cache_dir = get_cache_dir()
    return sorted(cache_dir.glob("*.json"))

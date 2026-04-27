"""
Shared admin state helpers (Issue #24).

The admin endpoints in ``api/admin.py`` and the ingestion job in
``ingest/main.py`` both need to read or write small JSON state files in the
law cache directory. Centralising the file names and the read/write helpers
here keeps the two services from drifting.

Files this module touches inside ``LAW_CACHE_DIR``:

  ``currency-report.json``     written by ``ingest.law_fetcher`` on every run
                                (read-only here)
  ``.fetcher_state.json``      daily call counter, written by the fetcher
                                (read-only here)
  ``.fetcher_running``         marker file written by the fetcher subprocess
                                while a run is in progress; read by the admin
                                endpoint to enforce the 409 idempotency
  ``.ingestion_state.json``    written by ``ingest/main.py`` at start/end of
                                each run; read by the admin endpoint

All readers tolerate the file being missing — the admin UI must work on a
clean install before the fetcher or ingestion has ever run.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Filenames inside the cache directory. Must stay in sync with
# ingest/law_fetcher.py (STATE_FILE_NAME / CURRENCY_REPORT_NAME) — but those
# constants live in ingest/ which the api container also imports, so we
# re-declare them here purely to avoid pulling in the heavy ingest module
# (httpx, pydantic schemas, etc.) just to read a filename.
CURRENCY_REPORT_FILE = "currency-report.json"
FETCHER_DAILY_STATE_FILE = ".fetcher_state.json"
FETCHER_RUNNING_MARKER = ".fetcher_running"
INGESTION_STATE_FILE = ".ingestion_state.json"


def get_cache_dir() -> Path:
    """Resolve the law cache directory.

    Mirrors :func:`ingest.cache.get_cache_dir` but without importing the
    heavyweight ingest module. The two implementations must stay in sync —
    if ``ingest.cache`` changes its resolution rules, update here too.
    """
    env_value = os.environ.get("LAW_CACHE_DIR")
    if env_value:
        return Path(env_value)
    # Fall back to repo-relative default. shared/ is one level below repo root.
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "law_cache"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Optional[dict]:
    """Read a JSON file, returning ``None`` on missing/corrupt input."""
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Could not parse JSON state at {path}: {exc}")
        return None


def read_currency_report(cache_dir: Optional[Path] = None) -> Optional[dict]:
    """Return the parsed currency report or ``None`` if absent/corrupt."""
    cache_dir = cache_dir or get_cache_dir()
    return _read_json(cache_dir / CURRENCY_REPORT_FILE)


def read_fetcher_daily_counter(cache_dir: Optional[Path] = None) -> dict:
    """Return ``{"date": str|None, "count": int}`` from the daily-counter file.

    Returns the zero-state when the file is missing or yesterday's. The
    fetcher itself uses this same logic; we duplicate it here so reading
    state never has a side effect.
    """
    cache_dir = cache_dir or get_cache_dir()
    raw = _read_json(cache_dir / FETCHER_DAILY_STATE_FILE)
    today = datetime.now(timezone.utc).date().isoformat()
    if not raw or raw.get("date") != today:
        return {"date": today, "count": 0}
    return {"date": raw["date"], "count": int(raw.get("count", 0))}


def is_fetcher_running(cache_dir: Optional[Path] = None) -> bool:
    """Return True if a fetcher run is currently in progress.

    Detection is based on the ``.fetcher_running`` marker file. The file is
    created right before the fetcher subprocess starts and removed when the
    subprocess returns (success, failure, or signal). Stale markers from a
    crashed process are a known limitation — the admin UI surfaces the
    `started_at` field so an operator can identify and (eventually) clear
    them.
    """
    cache_dir = cache_dir or get_cache_dir()
    return (cache_dir / FETCHER_RUNNING_MARKER).exists()


def read_fetcher_marker(cache_dir: Optional[Path] = None) -> Optional[dict]:
    """Read the fetcher running marker contents, if present."""
    cache_dir = cache_dir or get_cache_dir()
    return _read_json(cache_dir / FETCHER_RUNNING_MARKER)


def read_ingestion_state(cache_dir: Optional[Path] = None) -> dict:
    """Return the ingestion state.

    Shape::

        {
          "status": "idle" | "running" | "failed" | "unknown",
          "started_at": "2026-04-27T10:00:00+00:00" | None,
          "last_completed": "2026-04-27T10:05:00+00:00" | None,
          "error": "..." | None
        }

    Returns the ``unknown`` zero-state when the file is missing.
    """
    cache_dir = cache_dir or get_cache_dir()
    raw = _read_json(cache_dir / INGESTION_STATE_FILE)
    if not raw:
        return {
            "status": "unknown",
            "started_at": None,
            "last_completed": None,
            "error": None,
        }
    return {
        "status": raw.get("status", "unknown"),
        "started_at": raw.get("started_at"),
        "last_completed": raw.get("last_completed"),
        "error": raw.get("error"),
    }


# ---------------------------------------------------------------------------
# Writes (used by ingest/main.py and the fetcher subprocess wrapper)
# ---------------------------------------------------------------------------


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_ingestion_started(cache_dir: Optional[Path] = None) -> None:
    """Mark the ingestion as running."""
    cache_dir = cache_dir or get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    existing = read_ingestion_state(cache_dir)
    payload = {
        "status": "running",
        "started_at": _utc_now_iso(),
        "last_completed": existing.get("last_completed"),
        "error": None,
    }
    _write_json_atomic(cache_dir / INGESTION_STATE_FILE, payload)


def write_ingestion_succeeded(cache_dir: Optional[Path] = None) -> None:
    """Mark the ingestion as idle and record the completion timestamp."""
    cache_dir = cache_dir or get_cache_dir()
    existing = read_ingestion_state(cache_dir)
    now = _utc_now_iso()
    payload = {
        "status": "idle",
        "started_at": existing.get("started_at"),
        "last_completed": now,
        "error": None,
    }
    _write_json_atomic(cache_dir / INGESTION_STATE_FILE, payload)


def write_ingestion_failed(error: str, cache_dir: Optional[Path] = None) -> None:
    """Mark the ingestion as failed and record the error message."""
    cache_dir = cache_dir or get_cache_dir()
    existing = read_ingestion_state(cache_dir)
    payload = {
        "status": "failed",
        "started_at": existing.get("started_at"),
        "last_completed": existing.get("last_completed"),
        "error": error,
    }
    _write_json_atomic(cache_dir / INGESTION_STATE_FILE, payload)


def write_fetcher_marker(started_at: str, cache_dir: Optional[Path] = None) -> None:
    """Create the fetcher-running marker. Called by the trigger endpoint."""
    cache_dir = cache_dir or get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(
        cache_dir / FETCHER_RUNNING_MARKER,
        {"started_at": started_at},
    )


def clear_fetcher_marker(cache_dir: Optional[Path] = None) -> None:
    """Remove the fetcher-running marker if present."""
    cache_dir = cache_dir or get_cache_dir()
    marker = cache_dir / FETCHER_RUNNING_MARKER
    try:
        marker.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(f"Could not remove fetcher marker {marker}: {exc}")

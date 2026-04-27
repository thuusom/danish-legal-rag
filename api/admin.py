"""
Admin endpoints (Issue #24).

Two endpoints power the admin UI (Issue #26) and ops tooling:

* ``GET /admin/status`` — aggregate of corpus state pulled from
  ``ingest/sources.yaml``, ``law_cache/currency-report.json``, the fetcher's
  daily-counter file, and Qdrant payload metadata. One row per declared law.

* ``POST /admin/check-currency`` — spawns ``ingest.law_fetcher`` as a
  background subprocess. Returns 202 immediately. Refuses with 409 if a run
  is already in progress (detection via marker file in the cache dir).

Neither endpoint takes auth. They are intended to be reachable only from a
private network or an internal ingress; auth is a deferred follow-up. Do not
expose them to the public internet without putting them behind something.

The admin endpoints intentionally avoid pulling in the heavyweight
``ingest.law_fetcher`` import path (httpx, the full transformer pipeline,
etc.) when serving ``GET /admin/status`` — they read state files only.
The subprocess for ``POST /admin/check-currency`` runs the fetcher in a
fresh interpreter so it doesn't need to be importable here.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from shared.admin_state import (
    clear_fetcher_marker,
    get_cache_dir,
    is_fetcher_running,
    read_currency_report,
    read_fetcher_daily_counter,
    read_fetcher_marker,
    read_ingestion_state,
    write_fetcher_marker,
)
from shared.models import (
    AdminCheckCurrencyAccepted,
    AdminCheckCurrencyConflict,
    AdminFetcherState,
    AdminLawStatus,
    AdminStatusResponse,
)
from shared.qdrant_utils import COLLECTION_NAME, get_qdrant_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# /admin/status
# ---------------------------------------------------------------------------


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Python's fromisoformat handles "2026-04-27T10:00:00+00:00"
        # but historically did not handle a trailing 'Z'. Normalise.
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        logger.warning(f"Could not parse datetime: {value!r}")
        return None


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        logger.warning(f"Could not parse date: {value!r}")
        return None


def _aggregate_qdrant_by_law_code() -> dict[str, dict]:
    """Scroll Qdrant once and aggregate per-law payload state.

    Returns a dict keyed by ``law_code`` with the fields the admin UI cares
    about: ``law_name``, ``law_title``, ``law_number`` (used as the
    human-readable ``our_version``), ``our_version_number``,
    ``our_version_date``, ``ingested_at`` (most recent), ``provisions_count``,
    ``eli``. Returns an empty dict when the collection doesn't exist yet
    (clean install before first ingestion).
    """
    by_code: dict[str, dict] = {}
    try:
        qdrant = get_qdrant_client()
    except Exception as exc:
        logger.warning(f"Qdrant unavailable for /admin/status aggregate: {exc}")
        return by_code

    try:
        collections = [c.name for c in qdrant.get_collections().collections]
    except Exception as exc:
        logger.warning(f"Qdrant get_collections failed: {exc}")
        return by_code

    if COLLECTION_NAME not in collections:
        return by_code

    offset = None
    while True:
        records, offset = qdrant.scroll(
            collection_name=COLLECTION_NAME,
            limit=200,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            payload = record.payload or {}
            code = payload.get("law_code")
            if not code:
                continue
            entry = by_code.get(code)
            if entry is None:
                entry = {
                    "law_code": code,
                    "law_name": payload.get("law_name"),
                    "law_title": payload.get("law_title"),
                    "law_number": payload.get("law_number"),
                    "our_version_number": payload.get("law_version_number"),
                    "our_version_date": payload.get("law_version_date"),
                    "eli": payload.get("eli"),
                    "ingested_at": payload.get("ingested_at"),
                    "provisions_count": 0,
                }
                by_code[code] = entry
            else:
                # First-non-null wins for static fields
                for key in (
                    "law_name",
                    "law_title",
                    "law_number",
                    "our_version_number",
                    "our_version_date",
                    "eli",
                ):
                    if entry.get(key) is None:
                        # source key in payload differs for the version fields
                        if key == "our_version_number":
                            v = payload.get("law_version_number")
                        elif key == "our_version_date":
                            v = payload.get("law_version_date")
                        else:
                            v = payload.get(key)
                        if v is not None:
                            entry[key] = v
                # Max wins for ingested_at (ISO-8601 strings sort lexicographically)
                ts = payload.get("ingested_at")
                if ts and (entry.get("ingested_at") is None or ts > entry["ingested_at"]):
                    entry["ingested_at"] = ts
            entry["provisions_count"] += 1
        if offset is None:
            break
    return by_code


def _load_sources() -> list[dict]:
    """Load the sources manifest as plain dicts.

    We do not want to import ``ingest.cache.load_sources_manifest`` here in
    a way that crashes on a missing dependency: the api Dockerfile installs
    pyyaml (added in this PR), but the function is only reachable through
    a deferred import to keep cold-start light.
    """
    from ingest.cache import load_sources_manifest

    sources = load_sources_manifest()
    return [
        {
            "law_code": s.law_code,
            "law_name": s.short_name,
            "law_title": s.title,
        }
        for s in sources
    ]


def _index_currency_report(report: Optional[dict]) -> dict[str, dict]:
    """Index the currency report by ``law_code`` for easy lookup."""
    if not report or not isinstance(report.get("sources"), list):
        return {}
    indexed: dict[str, dict] = {}
    for entry in report["sources"]:
        code = entry.get("law_code")
        if code:
            indexed[code] = entry
    return indexed


def _derive_law_status(
    qdrant_entry: Optional[dict],
    report_entry: Optional[dict],
) -> tuple[str, Optional[str]]:
    """Compute (status, fetch_error) for a law.

    Rules (in order):
      1. If the fetcher's last attempt failed → ``fetch-failed``.
      2. If we have no report entry and no chunks → ``unknown``.
      3. If both versions are known and differ → ``outdated`` (when latest
         > our) or ``ok`` (when equal).
      4. Otherwise → ``ok`` if we have ingested chunks, else ``unknown``.
    """
    if report_entry and report_entry.get("status") == "fetch-failed":
        return "fetch-failed", report_entry.get("error")

    has_qdrant = qdrant_entry is not None and qdrant_entry.get("provisions_count", 0) > 0

    if report_entry is None:
        return ("ok" if has_qdrant else "unknown"), None

    latest = report_entry.get("latest_version")
    ours = (
        qdrant_entry.get("our_version_number") if qdrant_entry else None
    ) or report_entry.get("our_version") or 0

    if latest is not None and ours is not None:
        try:
            if int(latest) > int(ours):
                return "outdated", None
        except (TypeError, ValueError):
            pass

    return ("ok" if has_qdrant else "unknown"), None


def build_admin_status() -> AdminStatusResponse:
    """Assemble the admin status payload from cache + Qdrant."""
    cache_dir = get_cache_dir()
    sources = _load_sources()
    qdrant_by_code = _aggregate_qdrant_by_law_code()
    report = read_currency_report(cache_dir)
    report_index = _index_currency_report(report)
    daily_counter = read_fetcher_daily_counter(cache_dir)
    ingestion = read_ingestion_state(cache_dir)

    rows: list[AdminLawStatus] = []
    for src in sources:
        code = src["law_code"]
        qdrant_entry = qdrant_by_code.get(code)
        report_entry = report_index.get(code)
        status_value, fetch_error = _derive_law_status(qdrant_entry, report_entry)

        # latest_version_date: not in the report today (the fetcher only writes
        # the version *number*). We surface what we have; UIs can render
        # "newer version available" off the number alone.
        latest_version_date: Optional[date] = None

        rows.append(
            AdminLawStatus(
                law_code=code,
                law_name=(qdrant_entry or {}).get("law_name") or src["law_name"],
                law_title=(qdrant_entry or {}).get("law_title") or src["law_title"],
                our_version=(qdrant_entry or {}).get("law_number"),
                our_version_number=(qdrant_entry or {}).get("our_version_number"),
                our_version_date=_parse_iso_date(
                    (qdrant_entry or {}).get("our_version_date")
                ),
                latest_version_number=(report_entry or {}).get("latest_version"),
                latest_version_date=latest_version_date,
                status=status_value,
                ingested_at=_parse_iso_datetime(
                    (qdrant_entry or {}).get("ingested_at")
                ),
                provisions_count=(qdrant_entry or {}).get("provisions_count", 0),
                eli=(qdrant_entry or {}).get("eli"),
                fetch_error=fetch_error,
            )
        )

    # Resolve fetcher rate-limit knobs from env (defaults match
    # ingest/law_fetcher.py).
    rate_limit_day = _env_int("FETCHER_RATE_LIMIT_DAY", 40)
    rate_limit_hour = _env_int("FETCHER_RATE_LIMIT_HOUR", 15)

    # ingestion_status — coerce unknown legacy values to the typed literal.
    raw_status = ingestion.get("status", "unknown")
    if raw_status not in {"idle", "running", "failed", "unknown"}:
        raw_status = "unknown"

    return AdminStatusResponse(
        laws=rows,
        last_currency_check=_parse_iso_datetime(
            (report or {}).get("checked_at") if report else None
        ),
        ingestion_status=raw_status,
        last_ingestion_completed=_parse_iso_datetime(ingestion.get("last_completed")),
        last_ingestion_error=ingestion.get("error"),
        fetcher_state=AdminFetcherState(
            calls_today=daily_counter["count"],
            rate_limit_day=rate_limit_day,
            calls_this_hour=0,  # not persisted; see schema description
            rate_limit_hour=rate_limit_hour,
        ),
    )


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} is not an int; using default {default}")
        return default


@router.get("/status", response_model=AdminStatusResponse)
async def get_admin_status() -> AdminStatusResponse:
    """Aggregate corpus state. See module docstring for shape and rules."""
    try:
        return build_admin_status()
    except Exception as exc:
        logger.exception("Failed to build admin status")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# /admin/check-currency
# ---------------------------------------------------------------------------


async def _spawn_fetcher_subprocess() -> None:
    """Run ``python -m ingest.law_fetcher`` as a detached subprocess.

    The marker file is created here, before spawn, so a parallel POST sees
    the run in flight. The marker is cleared by the wrapper when the
    subprocess exits, regardless of outcome.
    """
    cache_dir = get_cache_dir()
    started_at = datetime.now(timezone.utc).isoformat()
    write_fetcher_marker(started_at, cache_dir)

    async def runner() -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "ingest.law_fetcher",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info(
                    f"Fetcher subprocess exited ok (rc=0). "
                    f"stdout_tail={stdout[-300:]!r}"
                )
            else:
                logger.error(
                    f"Fetcher subprocess failed (rc={proc.returncode}). "
                    f"stderr_tail={stderr[-500:]!r}"
                )
        except Exception:
            logger.exception("Fetcher subprocess could not be launched")
        finally:
            clear_fetcher_marker(cache_dir)

    # Fire-and-forget; the response goes back immediately.
    asyncio.create_task(runner())


@router.post(
    "/check-currency",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AdminCheckCurrencyAccepted,
    responses={
        409: {
            "model": AdminCheckCurrencyConflict,
            "description": "Another fetcher run is already in progress",
        },
    },
)
async def trigger_currency_check() -> AdminCheckCurrencyAccepted:
    """Trigger the live retsinformation fetcher.

    Idempotent: if a run is already in progress, returns 409 with the
    ``started_at`` of the in-progress run when known. Use ``GET /admin/status``
    to observe completion (the report timestamp updates).
    """
    cache_dir = get_cache_dir()
    if is_fetcher_running(cache_dir):
        marker = read_fetcher_marker(cache_dir) or {}
        body = AdminCheckCurrencyConflict(
            status="already-running",
            started_at=_parse_iso_datetime(marker.get("started_at")),
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=body.model_dump(mode="json"),
        )

    await _spawn_fetcher_subprocess()
    return AdminCheckCurrencyAccepted(
        status="started",
        started_at=datetime.now(timezone.utc),
    )

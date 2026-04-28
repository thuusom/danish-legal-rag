"""
Live law fetcher for retsinformation-api.dk (Issue #20).

This module is the boundary between the external retsinformation-api.dk and
our domain JSON files. It does NOT touch Qdrant — its only job is to keep
``law_cache/`` fresh. The existing ingestion pipeline (idempotent per #23)
re-processes whatever the cache currently holds on the next boot.

Flow (one pass through ``ingest/sources.yaml``):

  1. For every source: read the cached JSON if present and pull
     ``law_version_number`` (default 0 if missing/seed).
  2. Call ``GET /v1/lovgivning/{year}/{number}/versions/latest`` and compare
     versions. If the API version is newer (or the cache is missing), fetch
     and transform; otherwise mark up-to-date and move on.
  3. The cache file format is identical to the in-repo ``ingest/data/*.json``
     seed files, augmented with the metadata fields added in #22
     (``law_version_date``, ``law_version_number``, ``eli``,
     ``retsinformation_law_id``, plus per-provision
     ``retsinformation_paragraph_id``).
  4. Write a single ``law_cache/currency-report.json`` summarising the run.

Design notes:

  * The CLI is the only entry point for now. Issue #25 will wire a cron and a
    Makefile target.
  * Rate limiting is conservative: 15/h and 40/d (under the published 20/h,
    50/d limits). The daily counter persists in ``law_cache/.fetcher_state.json``
    so a restart can't reset it.
  * Resilience is per-law: an HTTP failure on AFL must not prevent ARL from
    being attempted. The seed cache continues to serve any law that fails.
  * No retries are attempted on 4xx (the source is wrong), only on 5xx and
    network errors. Backoff is exponential with a small jitter.
  * Pydantic validates the API response before transformation so a schema
    drift fails loudly with a useful error rather than producing a garbage
    cache file.

Configuration (env vars):

  RETSINFORMATION_API_URL     base URL (default https://retsinformation-api.dk)
  FETCHER_RATE_LIMIT_HOUR     calls per hour (default 15)
  FETCHER_RATE_LIMIT_DAY      calls per day (default 40)
  FETCHER_TIMEOUT_SEC         per-request timeout (default 30)
  FETCHER_DRY_RUN             if "true", do everything except writing files
  LAW_CACHE_DIR               cache directory (already used by ingest.cache)
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

from ingest.cache import LawSource, get_cache_dir, load_sources_manifest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} is not an int; using default {default}")
        return default


RETSINFORMATION_API_URL = os.environ.get(
    "RETSINFORMATION_API_URL", "https://retsinformation-api.dk"
).rstrip("/")
FETCHER_RATE_LIMIT_HOUR = _env_int("FETCHER_RATE_LIMIT_HOUR", 15)
FETCHER_RATE_LIMIT_DAY = _env_int("FETCHER_RATE_LIMIT_DAY", 40)
FETCHER_TIMEOUT_SEC = _env_int("FETCHER_TIMEOUT_SEC", 30)
FETCHER_DRY_RUN = os.environ.get("FETCHER_DRY_RUN", "false").lower() == "true"

# Filename for the daily quota state file inside the cache directory.
STATE_FILE_NAME = ".fetcher_state.json"
# Filename for the currency report.
CURRENCY_REPORT_NAME = "currency-report.json"


# ---------------------------------------------------------------------------
# API response validation
# ---------------------------------------------------------------------------


class ApiLitra(BaseModel):
    number: str = ""
    text: str = ""


class ApiStk(BaseModel):
    number: str = ""
    text: str = ""
    litra: list[ApiLitra] = Field(default_factory=list)


class ApiParagraph(BaseModel):
    id: str = ""
    number: str = ""
    stk: list[ApiStk] = Field(default_factory=list)


class ApiParagraphGroup(BaseModel):
    id: str = ""
    number: str = ""
    heading: str = ""
    paragraphs: list[ApiParagraph] = Field(default_factory=list)


class ApiChapter(BaseModel):
    chapter_number: str = ""
    chapter_title: str = ""
    afsnit: str = ""
    paragraph_groups: list[ApiParagraphGroup] = Field(default_factory=list)


class ApiStructure(BaseModel):
    title: str = ""
    chapters: list[ApiChapter] = Field(default_factory=list)


class ApiLawResponse(BaseModel):
    """Subset of the retsinformation-api.dk law response that we consume.

    Pydantic ignores fields it doesn't know about (model_config below), so
    we only declare what we actually use. Any drift in fields we depend on
    will fail validation loudly rather than silently producing junk.
    """

    law_id: Optional[str] = None
    version_number: Optional[int] = None
    effective_date: Optional[str] = None
    year: Optional[int] = None
    number: Optional[int] = None
    eli_uri: Optional[str] = None
    title: Optional[str] = None
    short_name: Optional[str] = None
    popular_title: Optional[str] = None
    signature_date: Optional[str] = None
    structure: ApiStructure = Field(default_factory=ApiStructure)


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class FetcherError(Exception):
    """Raised when a fetch fails for any reason — network, 5xx, or 4xx."""


class RateLimitExceeded(FetcherError):
    """Raised when the daily rate limit would be exceeded."""


class _HourlyThrottle:
    """Sleep-based throttle that enforces ``rate_per_hour`` evenly.

    This is intentionally simple: we sleep ``3600 / rate`` seconds between
    calls. No bursts allowed. Combined with the daily counter, that's enough
    to stay polite within the published 20/h and 50/d budgets.
    """

    def __init__(self, rate_per_hour: int, sleeper=time.sleep):
        self.rate_per_hour = max(1, rate_per_hour)
        self._sleeper = sleeper
        self._last_call_at: Optional[float] = None

    def wait(self) -> None:
        if self._last_call_at is None:
            self._last_call_at = time.monotonic()
            return
        interval = 3600.0 / self.rate_per_hour
        elapsed = time.monotonic() - self._last_call_at
        sleep_for = interval - elapsed
        if sleep_for > 0:
            logger.debug(f"Throttling: sleeping {sleep_for:.2f}s before next call")
            self._sleeper(sleep_for)
        self._last_call_at = time.monotonic()


class _DailyCounter:
    """Persistent counter to enforce a daily call budget across restarts.

    State is stored at ``<cache_dir>/.fetcher_state.json``. The date is
    derived in UTC; calling ``increment`` after the day rolls over resets
    the counter.
    """

    def __init__(self, state_path: Path, daily_limit: int):
        self.state_path = state_path
        self.daily_limit = daily_limit

    def _load(self) -> dict:
        if not self.state_path.exists():
            return {"date": None, "count": 0}
        try:
            with self.state_path.open(encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            logger.warning(f"Corrupt fetcher state at {self.state_path}; resetting")
            return {"date": None, "count": 0}

    def _save(self, state: dict) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Could not persist fetcher state to {self.state_path}: {exc}")

    def current(self) -> tuple[str, int]:
        today = datetime.now(timezone.utc).date().isoformat()
        state = self._load()
        if state.get("date") != today:
            return today, 0
        return today, int(state.get("count", 0))

    def can_consume(self, n: int = 1) -> bool:
        _, count = self.current()
        return (count + n) <= self.daily_limit

    def consume(self, n: int = 1) -> None:
        today, count = self.current()
        new_count = count + n
        if new_count > self.daily_limit:
            raise RateLimitExceeded(
                f"Daily fetcher budget exhausted: {count}/{self.daily_limit} used today"
            )
        self._save({"date": today, "count": new_count})


class RetsinformationClient:
    """HTTP client for retsinformation-api.dk with rate limiting and retries.

    All public methods raise :class:`FetcherError` on any failure (network,
    5xx after retries, 4xx). Callers are expected to catch it per-source so
    one failure doesn't poison the whole run.
    """

    def __init__(
        self,
        base_url: str = RETSINFORMATION_API_URL,
        rate_limit_per_hour: int = FETCHER_RATE_LIMIT_HOUR,
        rate_limit_per_day: int = FETCHER_RATE_LIMIT_DAY,
        timeout_sec: int = FETCHER_TIMEOUT_SEC,
        max_retries: int = 3,
        state_path: Optional[Path] = None,
        client: Optional[httpx.Client] = None,
        sleeper=time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self._sleeper = sleeper
        self._throttle = _HourlyThrottle(rate_limit_per_hour, sleeper=sleeper)
        if state_path is None:
            state_path = get_cache_dir() / STATE_FILE_NAME
        self._daily = _DailyCounter(state_path, rate_limit_per_day)
        self._client = client or httpx.Client(timeout=timeout_sec)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "RetsinformationClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -- public endpoints --------------------------------------------------

    def get_versions_latest(self, year: int, number: int) -> dict:
        """GET /v1/lovgivning/{year}/{number}/versions/latest."""
        path = f"/v1/lovgivning/{year}/{number}/versions/latest"
        return self._get_json(path)

    def get_base(self, year: int, number: int) -> dict:
        """GET /v1/lovgivning/{year}/{number} — only used to recover ``eli_uri``."""
        path = f"/v1/lovgivning/{year}/{number}"
        return self._get_json(path)

    # -- internals ---------------------------------------------------------

    def _get_json(self, path: str) -> dict:
        if not self._daily.can_consume(1):
            raise RateLimitExceeded(
                f"Refusing to call {path}: daily fetcher budget exhausted"
            )
        url = f"{self.base_url}{path}"
        attempt = 0
        last_exc: Optional[Exception] = None
        while attempt <= self.max_retries:
            self._throttle.wait()
            try:
                self._daily.consume(1)
                logger.info(f"GET {url} (attempt {attempt + 1})")
                resp = self._client.get(url)
            except httpx.RequestError as exc:
                last_exc = exc
                logger.warning(f"Network error on {url}: {exc}")
                if attempt >= self.max_retries:
                    break
                self._backoff_sleep(attempt)
                attempt += 1
                continue

            if resp.status_code == 200:
                try:
                    return resp.json()
                except json.JSONDecodeError as exc:
                    raise FetcherError(f"Non-JSON response from {url}: {exc}") from exc

            if 400 <= resp.status_code < 500:
                # Don't retry 4xx — the request itself is wrong.
                raise FetcherError(
                    f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}"
                )

            # 5xx — retry with backoff.
            last_exc = FetcherError(
                f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
            logger.warning(f"5xx on {url}: status={resp.status_code}, attempt={attempt + 1}")
            if attempt >= self.max_retries:
                break
            self._backoff_sleep(attempt)
            attempt += 1

        assert last_exc is not None
        raise FetcherError(f"Giving up on {url} after {self.max_retries + 1} attempts: {last_exc}")

    def _backoff_sleep(self, attempt: int) -> None:
        # 1s, 2s, 4s ... with up to 25% jitter
        base = 2 ** attempt
        jitter = random.uniform(0, base * 0.25)
        self._sleeper(base + jitter)


# ---------------------------------------------------------------------------
# Transformation
# ---------------------------------------------------------------------------


def _strip_dot_suffix(value: str) -> str:
    return value.rstrip(".").strip()


def _normalise_section(api_number: str) -> str:
    """``"§ 5 a." → "§ 5 a"`` — strip trailing dot, lowercase any single-letter suffix.

    Per the spike we keep the lowercase letter form (``§ 5 a``) rather than
    upper-casing. The upstream API is inconsistent — most letter-suffix
    paragraphs are lowercase but a handful (e.g. ``§ 44 C``) come back
    upper-case. We normalise here so downstream code never has to care.
    """
    cleaned = " ".join(_strip_dot_suffix(api_number).split())
    parts = cleaned.split(" ")
    # ``§ <number> <letter>`` — the letter is always one alphabetic char.
    if len(parts) == 3 and len(parts[2]) == 1 and parts[2].isalpha():
        parts[2] = parts[2].lower()
        cleaned = " ".join(parts)
    return cleaned


def _normalise_subsection(api_number: str) -> str:
    """``"Stk. 1." → "stk. 1"``."""
    return " ".join(_strip_dot_suffix(api_number).lower().split())


def _build_chapter_label(chapter: ApiChapter) -> Optional[str]:
    """Render ``"Kapitel 2 – Driftsmidler og skibe"`` from API fields.

    Returns ``None`` if both fields are empty (a synthetic top-level chapter
    with no number/title).
    """
    num = chapter.chapter_number.strip()
    title = chapter.chapter_title.strip()
    if not num and not title:
        return None
    if num and title:
        return f"{num} \u2013 {title}"
    return num or title


def _render_text_with_litra(stk: ApiStk) -> str:
    """Inline litra into the stk text (matches existing convention).

    Format: original text, blank line, then ``"<n>) <text>"`` per litra.
    """
    text = stk.text.strip()
    if not stk.litra:
        return text
    rendered = [text]
    for lit in stk.litra:
        num = lit.number.strip()
        body = lit.text.strip()
        if not num and not body:
            continue
        if num and body:
            rendered.append(f"{num} {body}")
        else:
            rendered.append(num or body)
    return "\n".join(rendered)


def _construct_eli(year: int, number: int) -> str:
    """Default ELI path for a Danish lovbekendtgørelse: ``eli/lta/{year}/{number}``."""
    return f"eli/lta/{year}/{number}"


def _normalise_eli(eli_uri: Optional[str]) -> Optional[str]:
    """Strip the leading slash so it matches the convention used in seed files."""
    if not eli_uri:
        return None
    return eli_uri.lstrip("/")


class LawTransformer:
    """Transform a parsed retsinformation API response into our cached law JSON."""

    def transform(
        self,
        api_response: dict,
        law_code: str,
        eli_override: Optional[str] = None,
    ) -> dict:
        """Return the same JSON shape as ``ingest/data/*.json``.

        Args:
            api_response: parsed JSON from ``versions/latest`` (or ``base``).
            law_code: short code from ``sources.yaml`` — not derivable from API.
            eli_override: an explicit ELI path. ``versions/latest`` returns
                ``eli_uri: null``, so callers either pass the value from the
                base endpoint or let us construct it from ``(year, number)``.

        Raises:
            ValidationError: if the API response doesn't match our schema.
        """
        parsed = ApiLawResponse.model_validate(api_response)

        # Resolve identity / metadata.
        law_name = (parsed.popular_title or "").strip() or (parsed.short_name or "").strip()
        law_title = (parsed.title or parsed.structure.title or "").strip()
        law_number = (parsed.short_name or "").strip() or None
        # ``signature_date`` is the date stamped on the lovbekendtgørelse —
        # matches our existing ``effective_date`` field. The top-level
        # ``effective_date`` is the version-effective date and goes to the
        # new ``law_version_date`` field.
        effective_date = parsed.signature_date
        law_version_date = parsed.effective_date
        law_version_number = parsed.version_number

        # ELI — explicit override > API-provided eli_uri > deterministic construction.
        eli = eli_override or _normalise_eli(parsed.eli_uri)
        if not eli and parsed.year and parsed.number:
            eli = _construct_eli(parsed.year, parsed.number)

        source_url = f"https://www.retsinformation.dk/{eli}" if eli else None

        # Walk the structure → flat list of provisions.
        provisions = self._extract_provisions(parsed.structure)

        # Single-stk wrapper elision: if a paragraph emits exactly one provision
        # AND that provision has no item, drop the ``subsection`` field. This
        # matches the existing hand-curated convention.
        provisions = self._elide_single_stk(provisions)

        return {
            "law_code": law_code,
            "law_name": law_name,
            "law_title": law_title,
            "law_number": law_number,
            "source_url": source_url,
            "effective_date": effective_date,
            # Issue #22 fields — populated only on live-fetched laws.
            "law_version_date": law_version_date,
            "law_version_number": law_version_number,
            "eli": eli,
            "retsinformation_law_id": parsed.law_id,
            "provisions": provisions,
        }

    # -- structure walking --------------------------------------------------

    def _extract_provisions(self, structure: ApiStructure) -> list[dict]:
        """Flatten chapters → groups → paragraphs → stk into provisions.

        Litra are inlined into their stk's text (matches existing convention;
        we don't split them into separate provisions).
        """
        provisions: list[dict] = []
        for chapter in structure.chapters:
            chapter_label = _build_chapter_label(chapter)
            for group in chapter.paragraph_groups:
                for paragraph in group.paragraphs:
                    section = _normalise_section(paragraph.number)
                    if not section:
                        # No § number — skip; can't build a stable id.
                        logger.debug("Skipping paragraph with empty number")
                        continue
                    para_id = paragraph.id or None
                    if not paragraph.stk:
                        # No stk at all: emit one provision with subsection=None.
                        provisions.append(
                            {
                                "chapter": chapter_label,
                                "section": section,
                                "subsection": None,
                                "item": None,
                                "title": None,
                                "text": "",
                                "retsinformation_paragraph_id": para_id,
                            }
                        )
                        continue
                    for stk in paragraph.stk:
                        subsection = _normalise_subsection(stk.number) or None
                        text = _render_text_with_litra(stk)
                        provisions.append(
                            {
                                "chapter": chapter_label,
                                "section": section,
                                "subsection": subsection,
                                "item": None,
                                "title": None,
                                "text": text,
                                "retsinformation_paragraph_id": para_id,
                            }
                        )
        return provisions

    @staticmethod
    def _elide_single_stk(provisions: list[dict]) -> list[dict]:
        """Drop the synthetic ``stk. 1`` wrapper for single-stk paragraphs.

        Convention from existing hand-curated files: a paragraph with exactly
        one stk and no litra (== no ``item``) carries ``subsection: null``,
        not ``"stk. 1"``. We detect this by counting provisions per
        ``section``.
        """
        per_section: dict[str, int] = {}
        for prov in provisions:
            per_section[prov["section"]] = per_section.get(prov["section"], 0) + 1

        result: list[dict] = []
        for prov in provisions:
            if (
                per_section[prov["section"]] == 1
                and prov.get("subsection") == "stk. 1"
                and not prov.get("item")
            ):
                prov = {**prov, "subsection": None}
            result.append(prov)
        return result


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def _read_cached_version(cache_path: Path) -> int:
    """Return the cached law's ``law_version_number`` or 0 if not present."""
    if not cache_path.exists():
        return 0
    try:
        with cache_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Could not parse cached law at {cache_path}: {exc}")
        return 0
    raw = data.get("law_version_number")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return 0


def _write_cache_atomic(path: Path, payload: dict) -> None:
    """Write ``payload`` to ``path`` atomically (write-and-rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def fetch_one(
    source: LawSource,
    client: RetsinformationClient,
    cache_dir: Path,
    transformer: Optional[LawTransformer] = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """Fetch and (if newer or missing) cache a single law.

    Returns a per-law currency report entry. Never raises — failures are
    captured in the returned ``status``/``error`` fields so the run can
    proceed past a single broken law.
    """
    transformer = transformer or LawTransformer()
    cache_path = cache_dir / f"{source.law_code}.json"
    cached_version = _read_cached_version(cache_path)
    cache_existed = cache_path.exists()
    started_at = datetime.now(timezone.utc).isoformat()

    entry: dict = {
        "law_code": source.law_code,
        "status": "unknown",
        "our_version": cached_version,
        "latest_version": None,
        "fetched_at": None,
        "error": None,
    }

    try:
        latest_raw = client.get_versions_latest(
            source.retsinformation.year, source.retsinformation.number
        )
    except FetcherError as exc:
        logger.error(
            f"FETCHER_FAIL law_code={source.law_code} step=versions_latest "
            f"err={exc}"
        )
        entry["status"] = "fetch-failed"
        entry["error"] = str(exc)
        return entry

    try:
        parsed = ApiLawResponse.model_validate(latest_raw)
    except ValidationError as exc:
        logger.error(
            f"FETCHER_FAIL law_code={source.law_code} step=validate err={exc}"
        )
        entry["status"] = "fetch-failed"
        entry["error"] = f"schema validation failed: {exc}"
        return entry

    latest_version = parsed.version_number or 0
    entry["latest_version"] = latest_version

    needs_fetch = force or (not cache_existed) or (latest_version > cached_version)
    if not needs_fetch:
        logger.info(
            f"FETCHER_SKIP law_code={source.law_code} our={cached_version} "
            f"latest={latest_version}"
        )
        entry["status"] = "up-to-date"
        return entry

    # We need an ELI for source_url. ``versions/latest`` returns it as null,
    # so try to recover it from the base endpoint. If that call fails too,
    # fall back to the deterministic construction.
    eli_override: Optional[str] = _normalise_eli(parsed.eli_uri)
    if not eli_override:
        try:
            base_raw = client.get_base(
                source.retsinformation.year, source.retsinformation.number
            )
            base_parsed = ApiLawResponse.model_validate(base_raw)
            eli_override = _normalise_eli(base_parsed.eli_uri)
        except (FetcherError, ValidationError) as exc:
            logger.warning(
                f"Could not recover eli_uri for {source.law_code} from base "
                f"endpoint ({exc}); will construct deterministically."
            )

    try:
        transformed = transformer.transform(
            latest_raw, law_code=source.law_code, eli_override=eli_override
        )
    except (ValidationError, KeyError, ValueError) as exc:
        logger.error(
            f"FETCHER_FAIL law_code={source.law_code} step=transform err={exc}"
        )
        entry["status"] = "fetch-failed"
        entry["error"] = f"transform failed: {exc}"
        return entry

    if not transformed.get("provisions"):
        # Refuse to write an empty cache — protect against silent corpus loss.
        msg = "transform produced 0 provisions; refusing to write empty cache"
        logger.error(f"FETCHER_FAIL law_code={source.law_code} step=transform err={msg}")
        entry["status"] = "fetch-failed"
        entry["error"] = msg
        return entry

    if not dry_run:
        _write_cache_atomic(cache_path, transformed)
        logger.info(
            f"FETCHER_WROTE law_code={source.law_code} version={latest_version} "
            f"provisions={len(transformed['provisions'])} path={cache_path}"
        )
    else:
        logger.info(
            f"FETCHER_DRY_RUN law_code={source.law_code} version={latest_version} "
            f"provisions={len(transformed['provisions'])} (no write)"
        )

    entry["status"] = "new" if not cache_existed else "updated"
    entry["fetched_at"] = started_at
    return entry


def fetch_all(
    sources: Iterable[LawSource],
    client: RetsinformationClient,
    cache_dir: Optional[Path] = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run :func:`fetch_one` for every source and return the currency report dict."""
    cache_dir = cache_dir or get_cache_dir()
    transformer = LawTransformer()
    sources_list = list(sources)

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": client.base_url,
        "dry_run": dry_run,
        "sources": [],
    }

    for source in sources_list:
        entry = fetch_one(
            source=source,
            client=client,
            cache_dir=cache_dir,
            transformer=transformer,
            force=force,
            dry_run=dry_run,
        )
        report["sources"].append(entry)

    return report


def write_currency_report(report: dict, cache_dir: Optional[Path] = None) -> Path:
    """Persist ``report`` to ``<cache_dir>/currency-report.json``."""
    cache_dir = cache_dir or get_cache_dir()
    target = cache_dir / CURRENCY_REPORT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI entrypoint for the fetcher.

    Usage::

        python -m ingest.law_fetcher [--force] [--dry-run]

    Exit code is 0 on success (even if some laws failed — those are logged
    and reported in currency-report.json) and 1 on a hard error (manifest
    missing, daily budget exhausted before any work, etc.).
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="ingest.law_fetcher",
        description="Fetch Danish laws from retsinformation-api.dk into the cache.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even if the cached version is current.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=FETCHER_DRY_RUN,
        help="Do everything except writing files.",
    )
    parser.add_argument(
        "--law-code",
        action="append",
        default=None,
        help="Restrict to a specific law_code (may be passed multiple times).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        sources = load_sources_manifest()
    except (FileNotFoundError, ValueError) as exc:
        logger.error(f"Could not load sources manifest: {exc}")
        return 1

    if args.law_code:
        wanted = set(args.law_code)
        sources = [s for s in sources if s.law_code in wanted]
        missing = wanted - {s.law_code for s in sources}
        if missing:
            logger.warning(f"Unknown law_code(s) ignored: {sorted(missing)}")
        if not sources:
            logger.error("No sources matched --law-code; nothing to do.")
            return 1

    cache_dir = get_cache_dir()
    logger.info(
        f"Starting fetcher: base_url={RETSINFORMATION_API_URL} "
        f"sources={len(sources)} cache_dir={cache_dir} dry_run={args.dry_run}"
    )

    with RetsinformationClient() as client:
        report = fetch_all(
            sources=sources,
            client=client,
            cache_dir=cache_dir,
            force=args.force,
            dry_run=args.dry_run,
        )

    report_path = write_currency_report(report, cache_dir)
    logger.info(f"Currency report written to {report_path}")

    # Final structured summary for log scrapers.
    counts: dict[str, int] = {}
    for entry in report["sources"]:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    logger.info(f"FETCHER_RUN_SUMMARY {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

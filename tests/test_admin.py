"""
Unit tests for the admin endpoints (Issue #24).

These run without Qdrant and without a real fetcher subprocess. We use
FastAPI's TestClient and patch the small set of helpers in
``api.admin`` that touch the outside world:

  * Qdrant aggregate         → ``_aggregate_qdrant_by_law_code``
  * sources manifest loader  → ``_load_sources``
  * fetcher subprocess spawn → ``_spawn_fetcher_subprocess``

Cache state files live in a tmp directory and are exercised via the real
``shared.admin_state`` helpers — that way the read paths get coverage too.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import admin as admin_mod
from shared.admin_state import (
    CURRENCY_REPORT_FILE,
    FETCHER_DAILY_STATE_FILE,
    FETCHER_RUNNING_MARKER,
    INGESTION_STATE_FILE,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch) -> Path:
    """Redirect LAW_CACHE_DIR to a tmp directory."""
    d = tmp_path / "law_cache"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LAW_CACHE_DIR", str(d))
    return d


@pytest.fixture
def fake_sources(monkeypatch):
    """Stub _load_sources to avoid loading the real sources.yaml."""

    sources = [
        {
            "law_code": "AFL",
            "law_name": "Afskrivningsloven",
            "law_title": "Bekendtgørelse af lov om skattemæssige afskrivninger",
        },
        {
            "law_code": "ARL",
            "law_name": "Årsregnskabsloven",
            "law_title": "Bekendtgørelse af årsregnskabsloven",
        },
    ]
    monkeypatch.setattr(admin_mod, "_load_sources", lambda: sources)
    return sources


@pytest.fixture
def empty_qdrant(monkeypatch):
    """Stub Qdrant aggregate to return nothing (clean install)."""
    monkeypatch.setattr(admin_mod, "_aggregate_qdrant_by_law_code", lambda: {})


@pytest.fixture
def populated_qdrant(monkeypatch):
    """Stub Qdrant aggregate to return realistic per-law payload state."""
    by_code = {
        "AFL": {
            "law_code": "AFL",
            "law_name": "Afskrivningsloven",
            "law_title": "Bekendtgørelse af lov om skattemæssige afskrivninger",
            "law_number": "LBK nr 1147 af 29/08/2016",
            "our_version_number": 1,
            "our_version_date": "2016-09-06",
            "eli": "eli/lta/2016/1147",
            "ingested_at": "2026-04-27T10:00:00+00:00",
            "provisions_count": 41,
        },
        "ARL": {
            "law_code": "ARL",
            "law_name": "Årsregnskabsloven",
            "law_title": "Bekendtgørelse af årsregnskabsloven",
            "law_number": "LBK nr 1580 af 10/12/2015",
            "our_version_number": 5,
            "our_version_date": "2015-12-10",
            "eli": "eli/lta/2015/1580",
            "ingested_at": "2026-04-27T10:01:00+00:00",
            "provisions_count": 90,
        },
    }
    monkeypatch.setattr(admin_mod, "_aggregate_qdrant_by_law_code", lambda: by_code)
    return by_code


@pytest.fixture
def app(fake_sources) -> FastAPI:
    """Minimal FastAPI app with only the admin router mounted.

    Avoiding the real ``api.main`` keeps the test fast (no Qdrant wait, no
    embedding model download) and lets us exercise the router in isolation.
    """
    app = FastAPI()
    app.include_router(admin_mod.router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# GET /admin/status
# ---------------------------------------------------------------------------


class TestAdminStatusEmptyCache:

    def test_no_report_no_qdrant_returns_unknown_per_law(
        self, cache_dir, empty_qdrant, client
    ):
        r = client.get("/admin/status")
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["last_currency_check"] is None
        assert body["ingestion_status"] == "unknown"
        assert body["last_ingestion_completed"] is None
        # Daily counter should default to 0 today.
        assert body["fetcher_state"]["calls_today"] == 0
        assert body["fetcher_state"]["rate_limit_day"] >= 1
        assert body["fetcher_state"]["rate_limit_hour"] >= 1

        # Every declared source produces a row.
        codes = [law["law_code"] for law in body["laws"]]
        assert codes == ["AFL", "ARL"]
        for law in body["laws"]:
            assert law["status"] == "unknown"
            assert law["provisions_count"] == 0
            assert law["our_version_number"] is None
            assert law["latest_version_number"] is None
            assert law["fetch_error"] is None

    def test_qdrant_only_no_report_returns_ok(
        self, cache_dir, populated_qdrant, client
    ):
        # Qdrant has data but the fetcher never ran — status is "ok" (we have
        # ingested chunks; we just don't know if upstream is newer).
        r = client.get("/admin/status")
        assert r.status_code == 200
        body = r.json()
        for law in body["laws"]:
            assert law["status"] == "ok"
            assert law["provisions_count"] > 0
            assert law["our_version_number"] is not None
            assert law["latest_version_number"] is None


class TestAdminStatusWithReport:

    def test_outdated_when_latest_greater_than_ours(
        self, cache_dir, populated_qdrant, client
    ):
        report = {
            "checked_at": "2026-04-27T06:00:00+00:00",
            "base_url": "https://retsinformation-api.dk",
            "dry_run": False,
            "sources": [
                {
                    "law_code": "AFL",
                    "status": "up-to-date",
                    "our_version": 1,
                    "latest_version": 24,  # >> our 1 → outdated
                    "fetched_at": None,
                    "error": None,
                },
                {
                    "law_code": "ARL",
                    "status": "up-to-date",
                    "our_version": 5,
                    "latest_version": 5,  # equal → ok
                    "fetched_at": None,
                    "error": None,
                },
            ],
        }
        _write(cache_dir / CURRENCY_REPORT_FILE, report)

        r = client.get("/admin/status")
        assert r.status_code == 200
        body = r.json()
        assert body["last_currency_check"] is not None
        assert body["last_currency_check"].startswith("2026-04-27T06:00:00")

        per_code = {law["law_code"]: law for law in body["laws"]}
        assert per_code["AFL"]["status"] == "outdated"
        assert per_code["AFL"]["latest_version_number"] == 24
        assert per_code["AFL"]["our_version_number"] == 1
        assert per_code["AFL"]["fetch_error"] is None
        assert per_code["ARL"]["status"] == "ok"
        assert per_code["ARL"]["latest_version_number"] == 5

    def test_fetch_failed_status_propagated(
        self, cache_dir, populated_qdrant, client
    ):
        report = {
            "checked_at": "2026-04-27T06:00:00+00:00",
            "sources": [
                {
                    "law_code": "AFL",
                    "status": "fetch-failed",
                    "our_version": 1,
                    "latest_version": None,
                    "fetched_at": None,
                    "error": "HTTP 503: upstream busy",
                },
                {
                    "law_code": "ARL",
                    "status": "up-to-date",
                    "our_version": 5,
                    "latest_version": 5,
                    "fetched_at": None,
                    "error": None,
                },
            ],
        }
        _write(cache_dir / CURRENCY_REPORT_FILE, report)

        r = client.get("/admin/status")
        body = r.json()
        per_code = {law["law_code"]: law for law in body["laws"]}
        assert per_code["AFL"]["status"] == "fetch-failed"
        assert per_code["AFL"]["fetch_error"] == "HTTP 503: upstream busy"
        # The healthy law in the same report stays healthy.
        assert per_code["ARL"]["status"] == "ok"


class TestAdminStatusFetcherCounter:

    def test_counts_today_reflected(self, cache_dir, empty_qdrant, client):
        today = datetime.now(timezone.utc).date().isoformat()
        _write(
            cache_dir / FETCHER_DAILY_STATE_FILE,
            {"date": today, "count": 7},
        )
        r = client.get("/admin/status")
        body = r.json()
        assert body["fetcher_state"]["calls_today"] == 7

    def test_yesterday_counter_reads_as_zero(
        self, cache_dir, empty_qdrant, client
    ):
        # Stale counter from a previous day shouldn't be reported as today's.
        _write(
            cache_dir / FETCHER_DAILY_STATE_FILE,
            {"date": "1970-01-01", "count": 999},
        )
        r = client.get("/admin/status")
        body = r.json()
        assert body["fetcher_state"]["calls_today"] == 0


class TestAdminStatusIngestionState:

    def test_idle_state_with_last_completed(
        self, cache_dir, empty_qdrant, client
    ):
        _write(
            cache_dir / INGESTION_STATE_FILE,
            {
                "status": "idle",
                "started_at": "2026-04-27T10:00:00+00:00",
                "last_completed": "2026-04-27T10:05:00+00:00",
                "error": None,
            },
        )
        r = client.get("/admin/status")
        body = r.json()
        assert body["ingestion_status"] == "idle"
        assert body["last_ingestion_completed"].startswith("2026-04-27T10:05:00")
        assert body["last_ingestion_error"] is None

    def test_failed_state_surfaces_error(
        self, cache_dir, empty_qdrant, client
    ):
        _write(
            cache_dir / INGESTION_STATE_FILE,
            {
                "status": "failed",
                "started_at": "2026-04-27T10:00:00+00:00",
                "last_completed": None,
                "error": "Qdrant unreachable",
            },
        )
        r = client.get("/admin/status")
        body = r.json()
        assert body["ingestion_status"] == "failed"
        assert body["last_ingestion_error"] == "Qdrant unreachable"

    def test_running_state(self, cache_dir, empty_qdrant, client):
        _write(
            cache_dir / INGESTION_STATE_FILE,
            {
                "status": "running",
                "started_at": "2026-04-27T10:00:00+00:00",
                "last_completed": None,
                "error": None,
            },
        )
        r = client.get("/admin/status")
        body = r.json()
        assert body["ingestion_status"] == "running"


# ---------------------------------------------------------------------------
# POST /admin/check-currency
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_spawn(monkeypatch):
    """Replace the subprocess spawner with a recorder that just creates the
    marker file (so a follow-up request observes 'already-running')."""

    calls = {"n": 0}

    async def fake_spawn() -> None:
        calls["n"] += 1
        # Mimic real spawn: create the running marker. We skip clearing it,
        # to simulate a long-running fetcher.
        from shared.admin_state import write_fetcher_marker
        write_fetcher_marker(datetime.now(timezone.utc).isoformat())

    monkeypatch.setattr(admin_mod, "_spawn_fetcher_subprocess", fake_spawn)
    return calls


class TestCheckCurrency:

    def test_starts_when_idle(self, cache_dir, stub_spawn, client):
        r = client.post("/admin/check-currency")
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] == "started"
        assert "started_at" in body
        # The spawner was called exactly once.
        assert stub_spawn["n"] == 1
        # The marker file now exists (recorded by fake_spawn).
        assert (cache_dir / FETCHER_RUNNING_MARKER).exists()

    def test_returns_409_when_already_running(
        self, cache_dir, stub_spawn, client
    ):
        # Pre-plant the marker so the first call is treated as in-flight.
        marker = cache_dir / FETCHER_RUNNING_MARKER
        marker.write_text(
            json.dumps({"started_at": "2026-04-27T09:00:00+00:00"}),
            encoding="utf-8",
        )

        r = client.post("/admin/check-currency")
        assert r.status_code == 409, r.text
        body = r.json()
        assert body["status"] == "already-running"
        assert body["started_at"].startswith("2026-04-27T09:00:00")
        # Spawner must NOT have been called.
        assert stub_spawn["n"] == 0

    def test_409_without_marker_payload_still_ok(
        self, cache_dir, stub_spawn, client
    ):
        # Marker file present but with malformed JSON — endpoint should still
        # return 409 (the marker existing is the source of truth) and not
        # blow up.
        marker = cache_dir / FETCHER_RUNNING_MARKER
        marker.write_text("not json", encoding="utf-8")

        r = client.post("/admin/check-currency")
        assert r.status_code == 409
        body = r.json()
        assert body["status"] == "already-running"
        assert body["started_at"] is None
        assert stub_spawn["n"] == 0


# ---------------------------------------------------------------------------
# Status-derivation unit tests (no FastAPI)
# ---------------------------------------------------------------------------


class TestDeriveLawStatus:
    """Direct tests of the per-law status logic; no IO."""

    def test_no_report_no_qdrant_unknown(self):
        s, err = admin_mod._derive_law_status(None, None)
        assert s == "unknown"
        assert err is None

    def test_no_report_with_qdrant_ok(self):
        s, err = admin_mod._derive_law_status({"provisions_count": 10}, None)
        assert s == "ok"
        assert err is None

    def test_fetch_failed_dominates(self):
        report = {"status": "fetch-failed", "error": "boom"}
        s, err = admin_mod._derive_law_status(
            {"provisions_count": 10}, report
        )
        assert s == "fetch-failed"
        assert err == "boom"

    def test_outdated_when_latest_greater(self):
        report = {"status": "up-to-date", "our_version": 1, "latest_version": 24}
        qdrant = {"provisions_count": 10, "our_version_number": 1}
        s, err = admin_mod._derive_law_status(qdrant, report)
        assert s == "outdated"
        assert err is None

    def test_ok_when_versions_equal(self):
        report = {"status": "up-to-date", "our_version": 24, "latest_version": 24}
        qdrant = {"provisions_count": 10, "our_version_number": 24}
        s, err = admin_mod._derive_law_status(qdrant, report)
        assert s == "ok"

    def test_ok_when_versions_unparseable(self):
        # If something weird ends up in the report (string version), we don't
        # crash — fall through to the qdrant-presence check.
        report = {"status": "up-to-date", "our_version": "x", "latest_version": "y"}
        qdrant = {"provisions_count": 10}
        s, _ = admin_mod._derive_law_status(qdrant, report)
        assert s == "ok"

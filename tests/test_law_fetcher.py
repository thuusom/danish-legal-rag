"""
Unit tests for the live law fetcher (Issue #20).

These tests run without network access and without Qdrant. The
retsinformation-api.dk client is replaced with an in-memory fake or
mocked HTTP layer; ``time.sleep`` is replaced with a counter so the
tests don't actually block.

The transformer is exercised against the recorded API sample at
``docs/spikes/retsinformation-api-sample.json`` and its ``versions/latest``
counterpart so we get realistic shape coverage without going off-host.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ingest.cache import LawSource, RetsinformationRef
from ingest.law_fetcher import (
    FetcherError,
    LawTransformer,
    RateLimitExceeded,
    RetsinformationClient,
    _DailyCounter,
    _HourlyThrottle,
    fetch_all,
    fetch_one,
    write_currency_report,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_BASE = FIXTURE_DIR / "retsinformation-api-sample.json"
SAMPLE_LATEST = FIXTURE_DIR / "retsinformation-api-versions-latest.json"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def afl_source() -> LawSource:
    return LawSource(
        law_code="AFL",
        title="Bekendtgørelse af lov om skattemæssige afskrivninger",
        short_name="Afskrivningsloven",
        retsinformation=RetsinformationRef(year=2016, number=1147),
        seed_file=Path("ingest/data/afskrivningsloven.json"),
    )


@pytest.fixture
def isolated_cache_dir(tmp_path, monkeypatch):
    """Redirect LAW_CACHE_DIR to a tmp directory for the test."""
    cache_dir = tmp_path / "law_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LAW_CACHE_DIR", str(cache_dir))
    # Cache resolution helpers in fetcher_mod use ingest.cache.get_cache_dir,
    # which honours the env var, so no extra patching needed.
    return cache_dir


@pytest.fixture
def base_sample() -> dict:
    """The base-endpoint sample (version 1, has eli_uri)."""
    return json.loads(SAMPLE_BASE.read_text(encoding="utf-8"))


@pytest.fixture
def latest_sample() -> dict:
    """The versions/latest sample (version 24, eli_uri null)."""
    return json.loads(SAMPLE_LATEST.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fake HTTP client
# ---------------------------------------------------------------------------


class _CountingSleeper:
    """Drop-in replacement for ``time.sleep`` that records calls."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _make_mock_transport(routes: dict[str, dict]) -> httpx.MockTransport:
    """Build an httpx MockTransport that routes by URL path.

    ``routes`` maps path -> dict with keys:
      * ``status``: HTTP status (default 200)
      * ``json``: response body (only when status is 200)
      * ``text``: response text (used for non-200 statuses)
      * ``call_count``: int, incremented on each hit (we read this back)
    """

    def handler(request: httpx.Request) -> httpx.Response:
        spec = routes.get(request.url.path)
        if spec is None:
            return httpx.Response(404, text=f"no route for {request.url.path}")
        spec["call_count"] = spec.get("call_count", 0) + 1
        status = spec.get("status", 200)
        if status == 200:
            return httpx.Response(200, json=spec["json"])
        return httpx.Response(status, text=spec.get("text", ""))

    return httpx.MockTransport(handler)


def _build_client(routes: dict[str, dict], state_path: Path, sleeper=None):
    sleeper = sleeper or _CountingSleeper()
    transport = _make_mock_transport(routes)
    http_client = httpx.Client(transport=transport)
    client = RetsinformationClient(
        base_url="https://test-api.local",
        rate_limit_per_hour=3600,  # 1s interval; we mock the sleeper anyway
        rate_limit_per_day=1000,
        timeout_sec=5,
        max_retries=2,
        state_path=state_path,
        client=http_client,
        sleeper=sleeper,
    )
    return client, sleeper, routes


# ---------------------------------------------------------------------------
# LawTransformer
# ---------------------------------------------------------------------------


class TestLawTransformer:

    def test_transforms_versions_latest_with_eli_override(self, latest_sample):
        t = LawTransformer()
        out = t.transform(latest_sample, law_code="AFL", eli_override="eli/lta/2016/1147")

        assert out["law_code"] == "AFL"
        assert out["law_name"] == "Afskrivningsloven"
        assert out["law_number"] == "LBK nr 1147 af 29/08/2016"
        assert out["effective_date"] == "2016-08-29"  # signature_date
        assert out["law_version_date"] == "2021-01-01"  # top-level effective_date
        assert out["law_version_number"] == 24
        assert out["eli"] == "eli/lta/2016/1147"
        assert out["source_url"] == "https://www.retsinformation.dk/eli/lta/2016/1147"
        assert out["retsinformation_law_id"] == "7f6afaff-e089-401d-99ea-19b52a6c18cd"
        assert isinstance(out["provisions"], list)
        assert len(out["provisions"]) > 0

    def test_transforms_base_endpoint_eli_uri_present(self, base_sample):
        # When eli_uri is provided by the API, transform must use it without override.
        t = LawTransformer()
        out = t.transform(base_sample, law_code="AFL")
        assert out["eli"] == "eli/lta/2016/1147"
        assert out["source_url"] == "https://www.retsinformation.dk/eli/lta/2016/1147"

    def test_chapter_label_format(self, latest_sample):
        out = LawTransformer().transform(latest_sample, law_code="AFL")
        # AFL chapter 1 in the API is "Lovens anvendelsesområde".
        labels = {p["chapter"] for p in out["provisions"]}
        assert "Kapitel 1 \u2013 Lovens anvendelsesomr\u00e5de" in labels
        # No null chapter labels in AFL — every paragraph sits inside a chapter.
        assert all(p["chapter"] for p in out["provisions"])

    def test_section_normalisation_strips_dot(self, latest_sample):
        out = LawTransformer().transform(latest_sample, law_code="AFL")
        sections = {p["section"] for p in out["provisions"]}
        # Plain numeric paragraphs.
        assert "\u00a7 1" in sections
        assert "\u00a7 2" in sections
        # No § ends with a dot.
        assert all(not s.endswith(".") for s in sections)

    def test_letter_suffix_paragraphs_kept_lowercase(self, latest_sample):
        out = LawTransformer().transform(latest_sample, law_code="AFL")
        sections = {p["section"] for p in out["provisions"]}
        # AFL has at least § 5 a (lowercase form preferred per spike decision).
        assert any(s.startswith("\u00a7 5 ") for s in sections), (
            f"expected letter-suffix § 5 X, got {sorted(sections)[:30]}"
        )
        # No upper-case letter suffix produced by the transformer.
        for s in sections:
            tail = s.split(" ", 2)
            if len(tail) == 3 and len(tail[2]) == 1 and tail[2].isalpha():
                assert tail[2].islower(), f"letter suffix should be lowercase: {s}"

    def test_single_stk_wrapper_elision(self, latest_sample):
        out = LawTransformer().transform(latest_sample, law_code="AFL")
        # § 1 has exactly one stk in the source — the synthetic Stk. 1 wrapper
        # must be dropped to match the existing convention.
        para_1 = [p for p in out["provisions"] if p["section"] == "\u00a7 1"]
        assert len(para_1) == 1
        assert para_1[0]["subsection"] is None

        # § 2 has 3 stk — they MUST keep their subsection labels.
        para_2 = [p for p in out["provisions"] if p["section"] == "\u00a7 2"]
        assert len(para_2) == 3
        assert {p["subsection"] for p in para_2} == {"stk. 1", "stk. 2", "stk. 3"}

    def test_litra_inlined_into_text(self, latest_sample):
        out = LawTransformer().transform(latest_sample, law_code="AFL")
        # § 3 stk. 1 has 3 litra entries — they should appear in the text, not
        # as separate provisions.
        para_3 = [p for p in out["provisions"] if p["section"] == "\u00a7 3"]
        assert len(para_3) == 1
        text = para_3[0]["text"]
        assert "1) leveret til en igangv\u00e6rende virksomhed" in text
        assert "2) bestemt til at indg\u00e5 i virksomhedens drift" in text
        assert "3) f\u00e6rdiggjort" in text
        # And no separate "item" rows should have been created.
        items_for_3 = [p["item"] for p in para_3]
        assert items_for_3 == [None]

    def test_paragraph_id_propagated(self, latest_sample):
        out = LawTransformer().transform(latest_sample, law_code="AFL")
        # Most provisions carry their parent paragraph id. The upstream API
        # leaves ``id`` empty on a small handful of paragraphs (e.g. § 44 C
        # in AFL), which is annoying but not load-bearing — chunks with a
        # missing id still embed and retrieve fine. Assert that the
        # *majority* propagate, and that every present id has the expected
        # ``id<uuid>`` shape.
        ids = [p.get("retsinformation_paragraph_id") for p in out["provisions"]]
        present = [pid for pid in ids if pid]
        # ``id`` is ``None`` rather than ``""`` once we've passed through the
        # transformer's "empty -> None" coercion.
        for pid in present:
            assert isinstance(pid, str)
            assert pid.startswith("id"), f"unexpected id format: {pid}"
        assert len(present) >= int(len(ids) * 0.8), (
            f"expected >=80% of provisions to carry a paragraph id, "
            f"got {len(present)}/{len(ids)}"
        )

    def test_eli_constructed_when_missing(self):
        """If eli_uri is null and no override is given, fall back to eli/lta/{year}/{number}."""
        api = {
            "law_id": "x",
            "version_number": 1,
            "year": 2020,
            "number": 99,
            "title": "T",
            "popular_title": "Testloven",
            "short_name": "LBK nr 99 af 01/01/2020",
            "signature_date": "2020-01-01",
            "effective_date": "2020-02-01",
            "eli_uri": None,
            "structure": {
                "chapters": [
                    {
                        "chapter_number": "Kapitel 1",
                        "chapter_title": "Almindeligt",
                        "afsnit": "",
                        "paragraph_groups": [
                            {
                                "paragraphs": [
                                    {
                                        "id": "idabc",
                                        "number": "\u00a7 1.",
                                        "stk": [{"number": "Stk. 1.", "text": "Hej."}],
                                    }
                                ]
                            }
                        ],
                    }
                ]
            },
        }
        out = LawTransformer().transform(api, law_code="TEST")
        assert out["eli"] == "eli/lta/2020/99"
        assert out["source_url"] == "https://www.retsinformation.dk/eli/lta/2020/99"


# ---------------------------------------------------------------------------
# Throttle / rate limiting
# ---------------------------------------------------------------------------


class TestHourlyThrottle:

    def test_first_call_does_not_sleep(self):
        sleeper = _CountingSleeper()
        t = _HourlyThrottle(rate_per_hour=60, sleeper=sleeper)
        t.wait()
        assert sleeper.calls == []

    def test_second_call_sleeps_when_too_close(self, monkeypatch):
        # Force monotonic to advance only 1 second between calls; with rate=60
        # the interval is 60s, so we should sleep 59s on the second call.
        ts = [0.0, 1.0]

        def fake_monotonic():
            return ts.pop(0) if ts else 9999.0

        sleeper = _CountingSleeper()
        monkeypatch.setattr("ingest.law_fetcher.time.monotonic", fake_monotonic)
        t = _HourlyThrottle(rate_per_hour=60, sleeper=sleeper)
        t.wait()
        t.wait()
        assert len(sleeper.calls) == 1
        # 60s interval - 1s elapsed = 59s
        assert pytest.approx(sleeper.calls[0], abs=0.01) == 59.0


class TestDailyCounter:

    def test_increments_and_persists(self, tmp_path):
        path = tmp_path / "state.json"
        c = _DailyCounter(path, daily_limit=3)
        c.consume(1)
        c.consume(1)
        # Reload counter — must read the persisted state.
        c2 = _DailyCounter(path, daily_limit=3)
        date, count = c2.current()
        assert count == 2
        c2.consume(1)
        with pytest.raises(RateLimitExceeded):
            c2.consume(1)

    def test_resets_on_new_day(self, tmp_path):
        path = tmp_path / "state.json"
        # Manually plant yesterday's record at the limit.
        path.write_text(json.dumps({"date": "1970-01-01", "count": 999}))
        c = _DailyCounter(path, daily_limit=5)
        # Today's count should be 0 (date mismatch).
        _, count = c.current()
        assert count == 0
        c.consume(1)  # must succeed
        _, count = c.current()
        assert count == 1


# ---------------------------------------------------------------------------
# RetsinformationClient
# ---------------------------------------------------------------------------


class TestRetsinformationClient:

    def test_get_versions_latest_happy_path(self, tmp_path, latest_sample):
        routes = {
            "/v1/lovgivning/2016/1147/versions/latest": {"json": latest_sample},
        }
        state_path = tmp_path / ".state.json"
        client, _, _ = _build_client(routes, state_path)
        try:
            data = client.get_versions_latest(2016, 1147)
        finally:
            client.close()
        assert data["version_number"] == 24

    def test_retries_on_500_then_succeeds(self, tmp_path, latest_sample):
        # First call returns 500, second returns 200.
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(503, text="busy")
            return httpx.Response(200, json=latest_sample)

        transport = httpx.MockTransport(handler)
        sleeper = _CountingSleeper()
        client = RetsinformationClient(
            base_url="https://test-api.local",
            rate_limit_per_hour=3600,
            rate_limit_per_day=1000,
            max_retries=3,
            state_path=tmp_path / ".state.json",
            client=httpx.Client(transport=transport),
            sleeper=sleeper,
        )
        try:
            data = client.get_versions_latest(2016, 1147)
        finally:
            client.close()
        assert data["version_number"] == 24
        assert attempts["n"] == 2
        # We slept at least once for backoff.
        assert any(s >= 1.0 for s in sleeper.calls)

    def test_no_retry_on_404(self, tmp_path):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(404, text="not found")

        transport = httpx.MockTransport(handler)
        client = RetsinformationClient(
            base_url="https://test-api.local",
            rate_limit_per_hour=3600,
            rate_limit_per_day=1000,
            max_retries=5,
            state_path=tmp_path / ".state.json",
            client=httpx.Client(transport=transport),
            sleeper=_CountingSleeper(),
        )
        try:
            with pytest.raises(FetcherError):
                client.get_versions_latest(1999, 1)
        finally:
            client.close()
        assert attempts["n"] == 1

    def test_daily_limit_blocks_calls(self, tmp_path, latest_sample):
        routes = {
            "/v1/lovgivning/2016/1147/versions/latest": {"json": latest_sample},
        }
        state_path = tmp_path / ".state.json"
        # Pre-plant a state file at today's date with count == limit.
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        today = _dt.now(_tz.utc).date().isoformat()
        state_path.write_text(json.dumps({"date": today, "count": 1}))
        transport = httpx.MockTransport(_make_mock_transport(routes).handler)
        client = RetsinformationClient(
            base_url="https://test-api.local",
            rate_limit_per_hour=3600,
            rate_limit_per_day=1,  # already used
            max_retries=2,
            state_path=state_path,
            client=httpx.Client(transport=transport),
            sleeper=_CountingSleeper(),
        )
        try:
            with pytest.raises(RateLimitExceeded):
                client.get_versions_latest(2016, 1147)
        finally:
            client.close()


# ---------------------------------------------------------------------------
# fetch_one / fetch_all
# ---------------------------------------------------------------------------


class TestFetchOne:

    def test_writes_cache_when_missing(
        self, tmp_path, isolated_cache_dir, afl_source, latest_sample, base_sample
    ):
        routes = {
            "/v1/lovgivning/2016/1147/versions/latest": {"json": latest_sample},
            "/v1/lovgivning/2016/1147": {"json": base_sample},
        }
        client, _, _ = _build_client(routes, state_path=tmp_path / ".state.json")
        try:
            entry = fetch_one(afl_source, client, isolated_cache_dir)
        finally:
            client.close()
        assert entry["status"] == "new"
        assert entry["latest_version"] == 24
        assert entry["our_version"] == 0
        out_path = isolated_cache_dir / "AFL.json"
        assert out_path.exists()
        cached = json.loads(out_path.read_text(encoding="utf-8"))
        assert cached["law_code"] == "AFL"
        assert cached["law_version_number"] == 24
        assert cached["eli"] == "eli/lta/2016/1147"

    def test_skip_when_up_to_date(
        self, tmp_path, isolated_cache_dir, afl_source, latest_sample
    ):
        # Pre-seed a cache file at version 24 so versions/latest reports the same.
        existing = {"law_code": "AFL", "law_version_number": 24, "provisions": [{"section": "x"}]}
        (isolated_cache_dir / "AFL.json").write_text(json.dumps(existing))

        routes = {
            "/v1/lovgivning/2016/1147/versions/latest": {"json": latest_sample},
            "/v1/lovgivning/2016/1147": {"json": {}},
        }
        client, _, route_state = _build_client(routes, state_path=tmp_path / ".state.json")
        try:
            entry = fetch_one(afl_source, client, isolated_cache_dir)
        finally:
            client.close()
        assert entry["status"] == "up-to-date"
        # Only versions/latest was hit; the base endpoint was NOT called.
        assert route_state["/v1/lovgivning/2016/1147/versions/latest"]["call_count"] == 1
        assert route_state["/v1/lovgivning/2016/1147"].get("call_count", 0) == 0

    def test_updates_when_version_advances(
        self, tmp_path, isolated_cache_dir, afl_source, latest_sample, base_sample
    ):
        existing = {"law_code": "AFL", "law_version_number": 1, "provisions": [{"section": "x"}]}
        (isolated_cache_dir / "AFL.json").write_text(json.dumps(existing))

        routes = {
            "/v1/lovgivning/2016/1147/versions/latest": {"json": latest_sample},
            "/v1/lovgivning/2016/1147": {"json": base_sample},
        }
        client, _, _ = _build_client(routes, state_path=tmp_path / ".state.json")
        try:
            entry = fetch_one(afl_source, client, isolated_cache_dir)
        finally:
            client.close()
        assert entry["status"] == "updated"
        assert entry["our_version"] == 1
        assert entry["latest_version"] == 24

    def test_force_refetches_even_when_current(
        self, tmp_path, isolated_cache_dir, afl_source, latest_sample, base_sample
    ):
        existing = {"law_code": "AFL", "law_version_number": 24, "provisions": [{"section": "x"}]}
        (isolated_cache_dir / "AFL.json").write_text(json.dumps(existing))

        routes = {
            "/v1/lovgivning/2016/1147/versions/latest": {"json": latest_sample},
            "/v1/lovgivning/2016/1147": {"json": base_sample},
        }
        client, _, _ = _build_client(routes, state_path=tmp_path / ".state.json")
        try:
            entry = fetch_one(afl_source, client, isolated_cache_dir, force=True)
        finally:
            client.close()
        # Cache existed and version equals — but force flag forces an "updated".
        assert entry["status"] == "updated"

    def test_fetch_failure_marks_status_and_keeps_cache(
        self, tmp_path, isolated_cache_dir, afl_source
    ):
        sentinel = {"law_code": "AFL", "law_version_number": 1, "provisions": [{"section": "keep"}]}
        cache_path = isolated_cache_dir / "AFL.json"
        cache_path.write_text(json.dumps(sentinel))

        # All routes return 500 → after retries, fetcher gives up.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        client = RetsinformationClient(
            base_url="https://test-api.local",
            rate_limit_per_hour=3600,
            rate_limit_per_day=1000,
            max_retries=1,
            state_path=tmp_path / ".state.json",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleeper=_CountingSleeper(),
        )
        try:
            entry = fetch_one(afl_source, client, isolated_cache_dir)
        finally:
            client.close()
        assert entry["status"] == "fetch-failed"
        assert entry["error"]
        # Cache untouched.
        assert json.loads(cache_path.read_text())["provisions"][0]["section"] == "keep"

    def test_dry_run_does_not_write(
        self, tmp_path, isolated_cache_dir, afl_source, latest_sample, base_sample
    ):
        routes = {
            "/v1/lovgivning/2016/1147/versions/latest": {"json": latest_sample},
            "/v1/lovgivning/2016/1147": {"json": base_sample},
        }
        client, _, _ = _build_client(routes, state_path=tmp_path / ".state.json")
        try:
            entry = fetch_one(afl_source, client, isolated_cache_dir, dry_run=True)
        finally:
            client.close()
        assert entry["status"] == "new"
        assert not (isolated_cache_dir / "AFL.json").exists()


class TestFetchAll:

    def test_mixed_statuses(
        self, tmp_path, isolated_cache_dir, latest_sample, base_sample
    ):
        # Two sources: AFL is up-to-date already; ARL is missing → new.
        # We re-use the same sample shape for the ARL response (different
        # year/number) — what matters here is the orchestration logic.
        afl = LawSource(
            law_code="AFL",
            title="t",
            short_name="Afskrivningsloven",
            retsinformation=RetsinformationRef(year=2016, number=1147),
            seed_file=Path("ingest/data/afskrivningsloven.json"),
        )
        arl = LawSource(
            law_code="ARL",
            title="t",
            short_name="Aarsregnskabsloven",
            retsinformation=RetsinformationRef(year=2015, number=1580),
            seed_file=Path("ingest/data/aarsregnskabsloven.json"),
        )
        # Pre-seed AFL cache at v24.
        (isolated_cache_dir / "AFL.json").write_text(
            json.dumps({"law_code": "AFL", "law_version_number": 24, "provisions": [{}]})
        )

        # Prepare a synthetic ARL latest with a different version number/title.
        arl_latest = json.loads(json.dumps(latest_sample))
        arl_latest["popular_title"] = "Aarsregnskabsloven"
        arl_latest["year"] = 2015
        arl_latest["number"] = 1580
        arl_base = json.loads(json.dumps(base_sample))
        arl_base["eli_uri"] = "/eli/lta/2015/1580"
        arl_base["year"] = 2015
        arl_base["number"] = 1580

        routes = {
            "/v1/lovgivning/2016/1147/versions/latest": {"json": latest_sample},
            "/v1/lovgivning/2016/1147": {"json": base_sample},
            "/v1/lovgivning/2015/1580/versions/latest": {"json": arl_latest},
            "/v1/lovgivning/2015/1580": {"json": arl_base},
        }
        client, _, _ = _build_client(routes, state_path=tmp_path / ".state.json")
        try:
            report = fetch_all([afl, arl], client, isolated_cache_dir)
        finally:
            client.close()

        statuses = {e["law_code"]: e["status"] for e in report["sources"]}
        assert statuses == {"AFL": "up-to-date", "ARL": "new"}
        assert (isolated_cache_dir / "ARL.json").exists()
        # AFL cache file untouched (status is up-to-date).
        afl_data = json.loads((isolated_cache_dir / "AFL.json").read_text())
        assert afl_data["law_version_number"] == 24

    def test_currency_report_written(
        self, tmp_path, isolated_cache_dir, afl_source, latest_sample, base_sample
    ):
        routes = {
            "/v1/lovgivning/2016/1147/versions/latest": {"json": latest_sample},
            "/v1/lovgivning/2016/1147": {"json": base_sample},
        }
        client, _, _ = _build_client(routes, state_path=tmp_path / ".state.json")
        try:
            report = fetch_all([afl_source], client, isolated_cache_dir)
            path = write_currency_report(report, isolated_cache_dir)
        finally:
            client.close()
        assert path.exists()
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk["sources"][0]["law_code"] == "AFL"
        assert on_disk["sources"][0]["status"] in {"new", "updated", "up-to-date"}
        assert "checked_at" in on_disk


# ---------------------------------------------------------------------------
# Live network validation (opt-in via FETCHER_LIVE_VALIDATE=1)
# ---------------------------------------------------------------------------
#
# These tests hit retsinformation-api.dk for real to satisfy the spike's
# follow-up: validate the fetcher against >=3 distinct laws (AFL, ARL, SFL).
# They are skipped by default — CI doesn't need them — and run by hand
# once per fetcher change. Cost: 6 calls (2 per law).


import os  # noqa: E402  -- imported here so the file works in both modes


@pytest.mark.skipif(
    os.environ.get("FETCHER_LIVE_VALIDATE") != "1",
    reason="set FETCHER_LIVE_VALIDATE=1 to hit retsinformation-api.dk",
)
class TestLiveValidation:
    """Real-network smoke tests against retsinformation-api.dk."""

    @pytest.mark.parametrize(
        "law_code,year,number",
        [
            ("AFL", 2016, 1147),
            ("ARL", 2015, 1580),
            ("SFL", 2022, 835),
        ],
    )
    def test_fetch_and_transform(self, tmp_path, law_code, year, number):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        source = LawSource(
            law_code=law_code,
            title="t",
            short_name=law_code,
            retsinformation=RetsinformationRef(year=year, number=number),
            seed_file=Path(f"ingest/data/{law_code}.json"),
        )
        with RetsinformationClient(state_path=cache_dir / ".state.json") as client:
            entry = fetch_one(source, client, cache_dir)
        assert entry["status"] in {"new", "updated"}, (
            f"{law_code} fetch failed: {entry}"
        )
        out = json.loads((cache_dir / f"{law_code}.json").read_text(encoding="utf-8"))
        assert out["law_code"] == law_code
        assert out["law_version_number"] is not None
        assert out["eli"] is not None
        assert len(out["provisions"]) > 0, f"{law_code} produced 0 provisions"
        # No raw "stk." remnants leaking into the section field.
        for prov in out["provisions"]:
            assert prov["section"].startswith("\u00a7 "), (
                f"unexpected section format: {prov['section']!r}"
            )
            assert not prov["section"].endswith("."), prov["section"]

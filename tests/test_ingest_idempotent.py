"""
Unit tests for idempotent re-ingestion (Issue #23).

These tests do NOT require a live Qdrant instance. They use a fake in-memory
Qdrant client that supports the subset of the API used by ingestion:
``count``, ``delete`` (filter-based), ``upsert``, ``retrieve``, and
``get_collection``-shaped helpers from :mod:`shared.qdrant_utils`.

Scope:
* Pure additions  — first ingestion of a law inserts all chunks.
* Pure deletions  — re-ingesting with one provision removed deletes the
  orphan (and the orphan is no longer searchable).
* No-op idempotency — re-ingesting the same JSON twice yields the same
  chunk count, no duplicates, no orphans.
* Cross-law isolation — ingesting law B leaves law A's chunks intact
  (delete is filter-scoped, never global).
* Empty-payload guard — refusing to wipe a law when the new payload has
  zero provisions but Qdrant already holds chunks for it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Match the runtime sys.path tweak the ingestion module relies on.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client.models import (
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
)

from shared.qdrant_utils import (
    COLLECTION_NAME,
    count_chunks_by_law_code,
    delete_chunks_by_law_code,
)

# ---------------------------------------------------------------------------
# Fake in-memory Qdrant client
# ---------------------------------------------------------------------------


class _CountResult:
    def __init__(self, count: int) -> None:
        self.count = count


class FakeQdrantClient:
    """
    Minimal in-memory stand-in for ``qdrant_client.QdrantClient``.

    Stores points keyed by id, with payload + (optional) named-vector dict.
    Supports the operations exercised by ingestion's idempotency path:
    ``count`` (filter on ``law_code``), ``delete`` (filter-based), and
    ``upsert``. Other QdrantClient methods are intentionally not modelled.
    """

    def __init__(self) -> None:
        # id -> {"payload": dict, "vector": dict}
        self._points: dict[Any, dict] = {}

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _law_codes_in_filter(flt: Filter) -> list[str]:
        codes: list[str] = []
        for cond in flt.must or []:
            if isinstance(cond, FieldCondition) and cond.key == "law_code":
                m = cond.match
                if isinstance(m, MatchValue):
                    codes.append(m.value)
        return codes

    # --- API surface used by shared.qdrant_utils ---------------------------

    def count(
        self,
        *,
        collection_name: str,
        count_filter: Filter,
        exact: bool = True,
    ) -> _CountResult:
        assert collection_name == COLLECTION_NAME
        codes = self._law_codes_in_filter(count_filter)
        if not codes:
            # Anything else would be a global count — never used by us.
            raise AssertionError(
                "FakeQdrantClient.count called without a law_code filter — "
                "this would be a global count and is forbidden by Issue #23."
            )
            # Defensive, although unreachable.
        n = sum(
            1
            for p in self._points.values()
            if p["payload"].get("law_code") in codes
        )
        return _CountResult(n)

    def delete(
        self,
        *,
        collection_name: str,
        points_selector: FilterSelector,
        wait: bool = True,
    ) -> None:
        assert collection_name == COLLECTION_NAME
        if not isinstance(points_selector, FilterSelector):
            raise AssertionError(
                "FakeQdrantClient.delete only supports FilterSelector — "
                "Issue #23 requires filter-scoped deletes, never global."
            )
        codes = self._law_codes_in_filter(points_selector.filter)
        if not codes:
            raise AssertionError(
                "FakeQdrantClient.delete refused: filter must include a "
                "law_code condition (delete must be law-scoped)."
            )
        to_remove = [
            pid
            for pid, p in self._points.items()
            if p["payload"].get("law_code") in codes
        ]
        for pid in to_remove:
            del self._points[pid]

    def upsert(
        self,
        *,
        collection_name: str,
        points: list[PointStruct],
    ) -> None:
        assert collection_name == COLLECTION_NAME
        for pt in points:
            self._points[pt.id] = {
                "payload": dict(pt.payload or {}),
                "vector": pt.vector,
            }

    # --- test-only helpers -------------------------------------------------

    def all_payloads(self) -> list[dict]:
        return [p["payload"] for p in self._points.values()]

    def payloads_for(self, law_code: str) -> list[dict]:
        return [
            p["payload"]
            for p in self._points.values()
            if p["payload"].get("law_code") == law_code
        ]

    def __len__(self) -> int:
        return len(self._points)


# ---------------------------------------------------------------------------
# Helpers for building law-shaped JSON
# ---------------------------------------------------------------------------


def _provision(section: str, text: str, **extra: Any) -> dict:
    p = {"section": section, "text": text}
    p.update(extra)
    return p


def _law_json(law_code: str, provisions: list[dict], law_name: str | None = None) -> dict:
    return {
        "law_code": law_code,
        "law_name": law_name or f"Test {law_code}",
        "law_title": f"Test title {law_code}",
        "law_number": "LBK nr 1 af 01/01/2020",
        "source_url": f"https://example.test/eli/lta/2020/{law_code.lower()}",
        "effective_date": "2020-01-01",
        "provisions": provisions,
    }


def _afl_three_provisions() -> dict:
    return _law_json(
        "AFL",
        [
            _provision("§ 1", "Loven gælder for skattemæssige afskrivninger."),
            _provision("§ 2", "Driftsmidler kan afskrives efter denne lov."),
            _provision("§ 3", "Bygninger afskrives med op til 4 procent årligt."),
        ],
        law_name="Afskrivningsloven",
    )


# ---------------------------------------------------------------------------
# delete_chunks_by_law_code / count_chunks_by_law_code
# ---------------------------------------------------------------------------


class TestDeleteChunksByLawCode:

    def test_returns_zero_on_empty_collection(self):
        client = FakeQdrantClient()
        deleted = delete_chunks_by_law_code(client, "AFL")
        assert deleted == 0
        assert len(client) == 0

    def test_deletes_only_matching_law_code(self):
        client = FakeQdrantClient()
        # Seed two laws by hand.
        client._points = {
            "a1": {"payload": {"law_code": "AFL", "section": "§ 1"}, "vector": None},
            "a2": {"payload": {"law_code": "AFL", "section": "§ 2"}, "vector": None},
            "b1": {"payload": {"law_code": "ARL", "section": "§ 1"}, "vector": None},
        }

        deleted = delete_chunks_by_law_code(client, "AFL")
        assert deleted == 2
        # ARL untouched.
        remaining_codes = {p["law_code"] for p in client.all_payloads()}
        assert remaining_codes == {"ARL"}
        assert len(client) == 1

    def test_rejects_empty_law_code(self):
        client = FakeQdrantClient()
        with pytest.raises(ValueError, match="non-empty"):
            delete_chunks_by_law_code(client, "")

    def test_count_is_filter_scoped(self):
        client = FakeQdrantClient()
        client._points = {
            "a1": {"payload": {"law_code": "AFL"}, "vector": None},
            "a2": {"payload": {"law_code": "AFL"}, "vector": None},
            "b1": {"payload": {"law_code": "ARL"}, "vector": None},
        }
        assert count_chunks_by_law_code(client, "AFL") == 2
        assert count_chunks_by_law_code(client, "ARL") == 1
        assert count_chunks_by_law_code(client, "ZZZ") == 0


# ---------------------------------------------------------------------------
# Full ingestion path with delete-then-insert
# ---------------------------------------------------------------------------


class _StubEmbedder:
    """Deterministic, hash-derived 'embedding' for offline tests."""

    model_name = "stub-embedder"
    vector_size = 4

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hash(t)
            # Tiny 4-dim vector; values bounded but distinct per text.
            out.append([
                ((h >> 0) & 0xFF) / 255.0,
                ((h >> 8) & 0xFF) / 255.0,
                ((h >> 16) & 0xFF) / 255.0,
                ((h >> 24) & 0xFF) / 255.0,
            ])
        return out

    def embed_single(self, text: str) -> list[float]:
        return self.embed([text])[0]


@pytest.fixture
def fake_qdrant() -> FakeQdrantClient:
    return FakeQdrantClient()


@pytest.fixture
def patched_run(monkeypatch, fake_qdrant, tmp_path):
    """
    Patch ``run_ingestion`` collaborators so the function runs end-to-end
    against the fake Qdrant + stub embedder, without touching the network,
    sentence-transformers, or the seed cache.
    """
    from ingest import main as ingest_main

    monkeypatch.setattr(ingest_main, "wait_for_qdrant", lambda: None)
    monkeypatch.setattr(ingest_main, "get_qdrant_client", lambda: fake_qdrant)
    monkeypatch.setattr(ingest_main, "get_embedding_provider", lambda: _StubEmbedder())
    monkeypatch.setattr(ingest_main, "ensure_collection", lambda *_a, **_k: None)
    monkeypatch.setattr(ingest_main, "is_hybrid_enabled", lambda: False)
    # Seed cache is exercised in test_cache.py — no-op here.
    monkeypatch.setattr(ingest_main, "seed_cache_from_repo", lambda: [])
    # Redirect the ingestion-state marker writes (Issue #24) to a tmp dir so
    # they don't leak into the repo / container filesystem during tests.
    state_dir = tmp_path / "law_cache"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LAW_CACHE_DIR", str(state_dir))
    return ingest_main


def _set_cached_laws(monkeypatch, ingest_main, law_jsons: list[dict]) -> None:
    """Install a stub for ``_load_laws_from_cache`` returning the given laws."""
    monkeypatch.setattr(ingest_main, "_load_laws_from_cache", lambda: list(law_jsons))


class TestIdempotentReingestion:

    def test_first_ingestion_inserts_all_chunks(
        self, monkeypatch, patched_run, fake_qdrant
    ):
        afl = _afl_three_provisions()
        _set_cached_laws(monkeypatch, patched_run, [afl])

        patched_run.run_ingestion()

        afl_chunks = fake_qdrant.payloads_for("AFL")
        assert len(afl_chunks) == 3
        sections = sorted(p["section"] for p in afl_chunks)
        assert sections == ["§ 1", "§ 2", "§ 3"]

    def test_reingest_with_removed_paragraph_removes_orphan(
        self, monkeypatch, patched_run, fake_qdrant
    ):
        # First run: 3 provisions.
        afl = _afl_three_provisions()
        _set_cached_laws(monkeypatch, patched_run, [afl])
        patched_run.run_ingestion()
        assert len(fake_qdrant.payloads_for("AFL")) == 3

        # Second run: drop § 3 from the cache.
        afl_v2 = _law_json(
            "AFL",
            afl["provisions"][:2],
            law_name="Afskrivningsloven",
        )
        _set_cached_laws(monkeypatch, patched_run, [afl_v2])
        patched_run.run_ingestion()

        afl_chunks = fake_qdrant.payloads_for("AFL")
        assert len(afl_chunks) == 2, (
            "After re-ingestion with one fewer provision, AFL must hold 2 chunks"
        )
        sections = sorted(p["section"] for p in afl_chunks)
        assert sections == ["§ 1", "§ 2"]
        # The repealed paragraph is gone from the collection entirely.
        all_sections = [p["section"] for p in fake_qdrant.all_payloads()]
        assert "§ 3" not in all_sections

    def test_reingest_unchanged_law_yields_same_chunk_count(
        self, monkeypatch, patched_run, fake_qdrant
    ):
        afl = _afl_three_provisions()
        _set_cached_laws(monkeypatch, patched_run, [afl])

        patched_run.run_ingestion()
        first = len(fake_qdrant.payloads_for("AFL"))

        # Same JSON, run again.
        patched_run.run_ingestion()
        second = len(fake_qdrant.payloads_for("AFL"))

        assert first == second == 3, (
            "Re-ingesting the same JSON must not duplicate or drop chunks"
        )

    def test_ingesting_law_b_does_not_affect_law_a(
        self, monkeypatch, patched_run, fake_qdrant
    ):
        afl = _afl_three_provisions()
        arl = _law_json(
            "ARL",
            [
                _provision("§ 1", "Årsregnskabsloven gælder for virksomheder."),
                _provision("§ 2", "Regnskaber skal være retvisende."),
            ],
            law_name="Årsregnskabsloven",
        )

        # Round 1: only AFL.
        _set_cached_laws(monkeypatch, patched_run, [afl])
        patched_run.run_ingestion()
        assert len(fake_qdrant.payloads_for("AFL")) == 3
        assert len(fake_qdrant.payloads_for("ARL")) == 0

        # Round 2: ingest ARL only — AFL must remain untouched.
        _set_cached_laws(monkeypatch, patched_run, [arl])
        patched_run.run_ingestion()
        assert len(fake_qdrant.payloads_for("AFL")) == 3, (
            "Re-ingesting ARL must not delete AFL's chunks"
        )
        assert len(fake_qdrant.payloads_for("ARL")) == 2

    def test_empty_new_payload_refused_when_law_already_ingested(
        self, monkeypatch, patched_run, fake_qdrant, caplog
    ):
        # Establish a non-empty AFL.
        afl = _afl_three_provisions()
        _set_cached_laws(monkeypatch, patched_run, [afl])
        patched_run.run_ingestion()
        assert len(fake_qdrant.payloads_for("AFL")) == 3

        # Now hand ingestion an empty payload for the same law_code.
        afl_empty = _law_json("AFL", [], law_name="Afskrivningsloven")
        _set_cached_laws(monkeypatch, patched_run, [afl_empty])

        import logging
        with caplog.at_level(logging.ERROR, logger="ingest.main"):
            patched_run.run_ingestion()

        # AFL data must be left intact.
        assert len(fake_qdrant.payloads_for("AFL")) == 3, (
            "Empty payload must not wipe an already-populated law"
        )
        assert any(
            "Refusing to wipe" in rec.message for rec in caplog.records
        ), "Expected a 'Refusing to wipe' error log line"

    def test_per_law_summary_logged(
        self, monkeypatch, patched_run, fake_qdrant, caplog
    ):
        afl = _afl_three_provisions()
        _set_cached_laws(monkeypatch, patched_run, [afl])

        import logging
        with caplog.at_level(logging.INFO, logger="ingest.main"):
            patched_run.run_ingestion()

        summary_lines = [
            rec.message for rec in caplog.records if "INGEST_SUMMARY" in rec.message
        ]
        assert summary_lines, "Expected at least one INGEST_SUMMARY log line"
        # First-run summary: added=3, deleted=0.
        assert any(
            "law_code=AFL" in line and "added=3" in line and "deleted=0" in line
            for line in summary_lines
        ), f"AFL summary not as expected. Got: {summary_lines}"


# ---------------------------------------------------------------------------
# Search-after-delete sanity check (uses fake client; verifies orphan absence)
# ---------------------------------------------------------------------------


class TestRemovedParagraphNotSearchable:
    """
    Use a search-shaped lookup against the FakeQdrantClient to confirm that a
    removed paragraph is not returned. We don't model vector similarity; we
    inspect payloads, which is sufficient: the contract is "the chunk is no
    longer in the collection", and search can never return what isn't there.
    """

    def test_removed_section_absent_from_collection(
        self, monkeypatch, patched_run, fake_qdrant
    ):
        afl = _afl_three_provisions()
        _set_cached_laws(monkeypatch, patched_run, [afl])
        patched_run.run_ingestion()

        afl_v2 = _law_json(
            "AFL",
            [p for p in afl["provisions"] if p["section"] != "§ 3"],
            law_name="Afskrivningsloven",
        )
        _set_cached_laws(monkeypatch, patched_run, [afl_v2])
        patched_run.run_ingestion()

        # Equivalent of asking "is § 3 still searchable?" — it isn't, because
        # it's not in the collection any more.
        sections = {p["section"] for p in fake_qdrant.payloads_for("AFL")}
        assert "§ 3" not in sections
        # Spot-check we haven't accidentally lost the others.
        assert {"§ 1", "§ 2"}.issubset(sections)


# ---------------------------------------------------------------------------
# Reject conditions on the helper itself
# ---------------------------------------------------------------------------


class TestDeleteHelperGuards:

    def test_filter_uses_match_value_on_law_code(self):
        """
        White-box: the helper must build a Filter that matches on law_code
        via MatchValue. We assert by intercepting the delete call.
        """
        client = MagicMock()
        client.count.return_value = _CountResult(2)

        with patch("shared.qdrant_utils.logger"):
            delete_chunks_by_law_code(client, "AFL")

        # delete should have been called once with FilterSelector wrapping a
        # Filter whose first must-condition matches law_code=AFL.
        assert client.delete.called
        kwargs = client.delete.call_args.kwargs
        selector = kwargs["points_selector"]
        assert isinstance(selector, FilterSelector)
        assert isinstance(selector.filter, Filter)
        cond = selector.filter.must[0]
        assert isinstance(cond, FieldCondition)
        assert cond.key == "law_code"
        assert isinstance(cond.match, MatchValue)
        assert cond.match.value == "AFL"

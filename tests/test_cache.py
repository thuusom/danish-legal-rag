"""
Unit tests for the ingest cache layer (Issue #21).

These tests run without Qdrant — they exercise only filesystem behaviour and
manifest validation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ingest import cache
from ingest.cache import (
    LawSource,
    list_cached_laws,
    load_sources_manifest,
    seed_cache_from_repo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_seed(path: Path, law_code: str) -> None:
    """Write a minimal but valid law JSON seed file."""
    path.write_text(
        json.dumps(
            {
                "law_code": law_code,
                "law_name": f"Test {law_code}",
                "law_title": f"Test title {law_code}",
                "law_number": "LBK nr 1 af 01/01/2020",
                "source_url": "https://example.test/eli/lta/2020/1",
                "effective_date": "2020-01-01",
                "provisions": [],
            }
        ),
        encoding="utf-8",
    )


def _build_manifest(tmp_path: Path, entries: list[dict]) -> Path:
    """Write a sources.yaml in ``tmp_path`` and return its path."""
    manifest = tmp_path / "sources.yaml"
    manifest.write_text(yaml.safe_dump({"sources": entries}, allow_unicode=True), encoding="utf-8")
    return manifest


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """
    Redirect both the cache directory and the repo root used by cache.py at a
    tmp directory, so seed file paths in the test manifest resolve cleanly.
    """
    cache_dir = tmp_path / "law_cache"
    monkeypatch.setenv("LAW_CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(cache, "REPO_ROOT", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# load_sources_manifest
# ---------------------------------------------------------------------------


class TestLoadSourcesManifest:

    def test_real_manifest_validates(self):
        """The committed sources.yaml must parse and contain all 12 laws."""
        sources = load_sources_manifest()
        assert len(sources) == 12, f"expected 12 sources, got {len(sources)}"

        codes = {s.law_code for s in sources}
        expected = {
            "AFL", "ARL", "BOG", "SEL", "MOML", "LL", "SKL", "REVL", "SFL",
            "BOG-BEK", "BOG-MBK", "MOML-BEK",
        }
        assert codes == expected

        # Each entry resolves a real seed file.
        for source in sources:
            seed = cache._resolve_seed_file(source.seed_file)
            assert seed.exists(), f"seed file missing for {source.law_code}: {seed}"

    def test_rejects_missing_law_code(self, tmp_path):
        manifest = _build_manifest(
            tmp_path,
            [
                {
                    "title": "T",
                    "short_name": "S",
                    "retsinformation": {"year": 2020, "number": 1},
                    "seed_file": "ingest/data/x.json",
                }
            ],
        )
        with pytest.raises(ValueError, match="invalid source entry"):
            load_sources_manifest(manifest)

    def test_rejects_missing_retsinformation_fields(self, tmp_path):
        manifest = _build_manifest(
            tmp_path,
            [
                {
                    "law_code": "X",
                    "title": "T",
                    "short_name": "S",
                    "retsinformation": {"year": 2020},  # missing number
                    "seed_file": "ingest/data/x.json",
                }
            ],
        )
        with pytest.raises(ValueError, match="invalid source entry"):
            load_sources_manifest(manifest)

    def test_rejects_duplicate_law_code(self, tmp_path):
        manifest = _build_manifest(
            tmp_path,
            [
                {
                    "law_code": "DUP",
                    "title": "T1",
                    "short_name": "S1",
                    "retsinformation": {"year": 2020, "number": 1},
                    "seed_file": "ingest/data/a.json",
                },
                {
                    "law_code": "DUP",
                    "title": "T2",
                    "short_name": "S2",
                    "retsinformation": {"year": 2021, "number": 2},
                    "seed_file": "ingest/data/b.json",
                },
            ],
        )
        with pytest.raises(ValueError, match="duplicate law_code"):
            load_sources_manifest(manifest)

    def test_rejects_missing_top_level_key(self, tmp_path):
        manifest = tmp_path / "sources.yaml"
        manifest.write_text(yaml.safe_dump({"foo": []}), encoding="utf-8")
        with pytest.raises(ValueError, match="top-level 'sources:'"):
            load_sources_manifest(manifest)

    def test_rejects_empty_sources_list(self, tmp_path):
        manifest = _build_manifest(tmp_path, [])
        with pytest.raises(ValueError, match="non-empty list"):
            load_sources_manifest(manifest)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_sources_manifest(tmp_path / "does-not-exist.yaml")


# ---------------------------------------------------------------------------
# seed_cache_from_repo
# ---------------------------------------------------------------------------


class TestSeedCacheFromRepo:

    def test_seeds_empty_cache(self, isolated_cache, monkeypatch):
        # Build two seed files inside the fake repo root.
        seed_a = isolated_cache / "ingest/data/a.json"
        seed_b = isolated_cache / "ingest/data/b.json"
        seed_a.parent.mkdir(parents=True, exist_ok=True)
        _write_seed(seed_a, "AAA")
        _write_seed(seed_b, "BBB")

        manifest = _build_manifest(
            isolated_cache,
            [
                {
                    "law_code": "AAA",
                    "title": "Title A",
                    "short_name": "ShortA",
                    "retsinformation": {"year": 2020, "number": 1},
                    "seed_file": "ingest/data/a.json",
                },
                {
                    "law_code": "BBB",
                    "title": "Title B",
                    "short_name": "ShortB",
                    "retsinformation": {"year": 2021, "number": 2},
                    "seed_file": "ingest/data/b.json",
                },
            ],
        )

        seeded = seed_cache_from_repo(manifest)
        assert sorted(seeded) == ["AAA", "BBB"]

        cache_dir = isolated_cache / "law_cache"
        assert (cache_dir / "AAA.json").exists()
        assert (cache_dir / "BBB.json").exists()
        # Content must match the seed.
        assert json.loads((cache_dir / "AAA.json").read_text())["law_code"] == "AAA"

    def test_partial_cache_only_fills_missing(self, isolated_cache):
        seed_a = isolated_cache / "ingest/data/a.json"
        seed_b = isolated_cache / "ingest/data/b.json"
        seed_a.parent.mkdir(parents=True, exist_ok=True)
        _write_seed(seed_a, "AAA")
        _write_seed(seed_b, "BBB")

        cache_dir = isolated_cache / "law_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Pre-populate AAA in the cache with a sentinel payload — must NOT be
        # overwritten by seeding.
        sentinel = {"law_code": "AAA", "marker": "do-not-overwrite", "provisions": []}
        (cache_dir / "AAA.json").write_text(json.dumps(sentinel), encoding="utf-8")

        manifest = _build_manifest(
            isolated_cache,
            [
                {
                    "law_code": "AAA",
                    "title": "Title A",
                    "short_name": "ShortA",
                    "retsinformation": {"year": 2020, "number": 1},
                    "seed_file": "ingest/data/a.json",
                },
                {
                    "law_code": "BBB",
                    "title": "Title B",
                    "short_name": "ShortB",
                    "retsinformation": {"year": 2021, "number": 2},
                    "seed_file": "ingest/data/b.json",
                },
            ],
        )

        seeded = seed_cache_from_repo(manifest)
        # Only BBB was missing.
        assert seeded == ["BBB"]

        # AAA still has the sentinel content.
        existing = json.loads((cache_dir / "AAA.json").read_text())
        assert existing.get("marker") == "do-not-overwrite"
        # BBB was copied from the seed.
        assert json.loads((cache_dir / "BBB.json").read_text())["law_code"] == "BBB"

    def test_idempotent_second_call(self, isolated_cache):
        seed_a = isolated_cache / "ingest/data/a.json"
        seed_a.parent.mkdir(parents=True, exist_ok=True)
        _write_seed(seed_a, "AAA")

        manifest = _build_manifest(
            isolated_cache,
            [
                {
                    "law_code": "AAA",
                    "title": "Title A",
                    "short_name": "ShortA",
                    "retsinformation": {"year": 2020, "number": 1},
                    "seed_file": "ingest/data/a.json",
                }
            ],
        )

        first = seed_cache_from_repo(manifest)
        second = seed_cache_from_repo(manifest)
        assert first == ["AAA"]
        assert second == []

    def test_missing_seed_file_raises(self, isolated_cache):
        manifest = _build_manifest(
            isolated_cache,
            [
                {
                    "law_code": "AAA",
                    "title": "Title A",
                    "short_name": "ShortA",
                    "retsinformation": {"year": 2020, "number": 1},
                    "seed_file": "ingest/data/missing.json",
                }
            ],
        )
        with pytest.raises(FileNotFoundError, match="seed file"):
            seed_cache_from_repo(manifest)


# ---------------------------------------------------------------------------
# list_cached_laws
# ---------------------------------------------------------------------------


class TestListCachedLaws:

    def test_returns_only_json_files_sorted(self, isolated_cache):
        cache_dir = isolated_cache / "law_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "BBB.json").write_text("{}", encoding="utf-8")
        (cache_dir / "AAA.json").write_text("{}", encoding="utf-8")
        (cache_dir / "ignore.txt").write_text("not json", encoding="utf-8")

        paths = list_cached_laws()
        names = [p.name for p in paths]
        assert names == ["AAA.json", "BBB.json"]

    def test_empty_cache_returns_empty(self, isolated_cache):
        # Cache dir is created lazily by get_cache_dir but contains nothing.
        paths = list_cached_laws()
        assert paths == []


# ---------------------------------------------------------------------------
# LawSource model
# ---------------------------------------------------------------------------


class TestLawSourceModel:

    def test_minimal_valid_entry(self):
        source = LawSource.model_validate(
            {
                "law_code": "AFL",
                "title": "Bekendtgørelse af lov om skattemæssige afskrivninger",
                "short_name": "Afskrivningsloven",
                "retsinformation": {"year": 2016, "number": 1147},
                "seed_file": "ingest/data/afskrivningsloven.json",
            }
        )
        assert source.law_code == "AFL"
        assert source.retsinformation.year == 2016
        assert source.retsinformation.number == 1147
        assert isinstance(source.seed_file, Path)

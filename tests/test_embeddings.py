"""
Standalone embedding tests — can run without a live Qdrant instance.

These tests verify:
- The embedding provider loads and produces vectors of the correct shape
- The LegalChunk model correctly computes embedding text and content hashes
- The chunker produces stable, deterministic chunk IDs
- Content hashes change when text changes (idempotency guard)

Run inside the API container:
  docker compose exec api python -m pytest /app/tests/test_embeddings.py -v

Or locally if dependencies are installed:
  python -m pytest tests/test_embeddings.py -v
"""
import sys
sys.path.insert(0, "/app")

import hashlib
import pytest


class TestLegalChunkModel:
    """Test the LegalChunk domain model."""

    def _make_chunk(self, **overrides):
        from shared.models import LegalChunk
        defaults = {
            "id": "test-id-123",
            "law_code": "AFL",
            "law_name": "Afskrivningsloven",
            "law_title": "Bekendtgørelse af lov om skattemæssige afskrivninger",
            "section": "§ 40 C",
            "subsection": "stk. 1",
            "item": None,
            "chapter": "Kapitel 7",
            "title": "EDB-programmer (software)",
            "text": "Udgifter til erhvervelse af EDB-programmer kan straksafskrives.",
            "citation_label": "Afskrivningsloven § 40 C, stk. 1",
            "source_url": "https://www.retsinformation.dk/eli/lta/2016/1147",
            "effective_date": "2016-08-29",
            "law_number": "LBK nr 1147 af 29/08/2016",
            "embedding_model": "paraphrase-multilingual-mpnet-base-v2",
            "embedding_content_hash": "abc123",
            "ingested_at": "2024-01-01T00:00:00+00:00",
        }
        defaults.update(overrides)
        return LegalChunk(**defaults)

    def test_compute_embedding_text_includes_law_name(self):
        """Embedding text must include law name for better semantic matching."""
        chunk = self._make_chunk()
        text = chunk.compute_embedding_text()
        assert "Afskrivningsloven" in text

    def test_compute_embedding_text_includes_section(self):
        """Embedding text must include section reference."""
        chunk = self._make_chunk()
        text = chunk.compute_embedding_text()
        assert "§ 40 C" in text

    def test_compute_embedding_text_includes_subsection(self):
        """Embedding text includes subsection if present."""
        chunk = self._make_chunk()
        text = chunk.compute_embedding_text()
        assert "stk. 1" in text

    def test_compute_embedding_text_includes_title(self):
        """Embedding text includes title in brackets if present."""
        chunk = self._make_chunk()
        text = chunk.compute_embedding_text()
        assert "EDB-programmer (software)" in text

    def test_compute_embedding_text_includes_raw_text(self):
        """Embedding text must include the actual provision text."""
        chunk = self._make_chunk()
        text = chunk.compute_embedding_text()
        assert "Udgifter til erhvervelse af EDB-programmer" in text

    def test_compute_content_hash_is_sha256(self):
        """Content hash must be a 64-character hex SHA256."""
        chunk = self._make_chunk()
        h = chunk.compute_content_hash()
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_content_hash_is_deterministic(self):
        """Same chunk must always produce the same hash."""
        chunk1 = self._make_chunk()
        chunk2 = self._make_chunk()
        assert chunk1.compute_content_hash() == chunk2.compute_content_hash()

    def test_content_hash_changes_with_text(self):
        """If text changes, hash must change (enables idempotency detection)."""
        chunk1 = self._make_chunk(text="Original tekst.")
        chunk2 = self._make_chunk(text="Ændret tekst.")
        assert chunk1.compute_content_hash() != chunk2.compute_content_hash()

    def test_to_qdrant_payload_has_all_fields(self):
        """Qdrant payload must include all required fields."""
        chunk = self._make_chunk()
        payload = chunk.to_qdrant_payload()
        required = [
            "id", "law_code", "law_name", "law_title", "section",
            "text", "citation_label", "embedding_model",
            "embedding_content_hash", "ingested_at",
        ]
        for field in required:
            assert field in payload, f"Missing field in Qdrant payload: {field}"

    def test_embedding_text_without_subsection(self):
        """Embedding text works when subsection is None."""
        chunk = self._make_chunk(subsection=None)
        text = chunk.compute_embedding_text()
        assert "§ 40 C" in text
        assert "stk." not in text

    def test_embedding_text_without_title(self):
        """Embedding text works when title is None."""
        chunk = self._make_chunk(title=None)
        text = chunk.compute_embedding_text()
        assert "[" not in text  # No bracket notation without title


class TestChunker:
    """Test the law chunker."""

    def _make_law_data(self):
        return {
            "law_code": "AFL",
            "law_name": "Afskrivningsloven",
            "law_title": "Bekendtgørelse af lov om skattemæssige afskrivninger",
            "law_number": "LBK nr 1147 af 29/08/2016",
            "source_url": "https://www.retsinformation.dk/eli/lta/2016/1147",
            "effective_date": "2016-08-29",
            "provisions": [
                {
                    "chapter": "Kapitel 7",
                    "section": "§ 40 C",
                    "subsection": "stk. 1",
                    "item": None,
                    "title": "EDB-programmer",
                    "text": "Udgifter til erhvervelse af EDB-programmer kan straksafskrives.",
                },
                {
                    "chapter": "Kapitel 7",
                    "section": "§ 40 C",
                    "subsection": "stk. 2",
                    "item": None,
                    "title": "Egenudviklet software",
                    "text": "Udgifter til udvikling af egne EDB-programmer behandles på samme måde.",
                },
            ],
        }

    def test_chunk_law_produces_one_chunk_per_provision(self):
        """Chunker must produce exactly one chunk per provision."""
        from ingest.chunker import chunk_law
        law_data = self._make_law_data()
        chunks = chunk_law(law_data, embedding_model="test-model")
        assert len(chunks) == 2

    def test_chunk_ids_are_stable(self):
        """Same provision must always get the same chunk ID."""
        from ingest.chunker import chunk_law
        law_data = self._make_law_data()
        chunks1 = chunk_law(law_data, embedding_model="model-a")
        chunks2 = chunk_law(law_data, embedding_model="model-b")
        # IDs are based on law_code + section + subsection, not embedding model
        assert chunks1[0].id == chunks2[0].id

    def test_chunk_ids_differ_between_provisions(self):
        """Different provisions must get different IDs."""
        from ingest.chunker import chunk_law
        law_data = self._make_law_data()
        chunks = chunk_law(law_data, embedding_model="test-model")
        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids)), "Duplicate chunk IDs detected"

    def test_citation_label_format(self):
        """Citation label must follow the expected format."""
        from ingest.chunker import chunk_law
        law_data = self._make_law_data()
        chunks = chunk_law(law_data, embedding_model="test-model")
        assert chunks[0].citation_label == "Afskrivningsloven § 40 C, stk. 1"
        assert chunks[1].citation_label == "Afskrivningsloven § 40 C, stk. 2"

    def test_content_hash_is_set_on_chunks(self):
        """Chunker must set the content hash on each chunk."""
        from ingest.chunker import chunk_law
        law_data = self._make_law_data()
        chunks = chunk_law(law_data, embedding_model="test-model")
        for chunk in chunks:
            assert chunk.embedding_content_hash, "Content hash must be set"
            assert len(chunk.embedding_content_hash) == 64

    def test_law_metadata_preserved(self):
        """All law metadata must be preserved in each chunk."""
        from ingest.chunker import chunk_law
        law_data = self._make_law_data()
        chunks = chunk_law(law_data, embedding_model="test-model")
        for chunk in chunks:
            assert chunk.law_code == "AFL"
            assert chunk.law_name == "Afskrivningsloven"
            assert chunk.law_number == "LBK nr 1147 af 29/08/2016"
            assert chunk.source_url == "https://www.retsinformation.dk/eli/lta/2016/1147"


class TestEmbeddingProvider:
    """Test the embedding provider (requires sentence-transformers installed)."""

    def test_provider_loads(self):
        """Embedding provider must load successfully."""
        from ingest.embedder import get_embedding_provider
        provider = get_embedding_provider()
        assert provider is not None

    def test_vector_size_is_768_for_default_model(self):
        """Default sentence-transformers model produces 768-dim vectors."""
        import os
        if os.environ.get("EMBEDDING_PROVIDER", "sentence-transformers") != "sentence-transformers":
            pytest.skip("Not using sentence-transformers")
        from ingest.embedder import get_embedding_provider
        provider = get_embedding_provider()
        assert provider.vector_size == 768

    def test_embed_single_returns_list_of_floats(self):
        """embed_single must return a list of floats."""
        from ingest.embedder import get_embedding_provider
        provider = get_embedding_provider()
        vector = provider.embed_single("Test tekst på dansk")
        assert isinstance(vector, list)
        assert all(isinstance(v, float) for v in vector)
        assert len(vector) == provider.vector_size

    def test_embed_batch_returns_correct_count(self):
        """embed must return one vector per input text."""
        from ingest.embedder import get_embedding_provider
        provider = get_embedding_provider()
        texts = ["Tekst et", "Tekst to", "Tekst tre"]
        vectors = provider.embed(texts)
        assert len(vectors) == 3
        for v in vectors:
            assert len(v) == provider.vector_size

    def test_normalized_vectors(self):
        """Vectors should be approximately unit-normalized (for cosine similarity)."""
        import math
        from ingest.embedder import get_embedding_provider
        provider = get_embedding_provider()
        vector = provider.embed_single("Afskrivning af software")
        magnitude = math.sqrt(sum(v**2 for v in vector))
        # Should be close to 1.0 (normalized)
        assert abs(magnitude - 1.0) < 0.01, f"Vector magnitude {magnitude:.4f} not close to 1.0"

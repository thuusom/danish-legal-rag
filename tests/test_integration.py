"""
Integration tests for the Danish Legal RAG system.

Tests:
1. Ingestion: Verify chunks are created and stored in Qdrant
2. Retrieval: Verify semantic search returns relevant results
3. Embeddings: Verify embeddings are generated and have correct shape
4. API: End-to-end test of the /ask endpoint

Run these tests after docker compose up:
  docker compose exec api python -m pytest /app/tests/ -v
"""
import sys

sys.path.insert(0, "/app")

import os

import httpx
import pytest

API_URL = os.environ.get("API_URL", "http://localhost:8000")
QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))


class TestIngestion:
    """Verify that ingestion has populated Qdrant correctly."""

    def test_qdrant_collection_exists(self):
        """Qdrant collection must exist after ingestion."""
        from qdrant_client import QdrantClient

        from shared.qdrant_utils import COLLECTION_NAME

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        collections = [c.name for c in client.get_collections().collections]
        assert COLLECTION_NAME in collections, f"Collection '{COLLECTION_NAME}' not found"

    def test_chunks_ingested(self):
        """Verify that chunks have been ingested."""
        from qdrant_client import QdrantClient

        from shared.qdrant_utils import COLLECTION_NAME

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        info = client.get_collection(COLLECTION_NAME)
        assert info.points_count > 0, "No chunks found in Qdrant"
        print(f"Total chunks ingested: {info.points_count}")

    def test_afl_chunks_present(self):
        """Afskrivningsloven chunks must be present."""
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        from shared.qdrant_utils import COLLECTION_NAME

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        results, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[FieldCondition(key="law_code", match=MatchValue(value="AFL"))]
            ),
            limit=1,
            with_payload=True,
        )
        assert len(results) > 0, "No Afskrivningsloven chunks found"

    def test_chunk_has_required_fields(self):
        """Each chunk must have all required metadata fields."""
        from qdrant_client import QdrantClient

        from shared.qdrant_utils import COLLECTION_NAME

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        records, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=1,
            with_payload=True,
        )
        assert records, "No records found"

        payload = records[0].payload
        required_fields = [
            "id", "law_code", "law_name", "section", "text",
            "citation_label", "embedding_model", "embedding_content_hash", "ingested_at"
        ]
        for field in required_fields:
            assert field in payload, f"Missing field: {field}"


class TestCacheLayer:
    """
    Verify that ingestion went through the law_cache indirection layer
    (Issue #21). After a successful ingestion the cache must be populated
    with one JSON file per law_code declared in sources.yaml.
    """

    def test_sources_manifest_loads(self):
        """sources.yaml must parse and list every law expected in Qdrant."""
        from ingest.cache import load_sources_manifest

        sources = load_sources_manifest()
        assert sources, "sources.yaml is empty"
        # Sanity: the canonical 12-law corpus.
        codes = {s.law_code for s in sources}
        assert "AFL" in codes
        assert "ARL" in codes

    def test_cache_directory_populated(self):
        """After ingestion, the cache directory must hold one JSON per source."""
        from ingest.cache import (
            get_cache_dir,
            list_cached_laws,
            load_sources_manifest,
        )

        sources = load_sources_manifest()
        cached = {p.stem for p in list_cached_laws()}
        cache_dir = get_cache_dir()
        for source in sources:
            assert source.law_code in cached, (
                f"missing {source.law_code}.json in cache at {cache_dir}; got {sorted(cached)}"
            )


class TestEmbeddings:
    """Verify that embeddings are generated correctly."""

    def test_embedding_model_loads(self):
        """Embedding model must load without errors."""
        from ingest.embedder import get_embedding_provider
        provider = get_embedding_provider()
        assert provider is not None
        assert provider.vector_size > 0
        print(f"Embedding model: {provider.model_name}, vector_size: {provider.vector_size}")

    def test_embed_danish_text(self):
        """Embedding must produce a vector of correct dimensions."""
        from ingest.embedder import get_embedding_provider
        provider = get_embedding_provider()

        text = "Udgifter til erhvervelse af EDB-programmer kan straksafskrives."
        vector = provider.embed_single(text)

        assert isinstance(vector, list), "Embedding must be a list"
        assert len(vector) == provider.vector_size, (
            f"Vector size mismatch: expected {provider.vector_size}, got {len(vector)}"
        )
        assert all(isinstance(v, float) for v in vector), "All values must be floats"

    def test_embeddings_stored_in_qdrant(self):
        """Qdrant points must have vectors stored."""
        from qdrant_client import QdrantClient

        from shared.qdrant_utils import COLLECTION_NAME

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        records, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=1,
            with_payload=True,
            with_vectors=True,
        )
        assert records, "No records found"
        vector = records[0].vector
        assert vector is not None, "Vector not stored in Qdrant"
        # Named vectors: vector is a dict with at least a "dense" key
        if isinstance(vector, dict):
            assert "dense" in vector, "Named 'dense' vector missing"
            assert len(vector["dense"]) > 0, "Dense vector is empty"
        else:
            # Legacy unnamed vector (pre-hybrid collections)
            assert len(vector) > 0, "Vector is empty"

    def test_content_hash_stored(self):
        """Each chunk must have embedding_content_hash in payload."""
        from qdrant_client import QdrantClient

        from shared.qdrant_utils import COLLECTION_NAME

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        records, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=5,
            with_payload=True,
        )
        for record in records:
            assert "embedding_content_hash" in record.payload
            assert len(record.payload["embedding_content_hash"]) == 64, "Hash must be SHA256 (64 hex chars)"

    def test_different_texts_produce_different_embeddings(self):
        """Different legal texts must produce different embedding vectors."""
        from ingest.embedder import get_embedding_provider
        provider = get_embedding_provider()

        text1 = "Software kan straksafskrives i anskaffelsesåret."
        text2 = "Goodwill afskrives med 1/7 af anskaffelsessummen."

        v1 = provider.embed_single(text1)
        v2 = provider.embed_single(text2)

        # Vectors should differ
        assert v1 != v2, "Different texts produced identical embeddings"

    def test_similar_texts_produce_similar_embeddings(self):
        """Semantically similar texts should have high cosine similarity."""
        import math

        from ingest.embedder import get_embedding_provider
        provider = get_embedding_provider()

        text1 = "EDB-programmer kan afskrives over 3 år"
        text2 = "Software afskrives skattemæssigt over tre år"

        v1 = provider.embed_single(text1)
        v2 = provider.embed_single(text2)

        # Cosine similarity (vectors are normalized)
        dot_product = sum(a * b for a, b in zip(v1, v2))
        magnitude1 = math.sqrt(sum(a**2 for a in v1))
        magnitude2 = math.sqrt(sum(b**2 for b in v2))
        cosine_sim = dot_product / (magnitude1 * magnitude2)

        print(f"Cosine similarity between similar texts: {cosine_sim:.3f}")
        assert cosine_sim > 0.5, f"Expected high similarity, got {cosine_sim:.3f}"


class TestRetrieval:
    """Test the retrieval pipeline."""

    def test_semantic_search_returns_results(self):
        """Semantic search must return results for relevant queries."""
        from ingest.embedder import get_embedding_provider
        from shared.qdrant_utils import get_qdrant_client, search_similar

        embedder = get_embedding_provider()
        qdrant = get_qdrant_client()

        query = "afskrivning af driftsmidler og bygninger"
        query_vector = embedder.embed_single(query)
        results = search_similar(qdrant, query_vector, limit=3)

        assert len(results) > 0, "No results returned for depreciation query"
        assert results[0]["score"] > 0.3, "Top result has very low relevance score"

        # Top result should be from a tax-relevant law (AFL is most likely,
        # but SEL/ARL also discuss depreciation in a corporate-tax context)
        top_law = results[0]["payload"].get("law_code")
        print(f"Top result: {results[0]['payload'].get('citation_label')} (score: {results[0]['score']:.3f})")
        accepted_laws = ["AFL", "ARL", "SEL"]
        assert top_law in accepted_laws, f"Unexpected law: {top_law}, expected one of {accepted_laws}"

    def test_references_preserved_in_retrieval(self):
        """Retrieved chunks must have all legal reference fields."""
        from ingest.embedder import get_embedding_provider
        from shared.qdrant_utils import get_qdrant_client, search_similar

        embedder = get_embedding_provider()
        qdrant = get_qdrant_client()

        query_vector = embedder.embed_single("immaterielle aktiver afskrivning")
        results = search_similar(qdrant, query_vector, limit=3)

        for result in results:
            payload = result["payload"]
            assert payload.get("section"), "section missing from retrieval result"
            assert payload.get("citation_label"), "citation_label missing from retrieval result"
            assert payload.get("law_name"), "law_name missing from retrieval result"


class TestAPI:
    """End-to-end API tests."""

    def test_health_check(self):
        """Health check must return 200."""
        with httpx.Client() as client:
            r = client.get(f"{API_URL}/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_ask_software_depreciation(self):
        """Primary test: ask about software depreciation."""
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                f"{API_URL}/ask",
                json={"question": "Hvordan afskrives immaterielle aktiver såsom software skattemæssigt?"},
            )

        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()

        assert "answer" in data and data["answer"], "answer field missing or empty"
        assert "references" in data and len(data["references"]) > 0, "No references returned"

        ref = data["references"][0]
        assert ref.get("law"), "reference missing law name"
        assert ref.get("section"), "reference missing section"
        assert ref.get("citation_label"), "reference missing citation_label"

        print(f"Answer preview: {data['answer'][:200]}")
        print(f"References: {[r['citation_label'] for r in data['references']]}")

    def test_ask_returns_structured_references(self):
        """References must be structured with required fields."""
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                f"{API_URL}/ask",
                json={"question": "Hvad er reglerne for EDB-programmer i afskrivningsloven?"},
            )
        assert r.status_code == 200
        data = r.json()

        for ref in data.get("references", []):
            assert "law" in ref
            assert "section" in ref
            assert "quote" in ref
            assert "citation_label" in ref

    def test_search_endpoint(self):
        """Search endpoint must return results."""
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{API_URL}/search",
                json={"query": "software afskrivning", "limit": 3},
            )
        assert r.status_code == 200
        data = r.json()
        assert len(data["results"]) > 0

    def test_laws_endpoint(self):
        """Laws endpoint must list ingested laws."""
        with httpx.Client() as client:
            r = client.get(f"{API_URL}/laws")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0
        law_codes = [law["law_code"] for law in data["laws"]]
        assert "AFL" in law_codes, "Afskrivningsloven not found in laws list"

    def test_laws_endpoint_exposes_aggregate_provenance_fields(self):
        """
        /laws response items must carry the Issue #22 aggregate fields:
        eli, law_version_date, latest_ingested_at. Values may be null
        when the live fetcher hasn't yet populated them (existing
        hand-curated JSON), but the keys must be present.
        """
        with httpx.Client() as client:
            r = client.get(f"{API_URL}/laws")
        assert r.status_code == 200
        data = r.json()
        assert data["laws"], "no laws returned"
        for law in data["laws"]:
            assert "eli" in law, f"eli missing from law summary: {law}"
            assert "law_version_date" in law, f"law_version_date missing: {law}"
            assert "latest_ingested_at" in law, f"latest_ingested_at missing: {law}"
        # At least one law must have ingested_at populated (set by chunker)
        timestamps = [law["latest_ingested_at"] for law in data["laws"]]
        assert any(t is not None for t in timestamps), (
            "No law has latest_ingested_at — chunker is not setting ingested_at"
        )

    def test_search_references_expose_provenance_fields(self):
        """
        /search responses must include eli and law_version_date on each
        reference (nullable). These are the public-facing provenance fields
        the frontend uses for deep-linking and currency display.
        """
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{API_URL}/search",
                json={"query": "software afskrivning", "limit": 3},
            )
        assert r.status_code == 200
        data = r.json()
        assert data["results"], "no results returned"
        for ref in data["results"]:
            # Keys must be present; values may be null until live fetcher runs
            assert "eli" in ref, f"eli missing from reference: {ref}"
            assert "law_version_date" in ref, f"law_version_date missing: {ref}"

    def test_search_with_retrieval_strategy_dense(self):
        """Search with explicit retrieval_strategy=dense must work."""
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{API_URL}/search",
                json={"query": "software afskrivning", "limit": 3, "retrieval_strategy": "dense"},
            )
        assert r.status_code == 200
        data = r.json()
        assert len(data["results"]) > 0

    def test_ask_with_retrieval_strategy_dense(self):
        """Ask with explicit retrieval_strategy=dense must work."""
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                f"{API_URL}/ask",
                json={
                    "question": "Hvad er reglerne for straksafskrivning?",
                    "retrieval_strategy": "dense",
                },
            )
        assert r.status_code == 200
        data = r.json()
        assert data["answer"], "Answer should not be empty"
        assert len(data["references"]) > 0


class TestAskStream:
    """Tests for the /ask/stream SSE endpoint."""

    def _parse_sse_events(self, text: str) -> list[dict]:
        """Parse SSE text into a list of JSON event dicts."""
        import json
        events = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                payload = line[len("data: "):]
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
        return events

    def test_ask_stream_returns_sse(self):
        """POST /ask/stream must return a valid SSE stream with chunk, references, and done events."""
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                f"{API_URL}/ask/stream",
                json={"question": "Hvordan afskrives software skattemæssigt?"},
            )
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

        events = self._parse_sse_events(r.text)
        assert len(events) > 0, "No SSE events received"

        event_types = [e["type"] for e in events]

        # Must have at least one chunk
        assert "chunk" in event_types, f"No 'chunk' events in stream. Got types: {event_types}"

        # Must have exactly one references event
        ref_events = [e for e in events if e["type"] == "references"]
        assert len(ref_events) == 1, f"Expected 1 references event, got {len(ref_events)}"
        refs = ref_events[0]["data"]
        assert isinstance(refs, list), "References data must be a list"
        if len(refs) > 0:
            ref = refs[0]
            assert "law" in ref, "Reference missing 'law' field"
            assert "section" in ref, "Reference missing 'section' field"
            assert "citation_label" in ref, "Reference missing 'citation_label' field"

        # Must have exactly one done event
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1, f"Expected 1 done event, got {len(done_events)}"
        assert "model_used" in done_events[0]["data"], "Done event missing 'model_used'"

        # done must be the last event
        assert events[-1]["type"] == "done", f"Last event should be 'done', got '{events[-1]['type']}'"

    def test_ask_stream_with_history(self):
        """POST /ask/stream with history must still return valid SSE."""
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                f"{API_URL}/ask/stream",
                json={
                    "question": "Hvad med goodwill?",
                    "limit": 5,
                    "history": [
                        {"role": "user", "content": "Hvordan afskrives software?"},
                        {"role": "assistant", "content": "Software kan straksafskrives."},
                    ],
                },
            )
        assert r.status_code == 200
        events = self._parse_sse_events(r.text)
        event_types = [e["type"] for e in events]
        assert "chunk" in event_types, "No chunk events with history"
        assert "done" in event_types, "No done event with history"

    def test_ask_stream_chunks_form_answer(self):
        """Concatenated chunk data should form a non-empty answer string."""
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                f"{API_URL}/ask/stream",
                json={"question": "Hvad er reglerne for straksafskrivning?"},
            )
        assert r.status_code == 200
        events = self._parse_sse_events(r.text)
        chunks = [e["data"] for e in events if e["type"] == "chunk"]
        full_answer = "".join(chunks)
        assert len(full_answer) > 10, f"Answer too short: '{full_answer}'"

    def test_nonstreaming_ask_still_works(self):
        """Regression: non-streaming /ask must still work after adding /ask/stream."""
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                f"{API_URL}/ask",
                json={"question": "Hvordan afskrives bygninger?"},
            )
        assert r.status_code == 200
        data = r.json()
        assert "answer" in data and data["answer"]
        assert "references" in data


class TestHybridSearch:
    """Tests for hybrid search. These require RETRIEVAL_STRATEGY=hybrid and re-ingested data."""

    @pytest.fixture(autouse=True)
    def _check_hybrid(self):
        """Skip hybrid tests if the collection doesn't have sparse vectors."""
        from qdrant_client import QdrantClient

        from shared.qdrant_utils import COLLECTION_NAME

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        try:
            info = client.get_collection(COLLECTION_NAME)
            has_sparse = (
                info.config.params.sparse_vectors is not None
                and "bm25" in (info.config.params.sparse_vectors or {})
            )
        except Exception:
            has_sparse = False

        if not has_sparse:
            pytest.skip("Collection has no sparse vectors (hybrid not enabled)")

    def test_hybrid_search_returns_results(self):
        """Hybrid search via /search must return results."""
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{API_URL}/search",
                json={
                    "query": "straksafskrivning af EDB-programmer",
                    "limit": 5,
                    "retrieval_strategy": "hybrid",
                },
            )
        assert r.status_code == 200
        data = r.json()
        assert len(data["results"]) > 0, "Hybrid search returned no results"
        # Verify result structure
        ref = data["results"][0]
        assert ref.get("citation_label"), "citation_label missing"
        assert ref.get("law_code"), "law_code missing"

    def test_dense_search_unaffected(self):
        """Dense search must still work even when collection has sparse vectors."""
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{API_URL}/search",
                json={
                    "query": "goodwill afskrivning",
                    "limit": 3,
                    "retrieval_strategy": "dense",
                },
            )
        assert r.status_code == 200
        data = r.json()
        assert len(data["results"]) > 0, "Dense search returned no results on hybrid collection"

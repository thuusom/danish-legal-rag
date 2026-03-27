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
import pytest
import httpx


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
        from qdrant_client.models import Filter, FieldCondition, MatchValue
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
        assert records[0].vector is not None, "Vector not stored in Qdrant"
        assert len(records[0].vector) > 0, "Vector is empty"

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

        query = "software afskrivning skattemæssigt"
        query_vector = embedder.embed_single(query)
        results = search_similar(qdrant, query_vector, limit=3)

        assert len(results) > 0, "No results returned for software query"
        assert results[0]["score"] > 0.3, "Top result has very low relevance score"

        # Top result should be from Afskrivningsloven
        top_law = results[0]["payload"].get("law_code")
        print(f"Top result: {results[0]['payload'].get('citation_label')} (score: {results[0]['score']:.3f})")
        assert top_law in ["AFL", "ARL"], f"Unexpected law: {top_law}"

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
        law_codes = [l["law_code"] for l in data["laws"]]
        assert "AFL" in law_codes, "Afskrivningsloven not found in laws list"

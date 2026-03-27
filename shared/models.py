"""
Shared domain models for the Danish Legal RAG system.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import hashlib


class LegalChunk(BaseModel):
    """
    Represents a chunk of a Danish legal text.
    Each chunk corresponds to one paragraph (§) or sub-section.

    References are preserved fully so no legal citation is lost
    even if only part of the text is retrieved.
    """
    # Identity
    id: str = Field(description="Stable UUID derived from law_code + section + subsection")

    # Legal reference metadata (preserved separately from embedding)
    law_code: str = Field(description="Short law code, e.g. 'AFL' for Afskrivningsloven")
    law_name: str = Field(description="Full law name in Danish")
    law_title: str = Field(description="Official title of the law")
    chapter: Optional[str] = Field(default=None, description="Chapter number/title if applicable")
    section: str = Field(description="Paragraph number, e.g. '§ 40'")
    subsection: Optional[str] = Field(default=None, description="Sub-section (stk.), e.g. 'stk. 2'")
    item: Optional[str] = Field(default=None, description="Item/letter (nr./litra), e.g. 'nr. 1'")
    title: Optional[str] = Field(default=None, description="Heading/title of the section if available")

    # Content
    text: str = Field(description="Full text of this legal provision")
    citation_label: str = Field(description="Human-readable citation, e.g. 'Afskrivningsloven § 40, stk. 2'")

    # Source
    source_url: Optional[str] = Field(default=None, description="Canonical URL at retsinformation.dk")
    effective_date: Optional[str] = Field(default=None, description="Date the provision became effective")
    law_number: Optional[str] = Field(default=None, description="Official law number, e.g. 'LBK nr 1147 af 29/08/2016'")

    # Embedding tracking (for idempotent ingestion)
    embedding_model: str = Field(description="Name of the embedding model used")
    embedding_content_hash: str = Field(description="SHA256 of the text used as embedding input")
    ingested_at: str = Field(description="ISO 8601 timestamp of ingestion")

    def compute_embedding_text(self) -> str:
        """
        Construct the text that will be embedded.

        Strategy: We enrich the embedding text with law name and section reference
        so semantic search can match both topic-based and reference-based queries.
        The raw reference fields are stored separately in the payload.

        Example embedding text:
          "Afskrivningsloven § 40, stk. 2 [EDB-programmer, software]:
           Udgifter til erhvervelse af EDB-programmer..."
        """
        parts = [f"{self.law_name} {self.section}"]
        if self.subsection:
            parts[0] += f", {self.subsection}"
        if self.title:
            parts[0] += f" [{self.title}]"
        parts.append(self.text)
        return "\n".join(parts)

    def compute_content_hash(self) -> str:
        """SHA256 hash of the embedding input text, used for idempotent re-ingestion."""
        return hashlib.sha256(self.compute_embedding_text().encode("utf-8")).hexdigest()

    def to_qdrant_payload(self) -> dict:
        """Serialize to Qdrant point payload (all fields except the vector itself)."""
        return {
            "id": self.id,
            "law_code": self.law_code,
            "law_name": self.law_name,
            "law_title": self.law_title,
            "chapter": self.chapter,
            "section": self.section,
            "subsection": self.subsection,
            "item": self.item,
            "title": self.title,
            "text": self.text,
            "citation_label": self.citation_label,
            "source_url": self.source_url,
            "effective_date": self.effective_date,
            "law_number": self.law_number,
            "embedding_model": self.embedding_model,
            "embedding_content_hash": self.embedding_content_hash,
            "ingested_at": self.ingested_at,
        }


class AskRequest(BaseModel):
    question: str = Field(description="Natural language question in Danish")
    limit: int = Field(default=5, ge=1, le=20, description="Max number of sources to retrieve")
    filter_law: Optional[str] = Field(default=None, description="Optional: filter by law_code, e.g. 'AFL'")


class LegalReference(BaseModel):
    law: str
    law_code: str
    section: str
    subsection: Optional[str] = None
    item: Optional[str] = None
    title: Optional[str] = None
    quote: str
    citation_label: str
    source_url: Optional[str] = None
    score: Optional[float] = None


class AskResponse(BaseModel):
    answer: str
    references: list[LegalReference]
    retrieved_context: list[dict]
    question: str
    model_used: str


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=20)
    filter_law: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[LegalReference]
    query: str

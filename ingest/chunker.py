"""
Chunker for Danish legal texts.

Converts raw law JSON data into LegalChunk objects.
Each provision (§, stk.) becomes exactly one chunk.
References are NEVER split across chunks.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from shared.models import LegalChunk

logger = logging.getLogger(__name__)


def build_citation_label(
    law_name: str,
    section: str,
    subsection: str | None,
    item: str | None,
) -> str:
    """
    Build a human-readable citation label.
    Example: 'Afskrivningsloven § 40 C, stk. 1'
    """
    label = f"{law_name} {section}"
    if subsection:
        label += f", {subsection}"
    if item:
        label += f", {item}"
    return label


def stable_chunk_id(law_code: str, section: str, subsection: str | None, item: str | None) -> str:
    """
    Generate a stable UUID-like ID based on legal reference.
    This ensures idempotent ingestion: same provision → same ID.
    """
    key = f"{law_code}:{section}:{subsection or ''}:{item or ''}"
    # Use UUID5 (namespace + name) for stable, deterministic IDs
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def chunk_law(law_data: dict, embedding_model: str) -> list[LegalChunk]:
    """
    Convert a law JSON object into a list of LegalChunk objects.

    One chunk per provision entry. The provision structure (§, stk., nr.)
    is preserved entirely in metadata fields, never merged or split.
    """
    law_code = law_data["law_code"]
    law_name = law_data["law_name"]
    law_title = law_data["law_title"]
    law_number = law_data.get("law_number")
    source_url = law_data.get("source_url")
    effective_date = law_data.get("effective_date")

    chunks: list[LegalChunk] = []
    now = datetime.now(timezone.utc).isoformat()

    for provision in law_data["provisions"]:
        section = provision["section"]
        subsection = provision.get("subsection")
        item = provision.get("item")
        chapter = provision.get("chapter")
        title = provision.get("title")
        text = provision["text"]

        chunk_id = stable_chunk_id(law_code, section, subsection, item)
        citation_label = build_citation_label(law_name, section, subsection, item)

        chunk = LegalChunk(
            id=chunk_id,
            law_code=law_code,
            law_name=law_name,
            law_title=law_title,
            law_number=law_number,
            chapter=chapter,
            section=section,
            subsection=subsection,
            item=item,
            title=title,
            text=text,
            citation_label=citation_label,
            source_url=source_url,
            effective_date=effective_date,
            embedding_model=embedding_model,
            embedding_content_hash="",  # Will be set after computing embedding text
            ingested_at=now,
        )
        # Set hash based on what will actually be embedded
        chunk.embedding_content_hash = chunk.compute_content_hash()

        chunks.append(chunk)
        logger.debug(f"Chunked: {citation_label}")

    logger.info(f"Produced {len(chunks)} chunks from {law_name}")
    return chunks

"""Claim ledger (V3 Phase 06, docs/V3-IMPLEMENTATION-PLAN.md section 9.4).

Every material research claim records a claim ID, text, type (source_fact,
calculation, inference, assumption), entity, period, units and support
status. Links identify supporting/refuting document versions and passages,
with page/table/cell where applicable. A calculation additionally records
formula ID, input fact IDs, code version and exact output.

These models are independently constructable in tests -- they do not import
or depend on `app/services/retrieval.py`'s fetcher; `SourceDocument.
content_hash` uses the same sha256-hex-string convention that module's
`FetchedDocument.content_hash` uses, so the two agree by convention, not by
coupling.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class SourceDocument(Base, UUIDPKMixin):
    __tablename__ = "source_documents"

    url: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String, index=True)  # sha256 hex
    # V3 9.1: publication time is distinct from retrieval time -- never
    # substitute one for the other.
    publication_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieval_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parser_version: Mapped[str] = mapped_column(String)
    rights_note: Mapped[str | None] = mapped_column(String, nullable=True)


class Passage(Base, UUIDPKMixin):
    __tablename__ = "passages"

    document_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("source_documents.id"), index=True)
    text: Mapped[str] = mapped_column(String)
    text_hash: Mapped[str] = mapped_column(String)  # sha256 of `text`
    location: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "page 4", "table 2 row 3"


class Fact(Base, UUIDPKMixin):
    """A source_fact, calculation, inference, or assumption -- V3 9.4."""

    __tablename__ = "facts"

    claim_type: Mapped[str] = mapped_column(String)  # "source_fact" | "calculation" | "inference" | "assumption"
    text: Mapped[str] = mapped_column(String)
    entity: Mapped[str] = mapped_column(String)
    period: Mapped[str | None] = mapped_column(String, nullable=True)
    units: Mapped[str | None] = mapped_column(String, nullable=True)
    # Stored as string, not a numeric column -- avoids a lossy type choice at
    # this layer; a numeric consumer parses/validates the typed value itself.
    value: Mapped[str | None] = mapped_column(String, nullable=True)
    support_status: Mapped[str] = mapped_column(String)  # "supported" | "unsupported" | "unknown" | "contradicted"
    # Calculation-specific, nullable, populated only when claim_type == "calculation".
    formula_id: Mapped[str | None] = mapped_column(String, nullable=True)
    input_fact_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    code_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FactPassageLink(Base, UUIDPKMixin):
    """Supporting or refuting link between a Fact and a Passage -- V3 9.4:
    'A real link without a supporting passage does not count as verified
    support' (enforced by app/services/evidence_ledger.py::verify_fact, not
    by this table alone)."""

    __tablename__ = "fact_passage_links"

    fact_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("facts.id"), index=True)
    passage_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("passages.id"), index=True)
    link_type: Mapped[str] = mapped_column(String)  # "supports" | "refutes"

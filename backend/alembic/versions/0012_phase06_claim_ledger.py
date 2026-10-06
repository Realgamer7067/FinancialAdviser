"""V3 Phase 06 claim ledger tables

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-14

docs/v3-execution/phase-06.md. Four new tables backing the claim ledger
(docs/V3-IMPLEMENTATION-PLAN.md section 9.4): source_documents, passages,
facts, fact_passage_links.

Phase 05's allocation/cash-flow/policy modules (allocation_engine.py,
cash_flow_engine.py, capacity_policy.py) are pure dataclasses/functions with
no persistence in this pass -- no migration needed for them. Phase 06's
retrieval.py and source_corpus_fixtures.py are also non-persisted (a fetcher
and a fixture module, not ORM models).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("publication_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieval_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parser_version", sa.String(), nullable=False),
        sa.Column("rights_note", sa.String(), nullable=True),
    )
    op.create_index("ix_source_documents_content_hash", "source_documents", ["content_hash"])

    op.create_table(
        "passages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("text_hash", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
    )
    op.create_index("ix_passages_document_id", "passages", ["document_id"])

    op.create_table(
        "facts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("claim_type", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("entity", sa.String(), nullable=False),
        sa.Column("period", sa.String(), nullable=True),
        sa.Column("units", sa.String(), nullable=True),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("support_status", sa.String(), nullable=False),
        sa.Column("formula_id", sa.String(), nullable=True),
        sa.Column("input_fact_ids", sa.JSON(), nullable=True),
        sa.Column("code_version", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "fact_passage_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fact_id", sa.Uuid(), sa.ForeignKey("facts.id"), nullable=False),
        sa.Column("passage_id", sa.Uuid(), sa.ForeignKey("passages.id"), nullable=False),
        sa.Column("link_type", sa.String(), nullable=False),
    )
    op.create_index("ix_fact_passage_links_fact_id", "fact_passage_links", ["fact_id"])
    op.create_index("ix_fact_passage_links_passage_id", "fact_passage_links", ["passage_id"])


def downgrade() -> None:
    op.drop_index("ix_fact_passage_links_passage_id", table_name="fact_passage_links")
    op.drop_index("ix_fact_passage_links_fact_id", table_name="fact_passage_links")
    op.drop_table("fact_passage_links")
    op.drop_table("facts")
    op.drop_index("ix_passages_document_id", table_name="passages")
    op.drop_table("passages")
    op.drop_index("ix_source_documents_content_hash", table_name="source_documents")
    op.drop_table("source_documents")

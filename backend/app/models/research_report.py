"""Research report model (V3 Phase 07, docs/V3-IMPLEMENTATION-PLAN.md section
9.6 "Follow-ups and revisions" and section 13.2 "Dependency-aware caches").

Follows the SAME natural-identity/append-only pattern already established by
`app/models/manifest.py` (DataManifestEntry): a report is never mutated after
publication -- a follow-up (`reuse_report_snapshot` or `refresh_sources`)
creates a brand-new row linked via `parent_report_id`, never an in-place edit
of the parent's `content`/`manifest_snapshot`. See `app/services/research_reuse.py`
for the read/write helpers that enforce this invariant.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class ResearchReport(Base, UUIDPKMixin):
    """Immutable once published -- V3 10.2: 'Published records are
    append-only. Corrections create revisions linked to the prior version.'
    A report is never mutated after `published_at` is set; a follow-up or
    refresh creates a NEW ResearchReport row with `parent_report_id` set."""

    __tablename__ = "research_reports"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_sessions.id"), index=True
    )
    parent_report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_reports.id"), nullable=True
    )
    # "reuse_report_snapshot" | "refresh_sources" | None for an original
    # (non-follow-up) report.
    revision_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    # Identifies content-equivalent reports for warm-cache reuse -- see
    # `research_reuse.compute_artifact_key`.
    artifact_key: Mapped[str] = mapped_column(String, index=True)
    # {"fact_ids": [...], "source_document_ids": [...], "cutoff_date": "...",
    #  "prompt_version": "...", "model_version": "..."} -- the EXACT
    # evidence/policy/prompt/model versions this report was built from,
    # frozen at publication (V3 13.2: "Company report | Manifest,
    # question/scope, prompts/models/research policy | Material new
    # evidence or freshness boundary").
    manifest_snapshot: Mapped[dict] = mapped_column(JSON)
    # The actual CompanyAssessment payload (or a placeholder dict shape if
    # the Verification worker's schema isn't wired up yet -- see report).
    content: Mapped[dict] = mapped_column(JSON)
    # Populated on a "refresh_sources" revision -- exactly which
    # source_document_ids differ from the parent (V3 9.6: "Track parent
    # session/report and changed source IDs").
    changed_source_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

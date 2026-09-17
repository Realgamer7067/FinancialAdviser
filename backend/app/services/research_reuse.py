"""Research report identity/versioning and warm-cache reuse (V3 Phase 07,
docs/V3-IMPLEMENTATION-PLAN.md section 9.6 "Follow-ups and revisions" and
section 13.2 "Dependency-aware caches").

This module is self-contained -- it does not import the pipeline, API, or
research workflow/verification modules. It owns exactly:
  - computing a deterministic artifact identity key for a "Company report"
    cache row (V3 13.2's dependency list for that row: manifest,
    question/scope, prompts/models/research policy),
  - looking up whether an identical warm artifact already exists,
  - validating and describing parent/follow-up linkage,
  - the symmetric-diff of changed source ids for a "refresh_sources"
    revision,
  - publishing a new (immutable once written) ResearchReport row without
    ever touching a parent row's own content/manifest_snapshot,
  - the "reuse both dossiers as-is" half of two-company comparison.

Freshness/staleness policy (whether an exact artifact_key match found by
`find_reusable_report` is still valid to serve) is explicitly OUT of this
module's scope -- that is a caller decision (V3 13.2: "Invalidated by ...
Material new evidence or freshness boundary" is a judgment the caller makes
using its own freshness policy, not something this lookup can decide from
the key alone).
"""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_report import ResearchReport

_VALID_REVISION_KINDS = {"reuse_report_snapshot", "refresh_sources"}


def compute_artifact_key(
    *,
    entity: str,
    question_scope: str,
    cutoff_date: str,
    prompt_version: str,
    model_version: str,
    research_policy_version: str,
) -> str:
    """Deterministic sha256-hex key over the exact dependency identity V3
    13.2 lists for a "Company report": manifest (here represented by
    cutoff_date, since the actual fact/source id set is captured separately
    in `manifest_snapshot` at publish time -- the key identifies the
    *request*, not the resulting evidence set), question/scope, and
    prompts/models/research-policy versions.

    Two calls with IDENTICAL arguments (in any order, since these are
    keyword-only) MUST produce the IDENTICAL key -- that is the whole point:
    it lets a caller detect "this exact request was already answered, reuse
    it, zero new provider/model calls" (V3 13.2: "Identical warm research
    request | Zero new provider/model calls where the artifact is still
    valid | Exact versioned inputs and freshness policy").

    Uses exact dependency identity, NEVER semantic similarity between
    financial questions (V3 13.2 says this explicitly) -- no fuzzy-matching
    or embedding logic here, just a plain hash over the exact fields.
    """
    canonical = "|".join(
        [
            "entity=" + entity,
            "question_scope=" + question_scope,
            "cutoff_date=" + cutoff_date,
            "prompt_version=" + prompt_version,
            "model_version=" + model_version,
            "research_policy_version=" + research_policy_version,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def find_reusable_report(db: AsyncSession, artifact_key: str) -> ResearchReport | None:
    """Looks up the newest published ResearchReport with this exact
    artifact_key. Returns None if none exists -- caller must then actually
    do the research, not assume reuse is available.

    Makes NO freshness/staleness judgment itself: an exact artifact_key
    match found here may still be too old under the caller's freshness
    policy (e.g. "Material new evidence or freshness boundary" per V3
    13.2) -- deciding that is out of this function's scope, the caller
    must apply its own policy to the returned report's `published_at`/
    `manifest_snapshot` before deciding to actually reuse it.
    """
    result = await db.execute(
        select(ResearchReport)
        .where(ResearchReport.artifact_key == artifact_key)
        .order_by(ResearchReport.published_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_follow_up(
    db: AsyncSession,
    *,
    parent_report_id: uuid.UUID,
    revision_kind: str,
    changed_source_ids: list[str] | None = None,
) -> dict:
    """Validates a follow-up's linkage and returns the metadata a caller
    passes into the eventual new ResearchReport(...) construction, once the
    actual follow-up research has run and produced new content.

    Does NOT create the new ResearchReport row itself -- that is
    `publish_report`'s job, called after real content exists. This function
    only validates:
      - `revision_kind` is one of "reuse_report_snapshot"/"refresh_sources",
        else ValueError.
      - `parent_report_id` references a real, PUBLISHED ResearchReport
        (queried, not assumed) -- you cannot follow up on a report that was
        never actually published, e.g. one still mid-workflow. Raises
        ValueError otherwise.
    """
    if revision_kind not in _VALID_REVISION_KINDS:
        raise ValueError(
            f"revision_kind must be one of {sorted(_VALID_REVISION_KINDS)}, got {revision_kind!r}"
        )

    result = await db.execute(
        select(ResearchReport).where(ResearchReport.id == parent_report_id)
    )
    parent = result.scalar_one_or_none()
    if parent is None:
        raise ValueError(f"parent_report_id {parent_report_id} does not reference an existing ResearchReport")
    if parent.published_at is None:
        raise ValueError(f"parent_report_id {parent_report_id} references a report that is not yet published")

    return {
        "parent_report_id": parent_report_id,
        "revision_kind": revision_kind,
        "changed_source_ids": changed_source_ids,
    }


def diff_source_ids(old_source_ids: list[str], new_source_ids: list[str]) -> list[str]:
    """Returns the SYMMETRIC DIFFERENCE (ids present in exactly one of the
    two lists), sorted for a deterministic return value -- V3 9.6: "Track
    parent session/report and changed source IDs." A refresh that adds one
    new source and drops none returns just that one new id; a refresh that
    both drops an old source and adds a new one returns both.
    """
    return sorted(set(old_source_ids) ^ set(new_source_ids))


async def publish_report(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    content: dict,
    artifact_key: str,
    manifest_snapshot: dict,
    parent_report_id: uuid.UUID | None = None,
    revision_kind: str | None = None,
    changed_source_ids: list[str] | None = None,
) -> ResearchReport:
    """Creates and flushes (does not commit) the ResearchReport row. Caller
    commits as part of its own transaction, matching this codebase's
    single-final-commit pattern (see `app/services/manifest.py`).

    CRITICAL invariant (V3 9.6: "Reusing a report can retrieve additional
    eligible passages, producing a new manifest version rather than
    mutating the old one"): this function never reads back, mutates, or
    otherwise touches a parent row's own `content`/`manifest_snapshot` --
    it only writes a brand-new row with `parent_report_id` pointing at it.
    """
    report = ResearchReport(
        session_id=session_id,
        parent_report_id=parent_report_id,
        revision_kind=revision_kind,
        artifact_key=artifact_key,
        manifest_snapshot=manifest_snapshot,
        content=content,
        changed_source_ids=changed_source_ids,
        published_at=datetime.now(timezone.utc),
    )
    db.add(report)
    await db.flush()
    return report


async def compare_two_reports(db: AsyncSession, report_id_a: uuid.UUID, report_id_b: uuid.UUID) -> dict:
    """V3 9.6: "Two-company comparison reuses each dossier, adds aligned
    comparison calculations, then synthesizes only the differences needed
    for the question." This implements the REUSE half only -- fetching
    both dossiers unmodified. The calculation/synthesis half needs the
    Verification worker's `content` schema plus a model call, neither of
    which this module owns.

    Raises ValueError if either report_id does not reference an existing
    ResearchReport.
    """
    result_a = await db.execute(select(ResearchReport).where(ResearchReport.id == report_id_a))
    report_a = result_a.scalar_one_or_none()
    if report_a is None:
        raise ValueError(f"report_id_a {report_id_a} does not reference an existing ResearchReport")

    result_b = await db.execute(select(ResearchReport).where(ResearchReport.id == report_id_b))
    report_b = result_b.scalar_one_or_none()
    if report_b is None:
        raise ValueError(f"report_id_b {report_id_b} does not reference an existing ResearchReport")

    return {
        "report_a": report_a.content,
        "report_b": report_b.content,
        "manifest_a": report_a.manifest_snapshot,
        "manifest_b": report_b.manifest_snapshot,
    }

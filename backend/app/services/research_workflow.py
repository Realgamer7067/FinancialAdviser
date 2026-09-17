"""Phase 07 research workflow worker (V3 implementation plan section 9.2
"Research state machine" and section 9.3 "Tool contracts").

Orchestrates Phase 06's retrieval (`app.services.retrieval`) and claim-ledger
(`app.services.evidence_ledger`) primitives into bounded, budgeted,
checkpointed research sessions.

State machine (V3 9.2, exact sequence):
    created -> resolving -> retrieving -> calculating -> synthesizing ->
    verifying -> ready_to_publish -> published
plus terminal-but-not-happy-path states `cancelled` and `failed`.
"Cancellation and supersession are terminal attempt states; a cancelled
attempt cannot publish later" -- enforced below as a real guard
(`_TERMINAL_STATES`), not just documentation.

Every state transition is a single atomic conditional ``UPDATE ... WHERE
id = :id AND state = :expected_state`` -- the same technique
`app/pipelines/publication.py` (Phase 01, C2) and
`app/services/model_scheduler.py` (Phase 04, C10) use to close the
read-compare-unconditional-write race: never a prior SELECT followed by a
separate, unconditional UPDATE.

The initial checklist is deterministic for standard company/fund questions
(`run_standard_checklist` -- NO model call). A model planner for nonstandard
questions is explicitly out of THIS module's scope for this task packet (see
task report) -- `run_standard_checklist` is the only checklist builder here.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import Fact, FactPassageLink, Passage, SourceDocument
from app.models.research import ResearchBranch, ResearchSession
from app.services.evidence_ledger import create_fact, link_fact_to_passage
from app.services.retrieval import FetchPolicy, RetrievalRejected, fetch_document, extract_passages
from app.utils.time import utcnow


class InvalidStateTransition(Exception):
    """Raised when a caller attempts a transition the state machine doesn't
    allow (e.g. publishing from 'cancelled')."""


class BudgetExhausted(Exception):
    """Raised when an operation would exceed the session's budget_envelope.
    Callers must catch this and transition the session to a 'partial'
    outcome with budget_exhausted_reason set, never silently continue."""


_VALID_TRANSITIONS: dict[str, set[str]] = {
    "created": {"resolving", "cancelled", "failed"},
    "resolving": {"retrieving", "cancelled", "failed"},
    "retrieving": {"calculating", "cancelled", "failed"},
    "calculating": {"synthesizing", "cancelled", "failed"},
    "synthesizing": {"verifying", "cancelled", "failed"},
    "verifying": {"ready_to_publish", "cancelled", "failed"},
    "ready_to_publish": {"published", "cancelled", "failed"},
    "published": set(),  # terminal, no transitions out
    "cancelled": set(),  # terminal
    "failed": set(),  # terminal
}

# Kept distinct from "no outgoing transitions" above (which happens to be
# the same set for this state machine) so the intent -- "cancellation of an
# already-terminal session is a no-op ERROR, not silently accepted" -- reads
# as a deliberate rule rather than an accidental byproduct of
# _VALID_TRANSITIONS' shape.
_TERMINAL_STATES = {"published", "cancelled", "failed"}

_STANDARD_BRANCH_TYPES = ("financials_valuation", "events_governance", "peers_downside")


# --------------------------------------------------------------------------
# Session lifecycle
# --------------------------------------------------------------------------


async def create_session(
    db: AsyncSession,
    *,
    user_id,
    question: str,
    instrument_ids: list,
    mode: str,
    cutoff_policy: dict,
    budget_envelope: dict,
    parent_session_id=None,
) -> ResearchSession:
    now = utcnow()
    session = ResearchSession(
        user_id=user_id,
        question=question,
        instrument_ids=instrument_ids,
        mode=mode,
        cutoff_policy=cutoff_policy,
        state="created",
        parent_session_id=parent_session_id,
        budget_envelope=budget_envelope,
        budget_consumed={},
        named_gaps=[],
        budget_exhausted_reason=None,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    await db.flush()
    return session


async def transition(db: AsyncSession, session_id, new_state: str) -> ResearchSession:
    """Atomic conditional UPDATE guarding the transition -- reuses the
    technique from `app/pipelines/publication.py`: a single
    ``UPDATE ... WHERE id = :id AND state = :current_state`` statement,
    never a prior SELECT then a separate UPDATE. Raises
    InvalidStateTransition if new_state isn't in
    _VALID_TRANSITIONS[current_state]."""
    session = await db.get(ResearchSession, session_id)
    if session is None:
        raise ValueError(f"no ResearchSession with id {session_id!r}")

    current_state = session.state
    allowed = _VALID_TRANSITIONS.get(current_state, set())
    if new_state not in allowed:
        raise InvalidStateTransition(
            f"research session {session_id}: cannot transition from {current_state!r} to "
            f"{new_state!r}; allowed targets from {current_state!r}: {sorted(allowed)}"
        )

    now = utcnow()
    result = await db.execute(
        update(ResearchSession)
        .where(ResearchSession.id == session_id, ResearchSession.state == current_state)
        .values(state=new_state, updated_at=now)
    )
    if result.rowcount == 0:
        # The pre-check above passed against a stale in-memory value, but the
        # atomic UPDATE's WHERE clause found the row no longer in that state
        # (changed concurrently) -- never fall back to an unconditional write.
        raise InvalidStateTransition(
            f"research session {session_id}: state changed concurrently before this "
            f"transition to {new_state!r} could apply (expected current state {current_state!r})"
        )
    await db.refresh(session)
    return session


async def cancel_session(db: AsyncSession, session_id) -> ResearchSession:
    """Transitions to 'cancelled' from ANY non-terminal state (bypasses the
    normal forward-only _VALID_TRANSITIONS check for this one case). A
    session already in 'published'/'cancelled'/'failed' raises
    InvalidStateTransition -- cancellation of an already-terminal session is
    a no-op error, not silently accepted."""
    session = await db.get(ResearchSession, session_id)
    if session is None:
        raise ValueError(f"no ResearchSession with id {session_id!r}")

    current_state = session.state
    if current_state in _TERMINAL_STATES:
        raise InvalidStateTransition(
            f"research session {session_id}: cannot cancel -- already terminal in state {current_state!r}"
        )

    now = utcnow()
    result = await db.execute(
        update(ResearchSession)
        .where(ResearchSession.id == session_id, ResearchSession.state == current_state)
        .values(state="cancelled", updated_at=now)
    )
    if result.rowcount == 0:
        raise InvalidStateTransition(
            f"research session {session_id}: state changed concurrently before cancellation could apply"
        )
    await db.refresh(session)
    return session


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------


def _resolve_budget_key(envelope: dict, resource: str) -> str | None:
    """The frozen ResearchSession.budget_envelope example uses "max_"-prefixed
    keys (e.g. "max_fetches"), while check_budget's own docstring/callers use
    bare resource names ("fetches"). Accept either spelling so a session
    created with the documented envelope shape actually gets enforced,
    instead of silently failing open because of a naming mismatch. Prefers
    the "max_"-prefixed spelling when both are present (matches the model's
    documented example); returns None if neither key exists (unbounded)."""
    prefixed = f"max_{resource}"
    if prefixed in envelope:
        return prefixed
    if resource in envelope:
        return resource
    return None


def check_budget(session: ResearchSession, resource: str, amount: int) -> None:
    """Raises BudgetExhausted if consuming `amount` more of `resource`
    (e.g. 'searches', 'fetches', 'tokens') would exceed the matching entry
    in session.budget_envelope -- accepting either the bare resource name or
    the "max_"-prefixed spelling documented on the model (see
    `_resolve_budget_key`). Pure function, no I/O -- caller updates
    budget_consumed (under the SAME resolved key) and persists separately
    after this check passes.

    A resource absent from budget_envelope under either spelling is treated
    as unbounded for that resource (no limit configured), never as zero --
    an envelope that simply omits a key is not the same as a key explicitly
    set to 0."""
    envelope = session.budget_envelope or {}
    key = _resolve_budget_key(envelope, resource)
    if key is None:
        return
    limit = envelope[key]
    consumed = session.budget_consumed or {}
    current = consumed.get(key, 0)
    if current + amount > limit:
        raise BudgetExhausted(
            f"resource {resource!r} (envelope key {key!r}): consuming {amount} more would exceed "
            f"budget limit {limit} (already consumed {current})"
        )


# --------------------------------------------------------------------------
# Branch checklist / execution
# --------------------------------------------------------------------------


async def run_standard_checklist(db: AsyncSession, session_id) -> list[ResearchBranch]:
    """Deterministic branch creation for a STANDARD (non-deep) question --
    NO model call. Creates exactly 3 ResearchBranch rows: financials_valuation,
    events_governance, peers_downside, each status='pending'."""
    session = await db.get(ResearchSession, session_id)
    if session is None:
        raise ValueError(f"no ResearchSession with id {session_id!r}")

    branches = []
    for branch_type in _STANDARD_BRANCH_TYPES:
        branch = ResearchBranch(
            session_id=session.id,
            branch_type=branch_type,
            status="pending",
            fact_ids=[],
            gap_reason=None,
            started_at=None,
            completed_at=None,
        )
        db.add(branch)
        branches.append(branch)
    await db.flush()
    return branches


def _branch_entity_label(session: ResearchSession) -> str:
    if session.instrument_ids:
        return str(session.instrument_ids[0])
    return session.question


async def run_branch(
    db: AsyncSession,
    branch_id,
    *,
    fetch_urls: list[str],
    retrieval_policy: FetchPolicy,
    resolver=None,
) -> ResearchBranch:
    """Runs ONE branch. See module/task docstring for the full failure-
    handling matrix (complete / partial / unavailable / failed), and the
    budget-exhaustion-mid-branch rule."""
    branch = await db.get(ResearchBranch, branch_id)
    if branch is None:
        raise ValueError(f"no ResearchBranch with id {branch_id!r}")
    session = await db.get(ResearchSession, branch.session_id)
    if session is None:
        raise ValueError(f"research branch {branch_id} references missing session {branch.session_id}")

    branch.status = "running"
    branch.started_at = utcnow()
    await db.flush()

    fetch_kwargs = {} if resolver is None else {"resolver": resolver}

    succeeded_urls: list[str] = []
    failed_urls: list[tuple[str, str]] = []
    new_fact_ids: list[str] = []
    budget_exhausted_msg: str | None = None

    try:
        for url in fetch_urls:
            try:
                check_budget(session, "fetches", 1)
            except BudgetExhausted as exc:
                budget_exhausted_msg = str(exc)
                break

            budget_key = _resolve_budget_key(session.budget_envelope or {}, "fetches") or "fetches"
            consumed = dict(session.budget_consumed or {})
            consumed[budget_key] = consumed.get(budget_key, 0) + 1
            session.budget_consumed = consumed
            session.updated_at = utcnow()
            await db.flush()

            try:
                document = await fetch_document(url, retrieval_policy, **fetch_kwargs)
            except RetrievalRejected as exc:
                failed_urls.append((url, str(exc)))
                continue

            passages = extract_passages(document)
            if not passages:
                failed_urls.append((url, "no passages extracted from fetched document"))
                continue

            source_doc = SourceDocument(
                url=document.url,
                content_hash=document.content_hash,
                publication_time=None,  # not derivable from the fetched document alone here
                retrieval_time=document.retrieved_at,
                parser_version="research_workflow-v1",
                rights_note=None,
            )
            db.add(source_doc)
            await db.flush()

            entity_label = _branch_entity_label(session)
            for passage_text in passages:
                passage = Passage(
                    document_id=source_doc.id,
                    text=passage_text,
                    text_hash=hashlib.sha256(passage_text.encode("utf-8")).hexdigest(),
                    location=None,
                )
                db.add(passage)
                await db.flush()

                # A plain source_fact claim is enough for this function's
                # job -- calculation facts are a later synthesis step.
                fact = await create_fact(
                    db,
                    claim_type="source_fact",
                    text=passage_text[:1000],
                    entity=entity_label,
                    period=None,
                    units=None,
                    value=None,
                )
                await link_fact_to_passage(db, fact.id, passage.id, "supports")
                new_fact_ids.append(str(fact.id))

            succeeded_urls.append(url)
    except Exception as exc:  # noqa: BLE001 -- deliberate broad catch, see docstring
        branch.status = "failed"
        branch.gap_reason = f"unexpected error while running branch: {exc}"
        branch.fact_ids = list(branch.fact_ids or []) + new_fact_ids
        branch.completed_at = utcnow()
        _append_named_gap(session, branch)
        await db.flush()
        return branch

    branch.fact_ids = list(branch.fact_ids or []) + new_fact_ids

    if budget_exhausted_msg is not None:
        branch.status = "partial"
        branch.gap_reason = f"budget exhausted mid-branch: {budget_exhausted_msg}"
        # V3 9.2: "session outcome includes ... an explicit budget_exhausted
        # reason when applicable" -- BudgetExhausted's own docstring requires
        # the catching caller (this function) to set this on the session,
        # never silently continue.
        session.budget_exhausted_reason = budget_exhausted_msg
    elif not fetch_urls:
        branch.status = "unavailable"
        branch.gap_reason = "no fetch_urls provided for this branch"
    elif succeeded_urls and not failed_urls:
        branch.status = "complete"
        branch.gap_reason = None
    elif succeeded_urls and failed_urls:
        branch.status = "partial"
        branch.gap_reason = "some sources unavailable: " + "; ".join(f"{u}: {reason}" for u, reason in failed_urls)
    else:  # nothing succeeded, everything failed
        branch.status = "unavailable"
        branch.gap_reason = "no evidence could be retrieved: " + "; ".join(
            f"{u}: {reason}" for u, reason in failed_urls
        )

    branch.completed_at = utcnow()
    if branch.status in ("partial", "unavailable"):
        _append_named_gap(session, branch)
    await db.flush()
    return branch


def _append_named_gap(session: ResearchSession, branch: ResearchBranch) -> None:
    """Session.named_gaps column comment: 'filled when a branch ends
    partial/unavailable' -- also extended here to 'failed' branches, since
    a failed branch is just as much a gap in the session's evidence as a
    partial/unavailable one. Copy-then-reassign (like budget_consumed
    above) so SQLAlchemy's JSON column change-tracking actually sees a new
    list object, not an in-place mutation of the old one."""
    gaps = list(session.named_gaps or [])
    gaps.append(
        {
            "branch_id": str(branch.id),
            "branch_type": branch.branch_type,
            "status": branch.status,
            "reason": branch.gap_reason,
        }
    )
    session.named_gaps = gaps
    session.updated_at = utcnow()


# --------------------------------------------------------------------------
# Contradiction detection
# --------------------------------------------------------------------------


async def check_material_contradiction(db: AsyncSession, session_id) -> list[dict]:
    """Scans the session's branches' Fact rows for 'refutes'-type
    FactPassageLink conflicts and returns a list of
    {"fact_id": ..., "reason": ...} for each contradiction found.

    THIS function only DETECTS contradictions; triggering an actual
    follow-up fetch is left to the caller -- see task report for why no
    follow-up-trigger helper was built here (out of this function's scope
    per the task packet)."""
    branch_rows = (
        await db.execute(select(ResearchBranch).where(ResearchBranch.session_id == session_id))
    ).scalars().all()

    fact_id_strs: set[str] = set()
    for branch in branch_rows:
        fact_id_strs.update(branch.fact_ids or [])
    if not fact_id_strs:
        return []

    fact_uuids = [uuid.UUID(f) for f in fact_id_strs]
    result = await db.execute(
        select(FactPassageLink, Fact)
        .join(Fact, FactPassageLink.fact_id == Fact.id)
        .where(FactPassageLink.link_type == "refutes", FactPassageLink.fact_id.in_(fact_uuids))
    )

    contradictions = []
    for link, fact in result.all():
        contradictions.append(
            {
                "fact_id": str(fact.id),
                "reason": (
                    f"fact {fact.id} ({fact.claim_type} for {fact.entity!r}) has a 'refutes' "
                    f"link to passage {link.passage_id} -- material contradiction, needs a "
                    f"targeted follow-up (V3 9.2)"
                ),
            }
        )
    return contradictions

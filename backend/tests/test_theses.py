"""Phase 09: theses, evidence independence, assessments, price events."""

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.single_user import SINGLE_USER_ID
from app.main import app
from app.models.evidence import Fact, FactPassageLink, Passage, SourceDocument
from app.models.market import Instrument, MarketCandle
from app.models.research import ResearchSession
from app.models.theses import Thesis, ThesisAssessment, ThesisEvent
from app.models.user import User
from app.portfolio_intelligence.research import thesis as logic
from app.portfolio_intelligence.research.independence import assign_lineages, fact_provenance
from app.portfolio_intelligence.research.researcher import MappingOutcome, ResearchOutcome, get_thesis_researcher
from app.portfolio_intelligence.research.thesis import ConditionVerdict, aggregate_status, validate_verdicts
from app.utils.time import utcnow
from tests.test_decisions import acct, complete_setup, current, dep, eq, imp, run_reviews, seed  # noqa: F401

ISIN_REL = "INE002A01018"


# --- pure ------------------------------------------------------------------------------------------

def test_lineages_count_sources_not_links():
    docs = [{"id": "a", "url": "https://www.company.com/results", "content_hash": "h1"},
            {"id": "b", "url": "https://company.com/other-page", "content_hash": "h2"},       # same outlet: one lineage
            {"id": "c", "url": "https://news.example/story", "content_hash": "h3"},
            {"id": "d", "url": "https://mirror.example/story-copy", "content_hash": "h3"}]  # identical content: one lineage
    lin = assign_lineages(docs)
    assert lin["a"] == lin["b"] == "company.com"
    assert lin["c"] == lin["d"]
    assert len(set(lin.values())) == 2


def prov(fid, text, *, status="supported", lineages=("a.com",), value=None):
    return {"fact_id": fid, "text": text, "value": value, "support_status": status, "lineages": list(lineages),
            "independent_sources": len(lineages)}


CONDS = [{"id": "c1", "text": "Revenue keeps growing", "kind": "supports"}, {"id": "c2", "text": "A promoter sells its stake", "kind": "invalidates"}]


def test_validation_drops_unknown_unverified_and_uncited_verdicts():
    p = {"f1": prov("f1", "Revenue grew 12 percent in FY26"), "f2": prov("f2", "rumour", status="unsupported")}
    out = validate_verdicts(CONDS, [
        ConditionVerdict(condition_id="c1", verdict="supported", cited_fact_ids=["f1", "invented"], note="Revenue grew 12 percent"),
        ConditionVerdict(condition_id="c2", verdict="supported", cited_fact_ids=["f2"]),           # only an unverified fact
        ConditionVerdict(condition_id="zzz", verdict="supported", cited_fact_ids=["f1"])],         # unknown condition id
        p)
    assert out[0]["verdict"] == "supported" and out[0]["cited_fact_ids"] == ["f1"] and any("unknown or unverified" in d for d in out[0]["dropped"])
    assert out[0]["note"] == "Revenue grew 12 percent"
    assert out[1]["verdict"] == "no_evidence" and out[1]["cited_fact_ids"] == []  # an unverified fact is not evidence
    assert [r["condition_id"] for r in out] == ["c1", "c2"]


def test_numbers_in_model_prose_must_come_from_cited_facts():
    p = {"f1": prov("f1", "Revenue grew 12 percent in FY26")}
    bad = validate_verdicts(CONDS[:1], [ConditionVerdict(condition_id="c1", verdict="supported", cited_fact_ids=["f1"],
                                                         note="Revenue grew 40 percent")], p)[0]
    assert bad["verdict"] == "supported" and bad["note"] == "" and any("numbers not found" in d for d in bad["dropped"])
    nocite = validate_verdicts(CONDS[:1], [ConditionVerdict(condition_id="c1", verdict="supported", cited_fact_ids=[])], p)[0]
    assert nocite["verdict"] == "no_evidence" and any("no verified evidence" in d for d in nocite["dropped"])


def row(kind, verdict, sources=1):
    return {"condition_id": "x", "text": f"{kind} {verdict}", "kind": kind, "verdict": verdict, "independent_sources": sources}


def test_status_rules_are_qualitative_and_conservative():
    assert aggregate_status([row("supports", "supported", 2), row("invalidates", "no_evidence", 0)])[0] == "supported"
    s, why = aggregate_status([row("supports", "supported", 1)])
    assert s == "mixed" and "single source" in why[0]  # a single source can never reach "supported"
    assert aggregate_status([row("supports", "supported", 3), row("invalidates", "supported", 1)])[0] == "weakened"
    assert aggregate_status([row("supports", "contradicted", 1)])[0] == "weakened"
    assert aggregate_status([row("supports", "supported", 2), row("supports", "contradicted", 1)])[0] == "mixed"
    assert aggregate_status([row("supports", "no_evidence", 0), row("invalidates", "no_evidence", 0)])[0] == "insufficient"
    assert aggregate_status([row("invalidates", "contradicted", 1)])[0] == "insufficient"  # "it has not happened" does not prove the thesis
    assert aggregate_status([])[0] == "insufficient"


def test_change_log_names_what_moved():
    prior = [{"condition_id": "c1", "verdict": "supported"}]
    now = [{"condition_id": "c1", "verdict": "contradicted", "text": "Revenue keeps growing"}]
    log = logic.change_log("supported", "weakened", now, prior)
    assert "changed from supported to weakened" in log and "supported -> contradicted" in log
    assert logic.change_log(None, "mixed", now, None) == "First assessment: mixed."


# --- DB-backed ----------------------------------------------------------------------------------------

class FakeResearcher:
    def __init__(self, db_factory=None):
        self.fact_ids: list[str] = []
        self.verdicts: list[ConditionVerdict] = []
        self.map_used = True
        self.gaps: list[str] = []
        self.session_id = None
        self.verification = {"total_material_claims": 2, "supported_count": 2, "unsupported_count": 0, "unknown_count": 0,
                             "contradicted_count": 0, "unresolved_critical_claim_ids": [], "fully_verifiable": True}
        self.contradictions: list[dict] = []

    async def gather(self, db, thesis):
        return ResearchOutcome(self.session_id, self.fact_ids, self.verification, self.contradictions, list(self.gaps))

    async def map_conditions(self, thesis, facts):
        return MappingOutcome(self.verdicts if self.map_used else [], {"used": self.map_used, "model": "fake", "prompt_version": "t", "error": None if self.map_used else "no key"})


@pytest.fixture
def researcher():
    r = FakeResearcher()
    app.dependency_overrides[get_thesis_researcher] = lambda: r
    yield r
    app.dependency_overrides.pop(get_thesis_researcher, None)


async def evidence(db, specs):
    """specs: [(fact text, status, [(url, passage text)...])] -> fact ids"""
    ids = []
    for text, status, sources in specs:
        f = Fact(claim_type="source_fact", text=text, entity="RELIANCE", period="FY26", units=None, value=None, support_status=status, created_at=utcnow())
        db.add(f)
        await db.flush()
        for url, passage in sources:
            doc = SourceDocument(url=url, content_hash=hashlib.sha256(url.encode()).hexdigest(), retrieval_time=utcnow(), parser_version="t",
                                 publication_time=datetime(2026, 9, 1, tzinfo=timezone.utc))
            db.add(doc)
            await db.flush()
            p = Passage(document_id=doc.id, text=passage, text_hash=hashlib.sha256(passage.encode()).hexdigest(), location="page 1")
            db.add(p)
            await db.flush()
            db.add(FactPassageLink(fact_id=f.id, passage_id=p.id, link_type="supports"))
        ids.append(str(f.id))
    await db.commit()
    return ids


def thesis_body(inst, **kw):
    b = {"instrument_id": str(inst.id), "ownership": "considered", "reason": "Strong retail growth and stable margins",
         "conditions": [{"text": "Revenue keeps growing", "kind": "supports"}, {"text": "The promoter sells a large stake", "kind": "invalidates"}],
         "confirmed": True}
    b.update(kw)
    return b


async def setup_thesis(client, db, **kw):
    await seed(db)
    inst = (await db.execute(select(Instrument).where(Instrument.symbol == "RELIANCE"))).scalar_one()
    r = await client.post("/api/v4/theses", json=thesis_body(inst, **kw))
    assert r.status_code == 201, r.text
    return inst, r.json()


async def test_creation_rules(client, db_session):
    await seed(db_session)
    inst = (await db_session.execute(select(Instrument).where(Instrument.symbol == "RELIANCE"))).scalar_one()
    assert (await client.post("/api/v4/theses", json=thesis_body(inst, confirmed=False))).status_code == 422  # never inferred
    assert (await client.post("/api/v4/theses", json=thesis_body(inst, reason="short"))).status_code == 422
    assert (await client.post("/api/v4/theses", json=thesis_body(inst, conditions=[]))).status_code == 422
    dup = [{"text": "Same thing", "kind": "supports"}, {"text": "same THING", "kind": "invalidates"}]
    assert (await client.post("/api/v4/theses", json=thesis_body(inst, conditions=dup))).status_code == 422
    assert (await client.post("/api/v4/theses", json=thesis_body(inst, instrument_id=str(uuid.uuid4())))).status_code == 422
    owned = await client.post("/api/v4/theses", json=thesis_body(inst, ownership="owned"))
    assert owned.status_code == 422 and "not a matched, valued holding" in owned.json()["detail"]
    ok = await client.post("/api/v4/theses", json=thesis_body(inst))
    assert ok.status_code == 201 and [c["id"] for c in ok.json()["conditions"]] == ["c1", "c2"]


async def test_owned_thesis_requires_a_matched_holding(client, db_session):
    a, b = await complete_setup(client, db_session)
    inst = (await db_session.execute(select(Instrument).where(Instrument.symbol == "RELIANCE"))).scalar_one()
    assert (await client.post("/api/v4/theses", json=thesis_body(inst, ownership="owned"))).status_code == 201


async def test_edit_keeps_condition_ids_and_version_rules(client, db_session):
    inst, t = await setup_thesis(client, db_session)
    body = thesis_body(inst, reason="Updated reasoning about retail growth", conditions=[
        {"text": "revenue keeps growing", "kind": "supports"}, {"text": "A new regulatory risk emerges", "kind": "invalidates"}])
    r = await client.put(f"/api/v4/theses/{t['chain_id']}", json={**body, "expected_version": 1})
    assert r.status_code == 200 and r.json()["version"] == 2
    ids = {c["text"].lower(): c["id"] for c in r.json()["conditions"]}
    assert ids["revenue keeps growing"] == "c1" and ids["a new regulatory risk emerges"] == "c3"  # same text keeps its id
    assert (await client.put(f"/api/v4/theses/{t['chain_id']}", json={**body, "expected_version": 1})).status_code == 409
    other = (await db_session.execute(select(Instrument).where(Instrument.symbol == "TCS"))).scalar_one()
    assert (await client.put(f"/api/v4/theses/{t['chain_id']}", json={**thesis_body(other), "expected_version": 2})).status_code == 422
    closed = await client.put(f"/api/v4/theses/{t['chain_id']}", json={**body, "expected_version": 2, "status": "closed"})
    assert closed.status_code == 200
    assert (await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")).status_code == 422


async def test_single_source_is_never_independent_corroboration(client, db_session, researcher):
    inst, t = await setup_thesis(client, db_session)
    # ONE document, TWO linked passages: two links, one lineage
    ids = await evidence(db_session, [("Revenue grew 12 percent in FY26", "supported",
                                       [("https://company.com/q4", "revenue up 12%"), ("https://company.com/q4-annex", "annex: revenue 12%")])])
    researcher.fact_ids = ids
    researcher.verdicts = [ConditionVerdict(condition_id="c1", verdict="supported", cited_fact_ids=ids, note="Revenue grew 12 percent")]
    a = (await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")).json()
    cond = next(c for c in a["per_condition"] if c["condition_id"] == "c1")
    ev = a["evidence"][ids[0]]
    assert len(ev["supporting"]) == 2 and ev["independent_sources"] == 1 and cond["independent_sources"] == 1
    assert a["status"] == "mixed" and "single source" in a["change_log"]
    assert a["review_status"] == "pending" and "never overrides" in a["portfolio_effect"]
    assert a["model_info"]["used"] is True and "score" not in str(a).lower().replace("never sets the status or writes a number", "")


async def test_two_independent_sources_can_support(client, db_session, researcher):
    inst, t = await setup_thesis(client, db_session)
    ids = await evidence(db_session, [("Revenue grew 12 percent in FY26", "supported", [("https://company.com/q4", "up 12%"), ("https://news.example/story", "up 12%")])])
    researcher.fact_ids = ids
    researcher.verdicts = [ConditionVerdict(condition_id="c1", verdict="supported", cited_fact_ids=ids)]
    a = (await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")).json()
    assert a["status"] == "supported" and a["per_condition"][0]["independent_sources"] == 2


async def test_invalidating_evidence_weakens_and_change_log_records_it(client, db_session, researcher):
    inst, t = await setup_thesis(client, db_session)
    good = await evidence(db_session, [("Revenue grew 12 percent in FY26", "supported", [("https://a.com/x", "t"), ("https://b.com/x", "t")])])
    researcher.fact_ids = good
    researcher.verdicts = [ConditionVerdict(condition_id="c1", verdict="supported", cited_fact_ids=good)]
    first = (await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")).json()
    bad = await evidence(db_session, [("The promoter sold 9 percent of the company", "supported", [("https://exchange.example/filing", "sold 9%")])])
    researcher.fact_ids = good + bad
    researcher.verdicts = [ConditionVerdict(condition_id="c1", verdict="supported", cited_fact_ids=good),
                           ConditionVerdict(condition_id="c2", verdict="supported", cited_fact_ids=bad, note="The promoter sold 9 percent")]
    second = (await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")).json()
    assert second["status"] == "weakened" and "changed from supported to weakened" in second["change_log"]
    assert "invalidating condition" in second["change_log"]
    hist = (await client.get(f"/api/v4/theses/{t['chain_id']}/assessments")).json()
    assert [h["assessment_id"] for h in hist] == [second["assessment_id"], first["assessment_id"]]
    # the owner's own thesis text is untouched by evidence
    th = (await client.get(f"/api/v4/theses/{t['chain_id']}")).json()
    assert th["reason"] == "Strong retail growth and stable margins" and th["version"] == 1 and th["latest_assessment"]["status"] == "weakened"


async def test_fabricated_citation_and_unverified_facts_cannot_support(client, db_session, researcher):
    inst, t = await setup_thesis(client, db_session)
    ids = await evidence(db_session, [("A rumour of record revenue", "unsupported", [("https://blog.example/post", "heard it")])])
    researcher.fact_ids = ids
    researcher.verdicts = [ConditionVerdict(condition_id="c1", verdict="supported", cited_fact_ids=ids + [str(uuid.uuid4())])]
    a = (await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")).json()
    assert a["status"] == "insufficient" and any("none passed verification" in g for g in a["gaps"])


async def test_missing_evidence_or_model_is_insufficient_with_named_gaps(client, db_session, researcher):
    inst, t = await setup_thesis(client, db_session)
    a = (await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")).json()
    assert a["status"] == "insufficient" and any("no evidence" in g for g in a["gaps"])
    ids = await evidence(db_session, [("Revenue grew 12 percent in FY26", "supported", [("https://a.com/x", "t"), ("https://b.com/x", "t")])])
    researcher.fact_ids, researcher.map_used = ids, False
    b = (await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")).json()
    assert b["status"] == "insufficient" and any("model unavailable" in g for g in b["gaps"]) and b["model_info"]["used"] is False
    ack = (await client.post(f"/api/v4/theses/{t['chain_id']}/assessments/{b['assessment_id']}/acknowledge")).json()
    assert ack["review_status"] == "acknowledged" and ack["acknowledged_at"]
    assert (await client.post(f"/api/v4/theses/{t['chain_id']}/assessments/{uuid.uuid4()}/acknowledge")).status_code == 404


async def test_research_verification_and_contradictions_survive_a_requery(client, db_session, researcher):
    inst, t = await setup_thesis(client, db_session)
    s = ResearchSession(user_id=SINGLE_USER_ID, question="q", instrument_ids=[str(inst.id)], mode="standard", cutoff_policy={}, state="ready_to_publish",
                        budget_envelope={}, budget_consumed={}, named_gaps=[], created_at=utcnow(), updated_at=utcnow())
    db_session.add(s)
    await db_session.commit()
    researcher.session_id = s.id
    researcher.contradictions = [{"between": ["f1", "f2"], "reason": "revenue figures differ"}]
    await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")
    r = (await client.get(f"/api/research/sessions/{s.id}")).json()
    assert r["verification"]["total_material_claims"] == 2 and r["verification"]["fully_verifiable"] is True
    assert r["contradictions"] == [{"between": ["f1", "f2"], "reason": "revenue figures differ"}]  # restored, not fabricated or lost
    a = (await client.get(f"/api/v4/theses/{t['chain_id']}/assessments")).json()[0]
    assert a["contradictions"] and a["verification"]["total_material_claims"] == 2


# --- price events ------------------------------------------------------------------------------------------

async def add_candles(db, inst, closes, source="yfinance"):
    start = datetime.now(timezone.utc) - timedelta(days=len(closes))
    for i, c in enumerate(closes):
        db.add(MarketCandle(instrument_id=inst.id, interval="1d", timestamp=start + timedelta(days=i), open=c, high=c, low=c, close=c, volume=1,
                            source=source, retrieved_at=utcnow(), adjusted=True))
    await db.commit()


async def test_price_move_is_an_event_and_never_changes_a_thesis(client, db_session, researcher):
    inst, t = await setup_thesis(client, db_session)
    ids = await evidence(db_session, [("Revenue grew 12 percent in FY26", "supported", [("https://a.com/x", "t"), ("https://b.com/x", "t")])])
    researcher.fact_ids = ids
    researcher.verdicts = [ConditionVerdict(condition_id="c1", verdict="supported", cited_fact_ids=ids)]
    before = (await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")).json()
    await add_candles(db_session, inst, [100.0] * 20 + [100, 101, 102, 90, 88, 85])  # about -15% in 5 sessions
    obs = (await client.post(f"/api/v4/theses/{t['chain_id']}/price-check")).json()
    assert obs["status"] == "threshold_crossed" and obs["event_recorded"] is True and obs["move_5_sessions"] < -0.08
    again = (await client.post(f"/api/v4/theses/{t['chain_id']}/price-check")).json()
    assert again["event_recorded"] is False  # same day: one event
    assert (await db_session.execute(select(func.count()).select_from(ThesisEvent))).scalar_one() == 1
    th = (await client.get(f"/api/v4/theses/{t['chain_id']}")).json()
    assert th["latest_assessment"]["assessment_id"] == before["assessment_id"] and th["latest_assessment"]["status"] == "supported"  # untouched by the price move
    assert th["events"][0]["kind"] == "price_move" and "never changes" in th["events"][0]["effect_on_thesis"]
    assert (await db_session.execute(select(func.count()).select_from(ThesisAssessment))).scalar_one() == 1


async def test_price_check_needs_real_history(client, db_session):
    inst, t = await setup_thesis(client, db_session)
    assert (await client.post(f"/api/v4/theses/{t['chain_id']}/price-check")).json()["status"] == "insufficient_history"
    await add_candles(db_session, inst, [100.0, 50.0, 40.0, 30.0, 20.0, 10.0, 5.0], source="demo_seed")  # demo data is ignored
    assert (await client.post(f"/api/v4/theses/{t['chain_id']}/price-check")).json()["status"] == "insufficient_history"
    assert (await client.post(f"/api/v4/theses/{uuid.uuid4()}/price-check")).status_code == 404


# --- review integration ----------------------------------------------------------------------------------------

async def test_thesis_update_is_information_only_and_cannot_change_the_decision(client, db_session, researcher, run_reviews):
    a, b = await complete_setup(client, db_session)
    inst = (await db_session.execute(select(Instrument).where(Instrument.symbol == "RELIANCE"))).scalar_one()
    t = (await client.post("/api/v4/theses", json=thesis_body(inst, ownership="owned"))).json()
    await run_reviews()
    base = (await current(client))["outcome"]
    assert base["status"] == "HOLD" and base["headline"] == "No action required today"
    ids = await evidence(db_session, [("The promoter sold 9 percent", "supported", [("https://exchange.example/f", "sold 9%")])])
    researcher.fact_ids = ids
    researcher.verdicts = [ConditionVerdict(condition_id="c2", verdict="supported", cited_fact_ids=ids)]
    wk = (await client.post(f"/api/v4/theses/{t['chain_id']}/refresh")).json()
    assert wk["status"] == "weakened"
    await client.post("/api/v4/reviews", json={"force": True})
    await run_reviews()
    out = (await current(client))["outcome"]
    issue = next(i for i in out["result"]["issues"] if i["kind"] == "thesis_update")
    assert issue["severity"] == "information" and "unchanged" in issue["detail"]
    # a weakened thesis does NOT turn HOLD into REVIEW or into a trade: only information items downgrade the wording
    assert out["status"] == "HOLD" and out["headline"] == "No issue found in the assessed holdings"
    await client.post(f"/api/v4/theses/{t['chain_id']}/assessments/{wk['assessment_id']}/acknowledge")
    await client.post("/api/v4/reviews", json={"force": True})
    await run_reviews()
    out2 = (await current(client))["outcome"]
    assert not any(i["kind"] == "thesis_update" for i in out2["result"]["issues"]) and out2["headline"] == "No action required today"

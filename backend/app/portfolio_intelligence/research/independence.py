"""Source provenance and independence (plan sections 5.4, 12.8).

A fact linked to passages is NOT thereby independently corroborated: several
passages from one document, or one outlet's pages, share one lineage. Counting
is by distinct LINEAGE, never by number of links. Lineage is the source host
(without `www.`); documents with identical content hashes are the same
lineage even across hosts (mirrors/syndication)."""

from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import Fact, FactPassageLink, Passage, SourceDocument


def host_of(url: str) -> str:
    h = (urlparse(url).hostname or url or "unknown").lower()
    return h[4:] if h.startswith("www.") else h


def assign_lineages(docs: list[dict]) -> dict[str, str]:
    """docs: {id, url, content_hash}. Returns doc id -> lineage key."""
    by_hash: dict[str, list[dict]] = {}
    for d in docs:
        by_hash.setdefault(d["content_hash"], []).append(d)
    out: dict[str, str] = {}
    for group in by_hash.values():
        key = min(host_of(d["url"]) for d in group)  # one lineage for identical content
        for d in group:
            out[d["id"]] = key if len(group) > 1 else host_of(d["url"])
    return out


async def fact_provenance(db: AsyncSession, fact_ids: list[str]) -> dict[str, dict]:
    """fact id -> {text, entity, period, support_status, supporting: [...], refuting: [...],
    independent_sources, lineages, earliest_publication, latest_retrieval}."""
    import uuid

    if not fact_ids:
        return {}
    ids = [uuid.UUID(str(f)) for f in fact_ids]
    facts = {str(f.id): f for f in (await db.execute(select(Fact).where(Fact.id.in_(ids)))).scalars()}
    rows = (await db.execute(
        select(FactPassageLink, Passage, SourceDocument)
        .join(Passage, Passage.id == FactPassageLink.passage_id)
        .join(SourceDocument, SourceDocument.id == Passage.document_id)
        .where(FactPassageLink.fact_id.in_(ids)))).all()
    docs = {str(d.id): {"id": str(d.id), "url": d.url, "content_hash": d.content_hash} for _, _, d in rows}
    lineage = assign_lineages(list(docs.values()))
    out: dict[str, dict] = {}
    for fid, f in facts.items():
        out[fid] = {"fact_id": fid, "text": f.text, "entity": f.entity, "period": f.period, "value": f.value, "units": f.units,
                    "support_status": f.support_status, "supporting": [], "refuting": []}
    times: dict[str, list] = {}
    for link, passage, doc in rows:
        fid = str(link.fact_id)
        entry = {"document_id": str(doc.id), "url": doc.url, "lineage": lineage[str(doc.id)], "passage_id": str(passage.id),
                 "location": passage.location, "publication_time": doc.publication_time.isoformat() if doc.publication_time else None,
                 "retrieval_time": doc.retrieval_time.isoformat()}
        out[fid]["supporting" if link.link_type == "supports" else "refuting"].append(entry)
        times.setdefault(fid, []).append(doc)
    for fid, e in out.items():
        e["lineages"] = sorted({x["lineage"] for x in e["supporting"]})
        e["independent_sources"] = len(e["lineages"])  # distinct lineages, NOT number of links
        pubs = sorted(x["publication_time"] for x in e["supporting"] if x["publication_time"])
        rets = sorted(x["retrieval_time"] for x in e["supporting"])
        e["earliest_publication"] = pubs[0] if pubs else None
        e["latest_retrieval"] = rets[-1] if rets else None
    return out

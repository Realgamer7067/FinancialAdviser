"""Fetch AMFI expense ratios in time-boxed chunks, store them raw, then match defensibly. A full pass is about 300 polite requests (several
minutes), longer than one job lease, so a chunk handles AMCs until its time budget is spent and the job queues its own follow-up."""

import logging
import time
from datetime import datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import SchemeTer, Security, SecurityTer
from app.portfolio_intelligence.costs import ter_match as M
from app.portfolio_intelligence.costs import ter_source as T
from app.portfolio_intelligence.sources.angel.token_store import IST
from app.utils.time import utcnow

logger = logging.getLogger("ter_sync")
BUDGET_SECONDS = 150.0


async def upsert_rows(db: AsyncSession, rows: list[dict], amc_name: str, now: datetime) -> int:
    existing = {r.nsdl_code: r for r in (await db.execute(select(SchemeTer).where(SchemeTer.nsdl_code.in_([x["nsdl_code"] for x in rows] or [""])))).scalars()}
    for x in rows:
        r = existing.get(x["nsdl_code"])
        if r is None:
            r = SchemeTer(nsdl_code=x["nsdl_code"])
            db.add(r)
        r.mf_id, r.amc_name, r.scheme_name, r.category, r.ter_date = x["mf_id"], amc_name, x["scheme_name"], x["category"], x["ter_date"]
        r.regular_ter, r.direct_ter, r.regular_ber, r.direct_ber, r.fetched_at = x["regular_ter"], x["direct_ter"], x["regular_ber"], x["direct_ber"], now
    await db.commit()
    return len(rows)


async def fetch_chunk(db: AsyncSession, amcs: list[dict], *, today, client: httpx.AsyncClient | None = None, budget: float = BUDGET_SECONDS, sleep=None, clock=time.monotonic) -> dict:
    """Process AMCs in order until the budget is spent. -> {done: [mf_id], failed: {mf_id: reason}, remaining: [amc dicts]}. A failed AMC is reported and
    skipped (a later run retries it); it never aborts the others."""
    own = client is None
    client = client or T.client()
    kw = {"sleep": sleep} if sleep else {}
    start, done, failed, stored = clock(), [], {}, 0
    remaining = list(amcs)
    try:
        while remaining and clock() - start < budget:
            amc = remaining.pop(0)
            try:
                rows = await T.fetch_amc_month(client, amc["mf_id"], T.current_month(today), **kw)
                if not rows:   # the month has not started publishing for this AMC yet
                    rows = await T.fetch_amc_month(client, amc["mf_id"], T.previous_month(today), **kw)
                stored += await upsert_rows(db, T.latest_per_scheme(rows, amc["mf_id"]), amc["name"], utcnow())
                done.append(amc["mf_id"])
            except T.TerError as exc:
                failed[amc["mf_id"]] = str(exc)[:120]
    finally:
        if own:
            await client.aclose()
    return {"done": done, "failed": failed, "remaining": remaining, "schemes_stored": stored}


async def match_all(db: AsyncSession, now: datetime | None = None) -> dict:
    """Rebuild `security_ter` from the stored raw TER rows. Replaces the previous matches wholesale, so a corrected rule leaves no stale rows."""
    now = now or utcnow()
    ter_rows = [{"mf_id": r.mf_id, "nsdl_code": r.nsdl_code, "scheme_name": r.scheme_name, "category": r.category, "ter_date": r.ter_date,
                 "regular_ter": None if r.regular_ter is None else float(r.regular_ter), "direct_ter": None if r.direct_ter is None else float(r.direct_ter)}
                for r in (await db.execute(select(SchemeTer))).scalars()]
    amcs = {r.mf_id: r.amc_name for r in (await db.execute(select(SchemeTer))).scalars()}
    index, istats = M.build_index(ter_rows, amcs)
    funds = (await db.execute(select(Security).where(Security.kind.in_(("mutual_fund", "etf")), Security.is_active.is_(True)))).scalars().all()
    nav_by_isin = {}
    for f in funds:
        if f.kind == "mutual_fund":
            for key in (f.isin, f.isin_reinvest):
                if key:
                    nav_by_isin.setdefault(key.upper(), {"name": f.name, "amc": f.amc})
    await db.execute(delete(SecurityTer))
    counts = {"mutual_fund": [0, 0], "etf": [0, 0]}
    for f in funds:
        counts[f.kind][1] += 1
        m = M.match_security({"kind": f.kind, "name": f.name, "amc": f.amc, "plan": f.plan, "isin": f.isin}, index, nav_row_by_isin=nav_by_isin)
        if m is None:
            continue
        counts[f.kind][0] += 1
        row = m["ter_row"]
        db.add(SecurityTer(security_id=f.id, nsdl_code=row["nsdl_code"], scheme_name=row["scheme_name"], ter=m["ter"], plan_used=m["plan_used"], matched_via=m["matched_via"], ter_date=row["ter_date"], matched_at=now))
    await db.commit()
    return {**istats, "mutual_funds_matched": counts["mutual_fund"][0], "mutual_funds_total": counts["mutual_fund"][1], "etfs_matched": counts["etf"][0], "etfs_total": counts["etf"][1]}

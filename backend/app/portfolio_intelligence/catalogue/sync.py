"""Catalogue sync: fetch (or accept) the public files, upsert `securities`, link to the legacy Nifty-50
`instruments` and to Angel `broker_instruments`, and store NSE corporate actions.

Every function takes already-parsed data or an AsyncSession, so the whole path is testable on fixtures.
Linking rules (never fuzzy):
- security -> instrument: same validated ISIN, else nothing (symbol alone never proves identity).
- broker instrument -> security: same NSE symbol on the EQ series, and the security's series is EQ.
  Angel's master carries no ISIN, so symbol+series is the only available key; it is recorded as
  `symbol_series_match` and a symbol that maps to two securities is left unlinked."""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import Instrument
from app.models.securities import CorporateAction, Security
from app.models.watchlist import BrokerInstrument
from app.portfolio_intelligence.catalogue import corporate_actions as ca
from app.portfolio_intelligence.catalogue import parse
from app.portfolio_intelligence.catalogue import sources
from app.portfolio_intelligence.sources.angel.token_store import IST
from app.utils.time import utcnow

logger = logging.getLogger("catalogue")
_FIELDS = ("kind", "isin", "isin_reinvest", "symbol", "name", "exchange", "series", "lot_size", "face_value", "listing_date", "sector",
           "asset_class", "category", "scheme_code", "amc", "plan", "option", "nav", "nav_date", "is_active", "source")


def _key(row: dict) -> str:
    return f"amfi:{row['scheme_code']}" if row["kind"] == "mutual_fund" else f"isin:{row['isin']}"


async def upsert_securities(db: AsyncSession, rows: list[dict], now: datetime | None = None) -> dict:
    """Insert/refresh by source_key. Fields absent from a row are left as they were (a sector learned from
    another file must not be wiped by a refresh of the equity list)."""
    now = now or utcnow()
    existing = {s.source_key: s for s in (await db.execute(select(Security))).scalars()}
    added = updated = 0
    for r in rows:
        key = _key(r)
        s = existing.get(key)
        if s is None:
            s = Security(source_key=key, kind=r["kind"], name=r["name"], source=r["source"], is_active=True, seen_at=now)
            db.add(s)
            existing[key] = s
            added += 1
        else:
            updated += 1
        for f in _FIELDS:
            if f in r and r[f] is not None:
                setattr(s, f, r[f])
        s.seen_at = now
    await db.flush()
    return {"added": added, "updated": updated}


async def apply_sectors(db: AsyncSession, sector_by_isin: dict[str, str]) -> int:
    n = 0
    for s in (await db.execute(select(Security).where(Security.kind == "stock", Security.isin.in_(list(sector_by_isin))))).scalars():
        if s.sector != sector_by_isin[s.isin]:
            s.sector = sector_by_isin[s.isin]
        n += 1
    return n


MIN_COMPLETE_FRACTION = 0.9  # a file shorter than this share of the currently active rows is treated as truncated


async def retire_missing(db: AsyncSession, source: str, kind: str, seen_keys: set[str], now: datetime) -> dict:
    """Rows from a source that did not appear in its latest file become inactive (delisted/merged). A file
    with fewer than 90% of the currently active rows is treated as truncated or partial (e.g. a maintenance
    list): nothing is retired and the report says why. Rows that reappear are reactivated by the upsert."""
    active = [s for s in (await db.execute(select(Security).where(Security.source == source, Security.kind == kind, Security.is_active.is_(True)))).scalars()]
    if active and len(seen_keys) < MIN_COMPLETE_FRACTION * len(active):
        return {"retired": 0, "skipped": f"file has {len(seen_keys)} rows vs {len(active)} active; looks truncated, nothing retired"}
    n = 0
    for s in active:
        if s.source_key not in seen_keys:
            s.is_active = False
            n += 1
    return {"retired": n}


async def link_instruments(db: AsyncSession) -> int:
    by_isin = {i.isin: i.id for i in (await db.execute(select(Instrument).where(Instrument.isin.is_not(None)))).scalars()}
    n = 0
    for s in (await db.execute(select(Security).where(Security.kind == "stock", Security.isin.in_(list(by_isin) or [""])))).scalars():
        if s.instrument_id != by_isin[s.isin]:
            s.instrument_id = by_isin[s.isin]
        n += 1
    return n


async def link_broker_instruments(db: AsyncSession) -> dict:
    by_symbol: dict[str, list[Security]] = {}
    for s in (await db.execute(select(Security).where(Security.kind.in_(("stock", "etf")), Security.series == "EQ", Security.is_active.is_(True)))).scalars():
        by_symbol.setdefault(s.symbol or "", []).append(s)
    linked = ambiguous = 0
    for b in (await db.execute(select(BrokerInstrument).where(BrokerInstrument.series == "EQ"))).scalars():
        cands = by_symbol.get(b.symbol, [])
        if len(cands) == 1:
            if b.security_id != cands[0].id:
                b.security_id = cands[0].id
            linked += 1
        elif len(cands) > 1:
            ambiguous += 1
            b.security_id = None
    return {"linked": linked, "ambiguous": ambiguous}


async def sync_catalogue(db: AsyncSession, texts: dict[str, str], now: datetime | None = None) -> dict:
    """texts: {equity_l, etf_list, sector_map, amfi} file contents. A source missing from `texts` is skipped
    (its rows stay as they were); a source present is applied whole. One transaction."""
    now = now or utcnow()
    report: dict = {}
    if "equity_l" in texts:
        rows, bad = parse.parse_equity_l(texts["equity_l"])
        if not rows:
            raise ValueError("EQUITY_L parsed to zero rows; refusing to apply")
        report["stocks"] = {**await upsert_securities(db, rows, now), "skipped_rows": bad}
        report["stocks"].update(await retire_missing(db, "nse_equity_l", "stock", {_key(r) for r in rows}, now))
    if "etf_list" in texts:
        rows, bad = parse.parse_etf_list(texts["etf_list"])
        if not rows:
            raise ValueError("ETF list parsed to zero rows; refusing to apply")
        report["etfs"] = {**await upsert_securities(db, rows, now), "skipped_rows": bad}
        report["etfs"].update(await retire_missing(db, "nse_etf_list", "etf", {_key(r) for r in rows}, now))
    if "sector_map" in texts:
        report["sectors_applied"] = await apply_sectors(db, parse.parse_sector_map(texts["sector_map"]))
    if "amfi" in texts:
        rows, bad, newest = parse.parse_amfi_navall(texts["amfi"])
        if not rows:
            raise ValueError("AMFI file parsed to zero schemes; refusing to apply")
        parse.mark_stale_funds(rows, newest)
        report["funds"] = {**await upsert_securities(db, rows, now), "skipped_rows": bad, "newest_nav": newest.isoformat() if newest else None,
                           **await retire_missing(db, "amfi_navall", "mutual_fund", {_key(r) for r in rows}, now)}
    report["linked_instruments"] = await link_instruments(db)
    report["linked_broker"] = await link_broker_instruments(db)
    await db.commit()
    return report


async def store_actions(db: AsyncSession, events: list[dict], now: datetime | None = None) -> dict:
    now = now or utcnow()
    existing = {(a.symbol, a.ex_date, a.subject): a for a in (await db.execute(select(CorporateAction))).scalars()}
    added = updated = 0
    for e in events:
        k = (e["symbol"], e["ex_date"], e["subject"])
        row = existing.get(k)
        if row is None:
            row = CorporateAction(symbol=e["symbol"], ex_date=e["ex_date"], subject=e["subject"], source="nse", fetched_at=now)
            db.add(row)
            existing[k] = row
            added += 1
        else:
            updated += 1
        for f in ("isin", "kind", "ratio_num", "ratio_den", "amount", "price_factor", "needs_review"):
            setattr(row, f, e[f])
        row.fetched_at = now
    await db.commit()
    return {"added": added, "updated": updated}


async def reparse_actions(db: AsyncSession) -> int:
    """Re-derive kind/ratio/amount/factor for every stored event from its raw subject, so an improved parser
    corrects history already stored (the raw subject is the source of truth; derived columns are a cache)."""
    changed = 0
    for row in (await db.execute(select(CorporateAction))).scalars():
        new = ca.parse_subject(row.subject)
        if any(getattr(row, k) != new[k] for k in new):
            for k, v in new.items():
                setattr(row, k, v)
            changed += 1
    await db.commit()
    return changed


async def latest_action_date(db: AsyncSession, upto: date) -> date | None:
    """Newest stored ex-date not after `upto`: the resume point (events dated in the future do not count as progress)."""
    from sqlalchemy import func

    return (await db.execute(select(func.max(CorporateAction.ex_date)).where(CorporateAction.ex_date <= upto))).scalar_one_or_none()


WINDOW_RETRY_DELAYS = (3.0, 10.0, 30.0)  # NSE drops connections from clients it finds too eager; wait, then try again


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


async def sync_actions(db: AsyncSession, start: date, end: date, fetch=sources.fetch_actions, pause=sources.polite_sleep,
                       now: datetime | None = None, retry_delays: tuple = WINDOW_RETRY_DELAYS, sleep=_sleep) -> dict:
    """Fetch quarter windows [start, end], storing each as it arrives (a failure keeps earlier windows). A window
    is retried with backoff before giving up; the first window that still fails stops the run and is reported
    (the next run resumes from the last stored date, so nothing is skipped silently)."""
    now = now or utcnow()
    windows, stored, failed = 0, 0, None
    for a, b in sources.date_chunks(start, end):
        records, error = None, None
        for attempt in range(len(retry_delays) + 1):
            try:
                records = await fetch(a, b)
                break
            except sources.SourceError as exc:
                error = str(exc)
                if attempt < len(retry_delays):
                    await sleep(retry_delays[attempt])
        if records is None:
            failed = {"window": [a.isoformat(), b.isoformat()], "error": error}
            break
        res = await store_actions(db, ca.normalize_records(records), now)
        stored += res["added"] + res["updated"]
        windows += 1
        await pause()
    return {"windows_done": windows, "events_stored": stored, "failed": failed}


async def refresh_catalogue(db: AsyncSession, now: datetime | None = None) -> dict:
    """The nightly entry point: download every source, apply what arrived, then top up corporate
    actions from the last stored ex-date (minus a 7 day overlap for late-published events). One source failing
    does not block the others."""
    now = now or utcnow()
    texts, errors = {}, {}
    # One at a time: from the Docker network, parallel first connections to different hosts intermittently
    # failed (DNS / "all connection attempts failed") while the same downloads succeeded serially. This is a
    # nightly job, so a minute of extra time costs nothing.
    for n in ("equity_l", "etf_list", "sector_map", "amfi"):
        try:
            texts[n] = await sources.fetch_text(n)
        except sources.SourceError as exc:
            errors[n] = str(exc)
        except Exception as exc:  # noqa: BLE001 -- one odd failure must not stop the other sources
            errors[n] = type(exc).__name__
    report: dict = {"fetch_errors": errors}
    if texts:
        try:
            report["catalogue"] = await sync_catalogue(db, texts, now)
        except Exception as exc:  # noqa: BLE001 -- a refused/odd file must not stop the actions top-up
            await db.rollback()
            report["catalogue_error"] = str(exc)[:200]
            logger.exception("catalogue sync failed")
    today = now.astimezone(IST).date()
    last = await latest_action_date(db, today)
    start = (last - timedelta(days=7)) if last else (today - timedelta(days=5 * 366))
    report["actions"] = await sync_actions(db, start, today, now=now)
    report["actions"]["reparsed"] = await reparse_actions(db)
    try:   # the exchange calendar rides along with the nightly refresh; its failure never fails the catalogue
        from app.portfolio_intelligence.market import holidays as hol

        report["holidays"] = await hol.refresh_holidays(db)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        report["holidays"] = {"error": str(exc)[:120]}
    return report

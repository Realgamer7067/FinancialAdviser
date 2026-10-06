"""Identity from the market catalogue. The old Nifty 50 `instruments` table is only one source of identity: an ISIN that names exactly
one active security in the market catalogue (stock, ETF or fund) is a real, priceable security even when that table does not list it.

This is read at display/coverage time, never written into the stored observation, so older imports benefit too and the stored
`resolution` stays exactly what the import decided. Sector-level analysis still needs the instrument master (see risk/exposure.py)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import Security

UNRESOLVED = ("unresolved", "ambiguous")


TRADED = ("stock", "etf")


async def catalogue_securities(db: AsyncSession, isins: set[str]) -> dict[str, Security]:
    """isin -> the one security it names. An ETF appears twice (its NSE listing and AMFI's fund row for the same ISIN): that is
    one thing, so the single traded listing wins. Two traded listings, or two fund rows, are a real ambiguity and give nothing."""
    isins = {i for i in isins if i}
    if not isins:
        return {}
    groups: dict[str, list[Security]] = {}
    for sec in (await db.execute(select(Security).where(Security.isin.in_(isins), Security.is_active.is_(True)))).scalars():
        groups.setdefault(sec.isin, []).append(sec)
    out: dict[str, Security] = {}
    for isin, secs in groups.items():
        traded = [x for x in secs if x.kind in TRADED]
        pick = traded if traded else secs
        if len(pick) == 1:
            out[isin] = pick[0]
    return out


async def unique_catalogue_isins(db: AsyncSession, isins: set[str]) -> dict[str, str]:
    """isin -> security id (see catalogue_securities for the rule)."""
    return {i: str(sec.id) for i, sec in (await catalogue_securities(db, isins)).items()}


def effective_identity(resolution: str, isin: str | None, catalogue: dict[str, str]) -> str:
    """'catalogue' when the import could not match the holding to the Nifty 50 table but its ISIN is a known security."""
    return "catalogue" if resolution in UNRESOLVED and isin and isin in catalogue else resolution

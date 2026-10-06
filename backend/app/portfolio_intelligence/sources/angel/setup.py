"""Operator-only Angel session setup. Run in YOUR terminal, never through the
web app or a chat:

    python -m app.portfolio_intelligence.sources.angel.setup connect
    python -m app.portfolio_intelligence.sources.angel.setup status
    python -m app.portfolio_intelligence.sources.angel.setup shape   # redacted payload shape only
    python -m app.portfolio_intelligence.sources.angel.setup disconnect

Client code / PIN / TOTP are read interactively (PIN and TOTP without echo),
so they never appear in process arguments or shell history. Only the session
tokens are stored (0600, outside the repo), never the PIN, TOTP or its seed.
Output shows only a masked client code."""

import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import SourceAccount
from app.portfolio_intelligence.sources.angel.client import AngelClient
from app.portfolio_intelligence.sources.angel.errors import AngelError
from app.portfolio_intelligence.sources.angel.identity import fingerprint, mask
from app.portfolio_intelligence.sources.angel.token_store import clear_session, load_session, save_session, session_dir
from app.utils.time import utcnow


async def _ensure_account(client_code: str) -> SourceAccount:
    fp = fingerprint(client_code)
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(SourceAccount).where(
                    SourceAccount.user_id == SINGLE_USER_ID,
                    SourceAccount.source_type == "angel_one",
                    SourceAccount.external_fingerprint == fp,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.status = "active"
            existing.last_error = None
            await db.commit()
            return existing
        base = f"Angel One ({mask(client_code)})"
        label, n = base, 1
        taken = set((await db.execute(select(SourceAccount.label).where(SourceAccount.user_id == SINGLE_USER_ID))).scalars())
        while label in taken:
            n += 1
            label = f"{base} #{n}"
        account = SourceAccount(
            user_id=SINGLE_USER_ID, source_type="angel_one", label=label,
            masked_external_id=mask(client_code), external_fingerprint=fp,
            included=True, status="active", version=1, created_at=utcnow(),
        )
        db.add(account)
        await db.commit()
        return account


async def connect() -> int:
    missing = [n for n, v in (("ANGEL_API_KEY", settings.angel_api_key), ("ANGEL_FINGERPRINT_KEY", settings.angel_fingerprint_key)) if not v]
    if missing:
        print(f"Set {', '.join(missing)} in .env first. Generate the fingerprint key with: openssl rand -hex 32")
        print("Back it up: losing it makes this account look new and would duplicate positions.")
        return 2
    client_code = input("Angel client code: ").strip()
    pin = getpass.getpass("PIN (hidden): ")
    totp = getpass.getpass("Current TOTP (hidden): ").strip()
    client = AngelClient()
    try:
        tokens = await client.login(client_code, pin, totp)
        sess = save_session(**tokens)
        profile = await client.get_profile()
        if str(profile["clientcode"]).strip().upper() != client_code.strip().upper():
            clear_session()
            print("IDENTITY_CONFLICT: session client code differs from the one entered; session discarded.")
            return 1
        account = await _ensure_account(client_code)
    except AngelError as exc:
        clear_session()
        print(f"Connection failed: {exc.code}: {exc}")
        return 1
    finally:
        pin = totp = ""  # noqa: F841 -- drop references early
        await client.aclose()
    print(f"Connected as {mask(client_code)}; account '{account.label}'. Session valid until {sess.expires_at.isoformat()}.")
    print(f"Session file: {session_dir()} (0600). Use the Holdings page to sync.")
    return 0


def _shape(v):
    """Type-only description; never values."""
    if isinstance(v, dict):
        return {k: _shape(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_shape(v[0])] if v else []
    return type(v).__name__


async def shape() -> int:
    """Capture the redacted SHAPE of each read endpoint: key names, types and
    boolean facts about holdings rows. No numbers, symbols or client code."""
    from decimal import Decimal, InvalidOperation

    from app.portfolio_intelligence.sources.angel.token_store import load_session

    sess = load_session()
    if sess is None:
        print("no valid session; run connect first")
        return 1

    def num(x):
        try:
            return Decimal(str(x))
        except (InvalidOperation, ValueError):
            return None

    client = AngelClient(jwt=sess.jwt)
    out: dict = {}
    try:
        for name, call in (("profile", client.get_profile), ("holdings", client.get_all_holding),
                           ("positions", client.get_positions), ("rms", client.get_rms)):
            try:
                out[name] = {"shape": _shape(await call())}
            except AngelError as exc:
                out[name] = {"error": exc.code}
        h = None
        try:
            h = await client.get_all_holding()
        except AngelError:
            pass
        if isinstance(h, dict) and isinstance(h.get("holdings"), list):
            rows = [r for r in h["holdings"] if isinstance(r, dict)]
            facts = {"row_count": len(rows), "totalholding_present": isinstance(h.get("totalholding"), dict)}
            checks = {
                "rows_with_t1quantity_gt_0": lambda r: (num(r.get("t1quantity")) or 0) > 0,
                "rows_with_quantity_eq_0": lambda r: num(r.get("quantity")) == 0,
                "rows_quantity_eq_realised_plus_t1": lambda r: num(r.get("quantity")) is not None and num(r.get("quantity")) == (num(r.get("realisedquantity")) or 0) + (num(r.get("t1quantity")) or 0),
                "rows_quantity_eq_realised": lambda r: num(r.get("quantity")) is not None and num(r.get("quantity")) == num(r.get("realisedquantity")),
                "rows_missing_isin": lambda r: not r.get("isin"),
                "rows_missing_ltp": lambda r: r.get("ltp") in (None, ""),
                "rows_with_collateral_gt_0": lambda r: (num(r.get("collateralquantity")) or 0) > 0,
            }
            for label, fn in checks.items():
                facts[label] = sum(1 for r in rows if fn(r))
            facts["products"] = sorted({str(r.get("product")) for r in rows})
            facts["exchanges"] = sorted({str(r.get("exchange")) for r in rows})
            out["holdings_facts"] = facts
    finally:
        await client.aclose()
    import json
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def status() -> int:
    sess = load_session()
    print("no valid session" if sess is None else f"session valid until {sess.expires_at.isoformat()}")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "connect":
        return asyncio.run(connect())
    if cmd == "shape":
        return asyncio.run(shape())
    if cmd == "disconnect":
        clear_session()
        print("session cleared; imported holdings are kept")
        return 0
    if cmd == "status":
        return status()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

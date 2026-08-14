"""Reads/writes the Upstox access-token state stored in `data_sources`
(Section 65/69). Centralized so the pipeline and the admin OAuth callback
agree on where the token lives."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import DataSource

SOURCE_NAME = "upstox"


async def get_upstox_token_state(db: AsyncSession) -> tuple[str | None, datetime | None]:
    row = (await db.execute(select(DataSource).where(DataSource.name == SOURCE_NAME))).scalar_one_or_none()
    if row is None or not row.meta.get("access_token"):
        return None, None
    return row.meta["access_token"], row.token_expires_at


async def store_upstox_token(db: AsyncSession, access_token: str, expires_at: datetime) -> None:
    row = (await db.execute(select(DataSource).where(DataSource.name == SOURCE_NAME))).scalar_one_or_none()
    if row is None:
        row = DataSource(name=SOURCE_NAME, kind="market")
        db.add(row)
    row.status = "ok"
    row.last_synced_at = datetime.now(timezone.utc)
    row.token_expires_at = expires_at
    row.meta = {"access_token": access_token}
    await db.flush()

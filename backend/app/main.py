from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, dashboard, education, jobs, onboarding, planning, portfolio, recommendations, stocks
from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.single_user import SINGLE_USER_ID
from app.models.user import User

app = FastAPI(title="Indian AI Equity Research Platform", version="0.1.0")


@app.on_event("startup")
async def seed_single_user() -> None:
    """No login in this build -- every request acts as this one fixed-UUID
    row (app.core.single_user.SINGLE_USER_ID), created idempotently on boot
    since several tables carry a NOT NULL FK to it."""
    async with AsyncSessionLocal() as db:
        existing = await db.get(User, SINGLE_USER_ID)
        if existing is None:
            db.add(
                User(
                    id=SINGLE_USER_ID,
                    email="user@local",
                    full_name="User",
                    hashed_password="unused-single-user-mode",
                )
            )
            await db.commit()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    # Codespaces (and similar cloud dev environments) serve the frontend from
    # a forwarded https://<name>-3000.app.github.dev origin, not localhost --
    # without this, every request gets silently CORS-blocked in the browser.
    allow_origin_regex=r"https://.*\.github\.dev",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(onboarding.router)
app.include_router(jobs.router)
app.include_router(recommendations.router)
app.include_router(stocks.router)
app.include_router(portfolio.router)
app.include_router(planning.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(education.router)


@app.get("/health")
async def health():
    return {"status": "ok", "demo_mode": settings.demo_mode}

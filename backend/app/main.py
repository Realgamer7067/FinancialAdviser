from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin,
    catalogue,
    dashboard,
    education,
    financial_inputs,
    jobs,
    onboarding,
    planning,
    plans,
    portfolio,
    recommendations,
    research,
    stocks,
)
from app.api.v4 import ledger as v4_ledger, suggestions as v4_suggestions, allocation as v4_allocation, catalogue as v4_catalogue, accounts as v4_accounts, watchlist as v4_watchlist, theses as v4_theses, inbox as v4_inbox, decisions as v4_decisions, actions as v4_actions, risk as v4_risk, constraints as v4_constraints, goals as v4_goals, connections as v4_connections, imports as v4_imports, personal as v4_personal, state as v4_state
from app.api.v4 import freshness as v4_freshness
from app.core.config import settings
from app.core.db import AsyncSessionLocal, engine
from app.core.migration_barrier import assert_migration_head
from app.core.single_user import SINGLE_USER_ID
from app.models.user import User

app = FastAPI(title="Indian AI Equity Research Platform", version="0.1.0")


@app.on_event("startup")
async def check_migration_head() -> None:
    """Migration startup barrier (V3 Phase 11, instruction 2) -- refuse to
    serve requests against a database whose applied Alembic revision doesn't
    match what this code expects. Runs first, before anything else touches
    the database."""
    async with engine.connect() as conn:
        await assert_migration_head(conn)


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

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ALLOWED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Codespaces (and similar cloud dev environments) serve the frontend from
    # a forwarded https://<name>-3000.app.github.dev origin, not localhost --
    # without this, every request gets silently CORS-blocked in the browser.
    # Off by default: private mode (real holdings/broker data) must not trust
    # forwarded origins. Opt in with ALLOW_FORWARDED_ORIGINS=true.
    allow_origin_regex=r"https://.*\.github\.dev" if settings.allow_forwarded_origins else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    """CORS does not stop a cross-site page from *sending* a state-changing
    request, only from reading the reply. For /api/v4 (holdings, broker
    connection) refuse browser-marked cross-site writes outright. Non-browser
    clients send neither header and are unaffected."""
    if request.method not in _SAFE_METHODS and request.url.path.startswith("/api/v4"):
        fetch_site = request.headers.get("sec-fetch-site")
        origin = request.headers.get("origin")
        if fetch_site is not None and fetch_site not in ("same-origin", "none"):
            return JSONResponse({"detail": "cross-site request rejected"}, status_code=403)
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return JSONResponse({"detail": "origin not allowed"}, status_code=403)
    return await call_next(request)

app.include_router(onboarding.router)
app.include_router(jobs.router)
app.include_router(recommendations.router)
app.include_router(stocks.router)
app.include_router(portfolio.router)
app.include_router(planning.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(education.router)
app.include_router(financial_inputs.router)
app.include_router(catalogue.router)
app.include_router(research.router)
app.include_router(plans.router)
app.include_router(v4_accounts.router)
app.include_router(v4_imports.router)
app.include_router(v4_connections.router)
app.include_router(v4_state.router)
app.include_router(v4_personal.router)
app.include_router(v4_goals.router)
app.include_router(v4_risk.router)
app.include_router(v4_actions.router)
app.include_router(v4_decisions.router)
app.include_router(v4_inbox.router)
app.include_router(v4_theses.router)
app.include_router(v4_watchlist.router)
app.include_router(v4_catalogue.router)
app.include_router(v4_allocation.router)
app.include_router(v4_suggestions.router)
app.include_router(v4_ledger.router)
app.include_router(v4_freshness.router)
app.include_router(v4_constraints.router)


@app.get("/health")
async def health():
    return {"status": "ok", "demo_mode": settings.demo_mode}


@app.on_event("startup")
async def start_background_scheduler() -> None:
    """Weekday market-close pass + due-retry drain (see app/portfolio_intelligence/scheduler.py).
    Registered last so it only starts after the migration barrier and user seeding succeeded."""
    from app.core.db import AsyncSessionLocal
    from app.portfolio_intelligence.market import holidays as hol
    from app.portfolio_intelligence.scheduler import start_scheduler

    try:
        async with AsyncSessionLocal() as db:
            await hol.load_calendar(db)      # the stored exchange holidays; weekdays only if none are stored yet
    except Exception:  # noqa: BLE001 -- the calendar is an improvement, never a reason not to start
        pass
    start_scheduler()

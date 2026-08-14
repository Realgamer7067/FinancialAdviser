from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, dashboard, jobs, onboarding, portfolio, recommendations, stocks
from app.core.config import settings

app = FastAPI(title="Indian AI Equity Research Platform", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(onboarding.router)
app.include_router(jobs.router)
app.include_router(recommendations.router)
app.include_router(stocks.router)
app.include_router(portfolio.router)
app.include_router(dashboard.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok", "demo_mode": settings.demo_mode}

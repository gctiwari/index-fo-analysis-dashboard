from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from app.api.routes import router
from app.api.tracking_routes import router as tracking_router
from app.db import init_db
from app.scheduler import start_scheduler, stop_scheduler
from app.json_safety import SafeJSONResponse

app = FastAPI(
    title="Indian Index F&O Analysis API",
    description="Pre-market / post-market technical + confluence analysis for Indian index derivatives. "
                 "Analysis and research tooling only -- not an automated trading system.",
    version="0.1.0",
    default_response_class=SafeJSONResponse,
)

# CORS_ORIGINS is a comma-separated list of allowed frontend origins, e.g.
#   CORS_ORIGINS=http://localhost:3000,https://your-app.vercel.app
# Defaults to localhost only, for local development.
_origins_env = os.environ.get("CORS_ORIGINS", "http://localhost:3000")
allow_origins = [o.strip() for o in _origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(tracking_router, prefix="/api")


@app.on_event("startup")
def _on_startup():
    init_db()
    start_scheduler()


@app.on_event("shutdown")
def _on_shutdown():
    # Item 4 of the follow-up audit: verify scheduler shutdown behavior. Without this, the
    # APScheduler background thread has no clean stop signal on app shutdown (uvicorn --reload
    # in particular can otherwise accumulate orphaned scheduler instances across reloads).
    stop_scheduler()


@app.get("/")
def root():
    return {"status": "ok", "service": "index-fo-analysis-api"}


@app.get("/health")
def health():
    return {"status": "healthy"}

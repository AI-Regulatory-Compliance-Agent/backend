"""
FastAPI Application Entry Point — AI Regulatory Compliance Agent.

This file:
  1. Creates the FastAPI app instance
  2. Configures CORS for the React frontend (localhost:5173)
  3. Creates all database tables on startup
  4. Registers all API routers

Routers registered:
  /auth              → login, register (JWT auth)
  /analyze           → start analysis, get results
  /analysis/stream   → SSE progress streaming
  /history           → past analyses, re-analysis support
  /reports           → PDF download

The app is served by Uvicorn on port 8000 inside Docker.
The frontend at localhost:5173 communicates with this backend.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.config import get_settings

# ── Import All Routers ──────────────────────────────────────
from app.routers import auth
from app.routers import analysis
from app.routers import sse
from app.routers import history
from app.routers import reports
from app.routers import upload

settings = get_settings()

# ── Create Database Tables ──────────────────────────────────
# Creates all tables defined in app/models/ if they don't exist.
# Uses the Base.metadata from database.py which collects all
# models imported via app/models/__init__.py
Base.metadata.create_all(bind=engine)

# ── Create FastAPI App ──────────────────────────────────────
app = FastAPI(
    title="AI Regulatory Compliance Agent",
    description="AI-powered regulatory compliance gap analysis tool. "
                "Analyses company profiles against stored government "
                "regulations to identify compliance gaps, risk levels, "
                "and remediation steps.",
    version="1.0.0"
)

# ── CORS Configuration ──────────────────────────────────────
# Allows the React frontend (Vite on port 5173) to make
# cross-origin requests to this backend (port 8000).
# In production, restrict allow_origins to your actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://127.0.0.1:5173", # Alternative localhost
    ],
    allow_credentials=True,  # Required for cookies/auth headers
    allow_methods=["*"],     # Allow all HTTP methods
    allow_headers=["*"],     # Allow all headers (including Authorization)
)

# ── Register Routers ────────────────────────────────────────
# Each router handles a specific domain of the API.
# Prefixes are set inside each router file.

app.include_router(auth.router)       # /auth/register, /auth/login
app.include_router(analysis.router)   # /analyze, /analyze/result/{id}
app.include_router(upload.router)     # /analyze/upload (document uploads)
app.include_router(sse.router)        # /analysis/stream/{session_id}
app.include_router(history.router)    # /history, /history/{id}
app.include_router(reports.router)    # /reports/{id}/download


# ── Health Check ────────────────────────────────────────────
# Simple endpoint to verify the backend is running.
# Used by Docker healthcheck and monitoring tools.
@app.get("/health")
def health():
    return {"status": "ok"}
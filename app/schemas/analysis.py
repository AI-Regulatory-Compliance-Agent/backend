"""
Analysis Schemas — Pydantic models for analysis API responses.

These schemas shape what the frontend receives from the backend.
Three levels of detail:
  - AnalysisHistoryItem → compact, for sidebar list
  - AnalysisResponse    → summary, for dashboard cards
  - AnalysisDetailResponse → full, for detailed results page

All use from_attributes=True (Pydantic v2) to auto-serialize
SQLAlchemy ORM objects without manual dict conversion.
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AnalysisHistoryItem(BaseModel):
    """
    Compact schema for the sidebar history list.

    The sidebar shows a list like:
      PayEasy — v1 — June 16 — score 72 HIGH
      PayEasy — v2 — June 18 — score 48 MEDIUM

    Minimal fields to keep the response small when loading
    the full history on page load.
    """
    id: str                                   # analysis run UUID
    company_name: str                         # from joined company
    analysis_type: Optional[str] = None       # product / service / company
    overall_risk_score: Optional[int] = None  # 0-100
    overall_risk_level: Optional[str] = None  # CRITICAL / HIGH / MEDIUM / LOW
    confidence_level: Optional[str] = None    # full / partial / minimal
    status: str                               # pending / running / complete / failed
    created_at: datetime

    class Config:
        from_attributes = True


class AnalysisResponse(BaseModel):
    """
    Summary schema for dashboard display.
    Includes risk information but not the full JSONB data.
    """
    id: str
    company_id: str
    company_name: str
    session_id: str
    status: str
    analysis_type: Optional[str] = None
    overall_risk_score: Optional[int] = None
    overall_risk_level: Optional[str] = None
    risk_score_range: Optional[dict] = None   # {min, max, estimated}
    confidence_level: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AnalysisDetailResponse(BaseModel):
    """
    Full analysis result with all JSONB agent outputs.

    This is what the frontend loads when the user clicks on
    a specific analysis run to see the detailed dashboard:
      - Which regulations apply
      - What gaps were found
      - Risk scores per gap
      - Remediation steps

    The JSONB fields are returned as-is (dict/list) since
    their internal structure varies by analysis_type.
    """
    id: str
    company_id: str
    session_id: str
    status: str
    analysis_type: Optional[str] = None

    # ── Agent Outputs ────────────────────────────────────────
    applicable_regulations: Optional[list] = None
    gaps: Optional[list] = None
    scored_gaps: Optional[list] = None
    remediation_plan: Optional[list] = None

    # ── Risk Summary ─────────────────────────────────────────
    overall_risk_score: Optional[int] = None
    overall_risk_level: Optional[str] = None
    risk_score_range: Optional[dict] = None
    confidence_level: Optional[str] = None

    # ── Timestamps ───────────────────────────────────────────
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AnalysisStartResponse(BaseModel):
    """
    Response from POST /analyze.
    Returns the session_id so the frontend can open an
    SSE connection to /analysis/stream/{session_id}.
    """
    session_id: str
    message: str = "Analysis started"

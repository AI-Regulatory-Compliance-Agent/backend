"""
AnalysisRun Model — SQLAlchemy ORM model for the 'analysis_runs' table.

Stores the complete output of one compliance analysis run.
Each run belongs to a user + company and stores all agent outputs
as JSONB columns for flexible querying.

Key design decisions:
  - All agent outputs (regulations, gaps, scored_gaps, remediation)
    are stored as JSONB — not normalized tables — because:
      1. The structure varies by analysis_type
      2. The frontend consumes them as-is for the dashboard
      3. No need to query individual gaps across runs
  - risk_score_range stores {min, max, estimated} for partial/minimal
    analyses where a single score would be misleading.
  - confidence_level mirrors information_availability to help the
    frontend decide which UI to show (single score vs range).
  - session_id links to Redis session for SSE progress tracking.
  - status lifecycle: pending → running → complete | failed
"""

import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    # ── Primary Key ──────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # ── Foreign Keys ─────────────────────────────────────────
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False
    )
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False
    )

    # ── Session & Status ─────────────────────────────────────

    # Links to Redis session:{session_id} for real-time SSE updates.
    # The SSE router polls this key to push progress to the frontend.
    session_id = Column(String, nullable=False, index=True)

    # Lifecycle: pending → running → complete → failed
    # Set to "pending" on creation, "running" when graph starts,
    # "complete" when report_generator finishes, "failed" on error.
    status = Column(
        String,
        nullable=False,
        default="pending"
    )

    # ── Analysis Configuration ───────────────────────────────

    # What kind of analysis was run: product / service / company
    # Stored here (in addition to company table) so historical
    # queries don't need to join companies.
    analysis_type = Column(String, nullable=True)

    # ── Agent Outputs (JSONB) ────────────────────────────────

    # Node 1 output: list of applicable regulations
    # Format: [{"name": "DPDP Act", "relevance": "...", "confidence": "CONFIRMED"}]
    applicable_regulations = Column(JSONB, nullable=True)

    # Node 2 output: identified compliance gaps
    # Format: [{"regulation": "...", "requirement": "...", "gap": "...", "confidence": "PROBABLE"}]
    gaps = Column(JSONB, nullable=True)

    # Node 3 output: gaps with severity scores added
    # Format: [{"...gap fields...", "severity": 85, "risk_level": "HIGH"}]
    scored_gaps = Column(JSONB, nullable=True)

    # Node 4 output: remediation steps per gap
    # Format: [{"gap": "...", "action": "...", "priority": "high", "label": "mandatory"}]
    remediation_plan = Column(JSONB, nullable=True)

    # ── Risk Summary ─────────────────────────────────────────

    # Overall risk score (0-100). Single value for "full" mode.
    overall_risk_score = Column(Integer, nullable=True)

    # Risk level derived from score: CRITICAL / HIGH / MEDIUM / LOW
    overall_risk_level = Column(String, nullable=True)

    # For partial/minimal modes: {min: 60, max: 85, estimated: 74}
    # Null for "full" mode where a single score is sufficient.
    risk_score_range = Column(JSONB, nullable=True)

    # Confidence in the analysis: "full" / "partial" / "minimal"
    # Maps directly to information_availability from the input.
    # Used by frontend to decide: show single score or range.
    confidence_level = Column(String, nullable=True)

    # ── Timestamps ───────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # ── Relationships ────────────────────────────────────────
    user = relationship("User", back_populates="analysis_runs")
    company = relationship("Company", back_populates="analysis_runs")
    report = relationship("Report", back_populates="analysis_run", uselist=False)
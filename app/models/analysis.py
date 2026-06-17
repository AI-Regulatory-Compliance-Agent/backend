import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
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
    session_id = Column(String, nullable=False, index=True)
    status = Column(
        String,
        nullable=False,
        default="pending"
        # values: pending / running / complete / failed
    )

    # agent outputs stored as JSONB
    applicable_regulations = Column(JSONB, nullable=True)
    gaps = Column(JSONB, nullable=True)
    scored_gaps = Column(JSONB, nullable=True)
    remediation_plan = Column(JSONB, nullable=True)

    # summary fields for dashboard
    overall_risk_score = Column(Integer, nullable=True)
    overall_risk_level = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # relationships
    user = relationship("User", back_populates="analysis_runs")
    company = relationship("Company", back_populates="analysis_runs")
    report = relationship("Report", back_populates="analysis_run", uselist=False)
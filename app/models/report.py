import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, LargeBinary
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id"),
        nullable=False
    )
    pdf_data = Column(LargeBinary, nullable=False)   # raw PDF bytes
    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    # relationships
    analysis_run = relationship("AnalysisRun", back_populates="report")
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Company(Base):
    __tablename__ = "companies"

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
    company_name = Column(String, nullable=False)
    industry = Column(String, nullable=False)
    product_description = Column(Text, nullable=False)
    data_types = Column(ARRAY(String), nullable=False)
    user_regions = Column(ARRAY(String), nullable=False)
    processes_payments = Column(String, nullable=False)
    stores_health_data = Column(String, nullable=False)
    existing_compliance = Column(ARRAY(String), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # relationships
    user = relationship("User", back_populates="companies")
    analysis_runs = relationship("AnalysisRun", back_populates="company")
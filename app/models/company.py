"""
Company Model — SQLAlchemy ORM model for the 'companies' table.

Stores the company profile submitted by the user for compliance analysis.
Each company belongs to a user and can have multiple analysis runs.

Key design decisions:
  - business_description (not product_description) because the system
    analyses products, services, AND companies — not just products.
  - analysis_type determines agent behaviour:
      "product"  → feature-level compliance gaps
      "service"  → service delivery compliance gaps
      "company"  → licensing and registration obligations
  - information_availability controls confidence tagging:
      "full"    → CONFIRMED gaps, single risk score
      "partial" → PROBABLE gaps, risk score range
      "minimal" → UNKNOWN gaps, wide range + low confidence
  - data_types and user_regions are PostgreSQL ARRAY(String) columns
    for multi-select support from the frontend form.
  - processes_payments and stores_health_data are Boolean columns
    that trigger sector-specific regulation checks (RBI, HIPAA, etc.)
"""

import uuid
from sqlalchemy import Column, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    # ── Primary Key ──────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # ── Foreign Key ── links to users.id ─────────────────────
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False
    )

    # ── Company Identity ─────────────────────────────────────
    company_name = Column(String, nullable=False)

    # Industry — validated at schema level via Literal type.
    # Values: fintech, healthtech, edtech, saas, ecommerce,
    #         consulting, managed_services, marketplace, other
    industry = Column(String, nullable=False)

    # Business type — determines remediation focus.
    # Values: software_product, physical_product,
    #         professional_services, managed_services,
    #         marketplace, other
    business_type = Column(String, nullable=False)

    # ── Analysis Configuration ───────────────────────────────

    # What kind of analysis to run:
    #   "product" → feature-level gaps
    #   "service" → service delivery gaps
    #   "company" → licensing obligations
    analysis_type = Column(String, nullable=False)

    # How much info the user has about the target company:
    #   "full"    → self-analysis or complete knowledge
    #   "partial" → some knowledge, some inference needed
    #   "minimal" → external analysis with limited info
    information_availability = Column(String, nullable=False)

    # ── Business Details ─────────────────────────────────────

    # Free-text description used for RAG search against Qdrant.
    # Renamed from product_description to business_description
    # because the system analyses more than just products.
    business_description = Column(Text, nullable=False)

    # Multi-select: which data types the company handles.
    # Values: personal_identifiable, financial, health,
    #         biometric, children_data, none
    data_types = Column(ARRAY(String), nullable=False)

    # Multi-select: where the company's users are located.
    # Values: india, eu, us, global
    user_regions = Column(ARRAY(String), nullable=False)

    # ── Sector-Specific Triggers ─────────────────────────────

    # If True, triggers RBI Payment Aggregator regulation checks
    processes_payments = Column(Boolean, nullable=False, default=False)

    # If True, triggers health data regulation checks (DPDP health
    # provisions, potential HIPAA if US region)
    stores_health_data = Column(Boolean, nullable=False, default=False)

    # ── Existing Compliance ──────────────────────────────────

    # Free-text list of certifications/compliances already held.
    # Used by gap_analysis agent to avoid flagging already-met
    # requirements. Empty list = no existing compliance.
    existing_compliance = Column(ARRAY(String), nullable=True)

    # ── Timestamps ───────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # ── Relationships ────────────────────────────────────────
    user = relationship("User", back_populates="companies")
    analysis_runs = relationship("AnalysisRun", back_populates="company")
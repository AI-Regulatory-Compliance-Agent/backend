"""
Document Model — SQLAlchemy ORM model for the 'documents' table.

Stores metadata for user-uploaded documents associated with companies.
Documents are persisted on disk at /data/uploads/{company_id}/ and
their metadata is stored in PostgreSQL for queryability.

Each document optionally belongs to a company (via company_id foreign key)
and always belongs to a user. When company_id is set, the document's
embedded chunks in Qdrant are filtered by company_id during search.
"""

import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    # ── Primary Key ──────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # ── Foreign Keys ─────────────────────────────────────────
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True  # nullable — uploads before company creation
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False
    )

    # ── File Metadata ────────────────────────────────────────
    # Stored filename on disk (e.g., "doc-a1b2c3d4e5f6.pdf")
    filename = Column(String, nullable=False)

    # User's original filename (e.g., "privacy_policy.pdf")
    original_name = Column(String, nullable=False)

    # Absolute path on disk (e.g., "/data/uploads/{company_id}/doc-xxx.pdf")
    file_path = Column(String, nullable=False)

    # File size in bytes
    file_size = Column(Integer, nullable=False)

    # ── Timestamps ───────────────────────────────────────────
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    # ── Relationships ────────────────────────────────────────
    company = relationship("Company", backref="documents")
    user = relationship("User", backref="documents")

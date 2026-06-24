"""
Upload Router — POST /analyze/upload

Handles document uploads (PDF, DOC, DOCX) for compliance analysis.

Flow:
  1. Frontend uploads files via multipart/form-data
  2. Files are validated (type, size)
  3. Files are saved to a persistent directory (/data/uploads/{company_id}/)
  4. Document metadata is saved to PostgreSQL
  5. Text is extracted, chunked, and embedded into Qdrant for RAG
  6. Document IDs are returned to the frontend
  7. Frontend includes document_ids in the analysis request

File size limits:
  - 10MB per file
  - 50MB total per upload batch

Storage:
  Files are stored persistently at /data/uploads/{company_id}/ (or
  /data/uploads/{user_id}/ when no company_id is provided). This
  directory is backed by a Docker volume so files survive restarts.
"""

import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.document import Document
from app.utils.jwt import verify_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

router = APIRouter(prefix="/analyze", tags=["upload"])

# ── Auth Dependency ──────────────────────────────────────────
_security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> str:
    return verify_token(credentials.credentials)


# ── Response Schema ──────────────────────────────────────────
class UploadResponse(BaseModel):
    document_ids: List[str]
    message: str


# ── Upload Directory ─────────────────────────────────────────
# Persistent storage backed by Docker volume
UPLOAD_BASE_DIR = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))
UPLOAD_BASE_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024       # 10MB
MAX_TOTAL_SIZE = 50 * 1024 * 1024      # 50MB


@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    files: List[UploadFile] = File(...),
    company_id: Optional[str] = Query(None, description="Company ID to associate documents with"),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload supporting documents for compliance analysis.

    Accepts PDF, DOC, and DOCX files.
    Files are saved persistently and their metadata stored in PostgreSQL.
    Document IDs are returned for reference in the analysis request.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided",
        )

    document_ids = []
    total_size = 0

    # Create upload directory scoped by company_id or user_id
    scope_id = company_id if company_id else user_id
    upload_dir = UPLOAD_BASE_DIR / scope_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    for file in files:
        # Validate extension
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type '{ext}' not allowed. Accepted: PDF, DOC, DOCX",
            )

        # Read file content
        content = await file.read()
        file_size = len(content)

        # Validate individual file size
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{file.filename}' exceeds 10MB limit",
            )

        # Validate total size
        total_size += file_size
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Total upload size exceeds 50MB limit",
            )

        # Save file with unique ID
        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        safe_filename = f"{doc_id}{ext}"
        file_path = upload_dir / safe_filename

        with open(file_path, "wb") as f:
            f.write(content)

        # Save document metadata to PostgreSQL
        document = Document(
            company_id=uuid.UUID(company_id) if company_id else None,
            user_id=uuid.UUID(user_id),
            filename=safe_filename,
            original_name=file.filename,
            file_path=str(file_path),
            file_size=file_size,
        )
        db.add(document)

        document_ids.append(doc_id)

        # Store metadata file for backward compatibility with
        # _process_uploaded_documents() in analysis.py
        meta_path = upload_dir / f"{doc_id}.meta"
        with open(meta_path, "w") as f:
            f.write(f"{file.filename}\n{ext}\n{file_size}\n{str(file_path)}")

    db.commit()

    return UploadResponse(
        document_ids=document_ids,
        message=f"Successfully uploaded {len(document_ids)} document(s)",
    )

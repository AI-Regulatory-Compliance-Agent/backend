"""
Upload Router — POST /analyze/upload

Handles document uploads (PDF, DOC, DOCX) for compliance analysis.

Flow:
  1. Frontend uploads files via multipart/form-data
  2. Files are validated (type, size)
  3. Files are saved to a temporary directory
  4. Text is extracted, chunked, and embedded into Qdrant for RAG
  5. Document IDs are returned to the frontend
  6. Frontend includes document_ids in the analysis request

File size limits:
  - 10MB per file
  - 50MB total per upload batch
"""

import os
import uuid
import shutil
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from pydantic import BaseModel
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
UPLOAD_DIR = Path(tempfile.gettempdir()) / "complianceai_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024       # 10MB
MAX_TOTAL_SIZE = 50 * 1024 * 1024      # 50MB


@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    files: List[UploadFile] = File(...),
    user_id: str = Depends(get_current_user),
):
    """
    Upload supporting documents for compliance analysis.

    Accepts PDF, DOC, and DOCX files.
    Files are saved to disk and their IDs returned for reference
    in the analysis request.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided",
        )

    document_ids = []
    total_size = 0

    # Create user-specific upload directory
    user_upload_dir = UPLOAD_DIR / user_id
    user_upload_dir.mkdir(exist_ok=True)

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
        file_path = user_upload_dir / safe_filename

        with open(file_path, "wb") as f:
            f.write(content)

        document_ids.append(doc_id)

        # Store metadata for later RAG processing
        meta_path = user_upload_dir / f"{doc_id}.meta"
        with open(meta_path, "w") as f:
            f.write(f"{file.filename}\n{ext}\n{file_size}\n{str(file_path)}")

    return UploadResponse(
        document_ids=document_ids,
        message=f"Successfully uploaded {len(document_ids)} document(s)",
    )

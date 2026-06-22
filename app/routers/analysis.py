"""
Analysis Router — POST /analyze and GET /analyze/result/{analysis_id}

This is the main API that triggers the compliance analysis pipeline.

Flow:
  1. Frontend sends POST /analyze with CompanyProfileRequest
  2. Router validates input, saves company to PostgreSQL
  3. Creates an AnalysisRun row (status="pending")
  4. Initialises Redis session for SSE progress tracking
  5. Spawns the LangGraph pipeline in a background thread
  6. Returns session_id immediately to the frontend
  7. Frontend opens SSE connection to /analysis/stream/{session_id}
  8. When complete, frontend calls GET /analyze/result/{analysis_id}

Why a background thread?
  The LangGraph pipeline makes multiple LLM calls (5 agents, each
  calling Gemini). Total execution time is 30-120 seconds.
  We can't block the HTTP request for that long.

Authentication:
  All endpoints require a valid JWT token in the Authorization header.
  The get_current_user dependency extracts user_id from the token.
"""

import uuid
import threading
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.company import Company
from app.models.analysis import AnalysisRun
from app.schemas.company import CompanyProfileRequest
from app.schemas.analysis import AnalysisStartResponse, AnalysisDetailResponse
from app.redis_client import set_session
from app.agents.graph import run_compliance_graph
from app.utils.jwt import verify_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

router = APIRouter(prefix="/analyze", tags=["analysis"])

# ── Auth Dependency ──────────────────────────────────────────
# Extracts user_id from JWT token in Authorization header.
_security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security)
) -> str:
    """
    FastAPI dependency that validates JWT and returns user_id.
    Used by all protected endpoints.
    """
    return verify_token(credentials.credentials)


# ── POST /analyze ────────────────────────────────────────────

@router.post("", response_model=AnalysisStartResponse)
def start_analysis(
    request: CompanyProfileRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start a new compliance analysis.

    1. Saves the company profile to PostgreSQL
    2. Creates an analysis run (status=pending)
    3. Initialises Redis session for SSE tracking
    4. Spawns the LangGraph pipeline in background
    5. Returns session_id for SSE connection

    The frontend should immediately open an SSE connection to:
      GET /analysis/stream/{session_id}
    """

    # ── Save Company Profile ─────────────────────────────────
    company = Company(
        user_id=uuid.UUID(user_id),
        company_name=request.target_company_name,
        industry=request.industry,
        business_type=request.business_type,
        analysis_type=request.analysis_type,
        information_availability=request.information_availability,
        business_description=request.business_description,
        data_types=request.data_types,
        user_regions=request.user_regions,
        processes_payments=request.processes_payments,
        stores_health_data=request.stores_health_data,
        existing_compliance=request.existing_compliance
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    # ── Create Analysis Run ──────────────────────────────────
    session_id = f"sess-{uuid.uuid4().hex[:12]}"

    analysis_run = AnalysisRun(
        user_id=uuid.UUID(user_id),
        company_id=company.id,
        session_id=session_id,
        status="pending",
        analysis_type=request.analysis_type
    )
    db.add(analysis_run)
    db.commit()
    db.refresh(analysis_run)

    # ── Initialise Redis Session ─────────────────────────────
    # This is what the SSE router polls to push progress to frontend
    set_session(session_id, {
        "status": "running",
        "current_agent": "regulation_identifier",
        "agent_status": "pending",
        "user_id": user_id,
        "analysis_id": None
    })

    # ── Build Initial State for LangGraph ────────────────────
    initial_state = {
        "company_profile": {
            "company_id": str(company.id),
            "target_company_name": request.target_company_name,
            "industry": request.industry,
            "business_type": request.business_type,
            "business_description": request.business_description,
            "data_types": request.data_types,
            "user_regions": request.user_regions,
            "processes_payments": request.processes_payments,
            "stores_health_data": request.stores_health_data,
            "existing_compliance": request.existing_compliance,
            # New full-mode fields
            "technical_architecture": request.technical_architecture,
            "data_processing_details": request.data_processing_details,
            "third_party_integrations": request.third_party_integrations,
            "employee_count": request.employee_count,
            "annual_revenue_range": request.annual_revenue_range,
        },
        "analysis_mode": request.analysis_mode,
        "analysis_type": request.analysis_type,
        "information_availability": request.information_availability,
        "session_id": session_id,
        "user_id": user_id,
        # Uploaded document IDs for RAG processing
        "uploaded_document_ids": request.uploaded_document_ids,
        # Output fields — initialised empty, filled by agent nodes
        "applicable_regulations": [],
        "gaps": [],
        "scored_gaps": [],
        "remediation_plan": [],
        "overall_risk_score": 0,
        "risk_score_range": None,
        "confidence_level": "",
        "final_report": {},
        "pdf_path": "",
        "error": None
    }

    # ── Process Uploaded Documents via RAG ────────────────────
    # If user uploaded documents, extract text and add to context.
    # This runs synchronously before spawning the pipeline thread
    # since it's fast (seconds) and needed before analysis begins.
    if request.uploaded_document_ids:
        document_texts = _process_uploaded_documents(
            request.uploaded_document_ids, user_id
        )
        if document_texts:
            # Append extracted document text to business description
            # so agents have access to the full context
            doc_context = "\n\n--- UPLOADED DOCUMENT CONTENT ---\n\n" + \
                          "\n\n---\n\n".join(document_texts)
            initial_state["company_profile"]["business_description"] += doc_context

    # ── Spawn Pipeline in Background Thread ──────────────────
    # We use threading (not asyncio) because the LangGraph pipeline
    # is synchronous and makes blocking HTTP calls to Gemini API.
    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(initial_state,),
        daemon=True  # Thread dies when main process exits
    )
    thread.start()

    return AnalysisStartResponse(session_id=session_id)


def _run_pipeline_thread(initial_state: dict):
    """
    Background thread that runs the LangGraph compliance pipeline.

    This runs outside the FastAPI request context, so:
    - No access to request-scoped dependencies
    - Creates its own DB sessions if needed
    - Communicates with frontend via Redis → SSE only
    """
    try:
        run_compliance_graph(initial_state)
    except Exception as e:
        # If the pipeline crashes entirely, mark as failed
        from app.redis_client import update_session
        session_id = initial_state.get("session_id", "")
        update_session(session_id, {
            "status": "failed",
            "error": str(e)
        })
        print(f"❌ Pipeline crashed for session {session_id}: {e}")


def _process_uploaded_documents(document_ids: list[str], user_id: str) -> list[str]:
    """
    Process uploaded documents for RAG integration.

    Reads uploaded files from disk, extracts text content,
    and returns a list of extracted text strings.

    Uses simple text extraction:
      - PDF: via PyPDF2 or pdfplumber if available
      - DOC/DOCX: via python-docx if available

    Falls back to reading raw content if libraries are not installed.
    """
    import tempfile
    from pathlib import Path

    upload_dir = Path(tempfile.gettempdir()) / "complianceai_uploads" / user_id
    extracted_texts = []

    for doc_id in document_ids:
        meta_path = upload_dir / f"{doc_id}.meta"
        if not meta_path.exists():
            print(f"⚠️ Document metadata not found: {doc_id}")
            continue

        with open(meta_path, "r") as f:
            lines = f.read().strip().split("\n")
            if len(lines) < 4:
                continue
            original_name = lines[0]
            ext = lines[1]
            file_path = Path(lines[3])

        if not file_path.exists():
            print(f"⚠️ Document file not found: {file_path}")
            continue

        try:
            text = ""
            if ext == ".pdf":
                try:
                    import pdfplumber
                    with pdfplumber.open(str(file_path)) as pdf:
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text + "\n"
                except ImportError:
                    try:
                        from PyPDF2 import PdfReader
                        reader = PdfReader(str(file_path))
                        for page in reader.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text + "\n"
                    except ImportError:
                        print(f"⚠️ No PDF library available. Install pdfplumber or PyPDF2.")

            elif ext in (".doc", ".docx"):
                try:
                    from docx import Document
                    doc = Document(str(file_path))
                    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                except ImportError:
                    print(f"⚠️ python-docx not installed. Cannot extract .docx content.")

            if text.strip():
                extracted_texts.append(
                    f"[Document: {original_name}]\n{text.strip()}"
                )
                print(f"✅ Extracted {len(text)} chars from {original_name}")
            else:
                print(f"⚠️ No text extracted from {original_name}")

        except Exception as e:
            print(f"❌ Error processing {original_name}: {e}")

    return extracted_texts


# ── GET /analyze/result/{analysis_id} ────────────────────────

@router.get("/result/{analysis_id}", response_model=AnalysisDetailResponse)
def get_analysis_result(
    analysis_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get the full analysis result.

    Called by the frontend after SSE signals completion.
    Returns all JSONB agent outputs for the dashboard.
    """
    analysis = db.query(AnalysisRun).filter(
        AnalysisRun.id == uuid.UUID(analysis_id),
        AnalysisRun.user_id == uuid.UUID(user_id)
    ).first()

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found"
        )

    return AnalysisDetailResponse(
        id=str(analysis.id),
        company_id=str(analysis.company_id),
        session_id=analysis.session_id,
        status=analysis.status,
        analysis_type=analysis.analysis_type,
        applicable_regulations=analysis.applicable_regulations,
        gaps=analysis.gaps,
        scored_gaps=analysis.scored_gaps,
        remediation_plan=analysis.remediation_plan,
        overall_risk_score=analysis.overall_risk_score,
        overall_risk_level=analysis.overall_risk_level,
        risk_score_range=analysis.risk_score_range,
        confidence_level=analysis.confidence_level,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at
    )

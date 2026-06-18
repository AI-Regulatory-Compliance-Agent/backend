"""
Reports Router — PDF report download endpoint.

Single endpoint: GET /reports/{analysis_id}/download
Returns the PDF file stored in PostgreSQL as a downloadable response.

Security:
  - Requires valid JWT token
  - Validates that the requesting user owns the analysis
  - Returns 404 if report not found (not 403, to avoid leaking info)
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.analysis import AnalysisRun
from app.models.report import Report
from app.routers.analysis import get_current_user
import io

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{analysis_id}/download")
def download_report(
    analysis_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Download the PDF compliance report for a given analysis.

    The PDF is stored as raw bytes in the reports table (LargeBinary).
    We stream it back as a downloadable file.

    Response headers:
      Content-Type: application/pdf
      Content-Disposition: attachment; filename="compliance_report_{id}.pdf"

    Frontend usage:
      <a href="/reports/{analysis_id}/download"
         download="compliance_report.pdf">
        Download PDF
      </a>

    Or via JavaScript:
      const response = await api.get(`/reports/${analysisId}/download`,
                                     { responseType: 'blob' });
      const url = URL.createObjectURL(response.data);
      window.open(url);
    """

    # ── Verify ownership ─────────────────────────────────────
    # Check that the analysis belongs to the requesting user
    analysis = db.query(AnalysisRun).filter(
        AnalysisRun.id == uuid.UUID(analysis_id),
        AnalysisRun.user_id == uuid.UUID(user_id)
    ).first()

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found"
        )

    # ── Fetch PDF ────────────────────────────────────────────
    report = db.query(Report).filter(
        Report.analysis_id == uuid.UUID(analysis_id)
    ).first()

    if not report or not report.pdf_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not yet generated. Analysis may still be running."
        )

    # ── Stream PDF back ──────────────────────────────────────
    # Wrap bytes in BytesIO for streaming
    pdf_stream = io.BytesIO(report.pdf_data)

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="compliance_report_{analysis_id[:8]}.pdf"'
            )
        }
    )

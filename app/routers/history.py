"""
History Router — Past analysis browsing and re-analysis support.

Endpoints:
  GET /history        → List all past analyses for the logged-in user
  GET /history/{id}   → Get full details of a specific analysis
                        (includes company profile for re-analysis form pre-fill)

The sidebar on the frontend uses GET /history to show:
  PayEasy — v1 — June 16 — score 72 HIGH
  PayEasy — v2 — June 18 — score 48 MEDIUM

When the user clicks "Update Analysis", GET /history/{id} returns
the full company profile so the form can be pre-populated.
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.analysis import AnalysisRun
from app.models.company import Company
from app.schemas.analysis import AnalysisHistoryItem, AnalysisDetailResponse
from app.schemas.company import CompanyProfileResponse
from app.routers.analysis import get_current_user

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[AnalysisHistoryItem])
def get_analysis_history(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all past analyses for the logged-in user.

    Returns a compact list sorted by creation date (newest first).
    Used by the sidebar component to show analysis history.

    Each item includes:
      - Analysis ID (for navigation)
      - Company name (for display)
      - Risk score and level (for quick assessment)
      - Confidence level (full/partial/minimal badge)
      - Status (pending/running/complete/failed)
      - Created date (for timeline)
    """
    analyses = (
        db.query(AnalysisRun)
        .options(joinedload(AnalysisRun.company))
        .filter(AnalysisRun.user_id == uuid.UUID(user_id))
        .order_by(AnalysisRun.created_at.desc())
        .all()
    )

    # Build response with company name from eager-loaded relationship
    items = []
    for analysis in analyses:
        company_name = analysis.company.company_name if analysis.company else "Unknown"

        items.append(AnalysisHistoryItem(
            id=str(analysis.id),
            company_name=company_name,
            analysis_type=analysis.analysis_type,
            overall_risk_score=analysis.overall_risk_score,
            overall_risk_level=analysis.overall_risk_level,
            confidence_level=analysis.confidence_level,
            status=analysis.status,
            created_at=analysis.created_at
        ))

    return items


@router.get("/{analysis_id}")
def get_analysis_detail(
    analysis_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get full details of a specific analysis, including the company profile.

    Used for two purposes:
      1. Viewing detailed results (dashboard page)
      2. Re-analysis — the company profile is used to pre-fill the form

    Returns both the analysis results AND the company profile
    so the frontend has everything it needs.
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

    # Fetch the company profile for form pre-fill
    company = db.query(Company).filter(
        Company.id == analysis.company_id
    ).first()

    # Build company profile response
    company_data = None
    if company:
        company_data = CompanyProfileResponse(
            id=str(company.id),
            company_name=company.company_name,
            industry=company.industry,
            business_type=company.business_type,
            analysis_type=company.analysis_type,
            information_availability=company.information_availability,
            business_description=company.business_description,
            data_types=company.data_types or [],
            user_regions=company.user_regions or [],
            processes_payments=company.processes_payments,
            stores_health_data=company.stores_health_data,
            existing_compliance=company.existing_compliance or [],
            created_at=company.created_at
        )

    # Build analysis response
    analysis_data = AnalysisDetailResponse(
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

    return {
        "analysis": analysis_data,
        "company": company_data
    }

"""
Report Generator Agent — Node 5 (final) of the compliance pipeline.

PURPOSE:
  The final node that:
  1. Builds a structured JSON report from the entire state
  2. Generates a PDF using the pdf_generator tool
  3. Saves the analysis run to PostgreSQL (analysis_runs table)
  4. Saves the PDF bytes to PostgreSQL (reports table)
  5. Updates Redis with completion status + analysis_id

This is the ONLY node that interacts with PostgreSQL. All previous
nodes only read from Qdrant and write to the in-memory LangGraph state.

EXTERNAL MODE:
  When analysis_mode is "external", the report_data dict includes
  analysis_mode so that pdf_generator can:
  - Display a "🌐 External Research Mode" badge on the cover page
  - Add a methodology note in the disclaimer section

PERSISTENCE:
  After this node runs:
    - PostgreSQL analysis_runs row has all JSONB fields populated
    - PostgreSQL reports row has the PDF bytes
    - Redis session is updated with {status: "complete", analysis_id: uuid}
    - Frontend receives the final SSE event and can fetch results

This node does NOT call the LLM. It's purely a data persistence step.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.agents.state import ComplianceState
from app.tools.pdf_generator import generate_pdf
from app.redis_client import set_agent_progress, update_session
from app.database import SessionLocal
from app.models.analysis import AnalysisRun
from app.models.report import Report


def generate_report(state: ComplianceState) -> dict:
    """
    Node 5: Build report, generate PDF, save everything to PostgreSQL.

    Reads from state:
      - ALL fields from previous nodes
      - company_profile (for report metadata)
      - analysis_mode (for external research notation in PDF)
      - session_id, user_id (for database writes)

    Writes to state:
      - final_report: dict (structured JSON summary)
      - pdf_path: str (analysis_id reference to reports table)

    Returns:
      Dict with keys to merge into ComplianceState.
    """
    session_id = state["session_id"]

    if state.get("error"):
        _mark_failed(session_id, state)
        return {"final_report": {}, "pdf_path": ""}

    set_agent_progress(session_id, "report_generator", "running")

    try:
        # ── Step 1: Build structured report ──────────────────
        report_data = _build_report(state)

        # ── Step 2: Generate PDF ─────────────────────────────
        pdf_bytes = generate_pdf(report_data)

        # ── Step 3: Save to PostgreSQL ───────────────────────
        analysis_id = _save_to_database(state, report_data, pdf_bytes)

        # ── Step 4: Update Redis with completion ─────────────
        set_agent_progress(session_id, "report_generator", "complete")
        update_session(session_id, {
            "status": "complete",
            "analysis_id": str(analysis_id)
        })

        return {
            "final_report": report_data,
            "pdf_path": str(analysis_id)
        }

    except Exception as e:
        import traceback; traceback.print_exc()
        set_agent_progress(session_id, "report_generator", "failed")
        update_session(session_id, {"status": "failed"})
        return {
            "final_report": {},
            "pdf_path": "",
            "error": f"Report generation failed: {str(e)}"
        }


def _build_report(state: ComplianceState) -> dict:
    """
    Build a structured JSON report from the entire pipeline state.

    This JSON is used in two ways:
      1. Fed into pdf_generator to create the PDF
      2. Stored in analysis_runs for API retrieval

    In external mode, analysis_mode is passed through so that the
    PDF generator can add the external research badge and footer note.
    """
    profile = state.get("company_profile", {})
    risk_score = state.get("overall_risk_score", 0)

    # Determine risk level from score
    if risk_score >= 80:
        risk_level = "CRITICAL"
    elif risk_score >= 60:
        risk_level = "HIGH"
    elif risk_score >= 40:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        # Company info
        "company_name": profile.get("target_company_name", "Unknown"),
        "industry": profile.get("industry", "Unknown"),
        "business_type": profile.get("business_type", "Unknown"),

        # Analysis config — analysis_mode is passed to pdf_generator
        # so it can annotate the PDF when mode is "external"
        "analysis_type": state.get("analysis_type", "product"),
        "analysis_mode": state.get("analysis_mode", "self"),
        "information_availability": state.get("information_availability", "full"),

        # Agent outputs
        "applicable_regulations": state.get("applicable_regulations", []),
        "gaps": state.get("gaps", []),
        "scored_gaps": state.get("scored_gaps", []),
        "remediation_plan": state.get("remediation_plan", []),

        # Risk summary
        "overall_risk_score": risk_score,
        "overall_risk_level": risk_level,
        "risk_score_range": state.get("risk_score_range"),
        "confidence_level": state.get("confidence_level", "full"),

        # Metadata
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_regulations": len(state.get("applicable_regulations", [])),
        "total_gaps": len(state.get("scored_gaps", [])),
        "critical_gaps": sum(
            1 for g in state.get("scored_gaps", [])
            if g.get("risk_level") == "CRITICAL"
        ),
        "high_gaps": sum(
            1 for g in state.get("scored_gaps", [])
            if g.get("risk_level") == "HIGH"
        )
    }


def _save_to_database(
    state: ComplianceState,
    report_data: dict,
    pdf_bytes: bytes
) -> uuid.UUID:
    """
    Save the analysis run and PDF report to PostgreSQL.

    Creates/updates two rows:
      1. analysis_runs — all JSONB agent outputs + risk summary
      2. reports — PDF bytes linked to the analysis run

    Uses a fresh database session (not from FastAPI dependency)
    because this runs inside a background thread, not a request context.
    """
    # Create a new database session for this background operation
    db: Session = SessionLocal()

    try:
        # Determine risk level
        risk_score = state.get("overall_risk_score", 0)
        if risk_score >= 80:
            risk_level = "CRITICAL"
        elif risk_score >= 60:
            risk_level = "HIGH"
        elif risk_score >= 40:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        # Look for existing analysis run (created by the analysis router)
        analysis_run = db.query(AnalysisRun).filter(
            AnalysisRun.session_id == state["session_id"]
        ).first()

        if analysis_run:
            # Update existing run with results
            analysis_run.status = "complete"
            analysis_run.analysis_type = state.get("analysis_type")
            analysis_run.applicable_regulations = state.get("applicable_regulations", [])
            analysis_run.gaps = state.get("gaps", [])
            analysis_run.scored_gaps = state.get("scored_gaps", [])
            analysis_run.remediation_plan = state.get("remediation_plan", [])
            analysis_run.overall_risk_score = risk_score
            analysis_run.overall_risk_level = risk_level
            analysis_run.risk_score_range = state.get("risk_score_range")
            analysis_run.confidence_level = state.get("confidence_level")
            analysis_run.completed_at = datetime.now(timezone.utc)
        else:
            # Create new run if not found (shouldn't normally happen)
            analysis_run = AnalysisRun(
                user_id=uuid.UUID(state["user_id"]),
                company_id=uuid.UUID(state["company_profile"].get("company_id", str(uuid.uuid4()))),
                session_id=state["session_id"],
                status="complete",
                analysis_type=state.get("analysis_type"),
                applicable_regulations=state.get("applicable_regulations", []),
                gaps=state.get("gaps", []),
                scored_gaps=state.get("scored_gaps", []),
                remediation_plan=state.get("remediation_plan", []),
                overall_risk_score=risk_score,
                overall_risk_level=risk_level,
                risk_score_range=state.get("risk_score_range"),
                confidence_level=state.get("confidence_level"),
                completed_at=datetime.now(timezone.utc)
            )
            db.add(analysis_run)

        db.flush()  # Get the analysis_run.id

        # Save PDF report
        report = Report(
            analysis_id=analysis_run.id,
            pdf_data=pdf_bytes
        )
        db.add(report)

        db.commit()
        return analysis_run.id

    except Exception as e:
        import traceback; traceback.print_exc()
        db.rollback()
        raise e
    finally:
        db.close()


def _mark_failed(session_id: str, state: ComplianceState):
    """
    Mark the analysis run as failed in both Redis and PostgreSQL.
    Called when a previous node has set an error.
    """
    set_agent_progress(session_id, "report_generator", "failed")
    update_session(session_id, {"status": "failed"})

    # Update PostgreSQL status
    db: Session = SessionLocal()
    try:
        analysis_run = db.query(AnalysisRun).filter(
            AnalysisRun.session_id == session_id
        ).first()
        if analysis_run:
            analysis_run.status = "failed"
            analysis_run.completed_at = datetime.now(timezone.utc)
            analysis_run.error_message = state.get("error")
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

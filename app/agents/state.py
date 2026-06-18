"""
ComplianceState — LangGraph state definition for the compliance agent pipeline.

This TypedDict defines the ENTIRE shared state that flows through all 5 agent
nodes in the LangGraph. Each node reads what it needs and writes its outputs
back into this state.

Data flow through the pipeline:
  ┌──────────────────────┐
  │  User Input (form)   │ → company_profile, analysis_mode, analysis_type,
  │                      │   information_availability, session_id, user_id
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐
  │ regulation_identifier│ → writes: applicable_regulations
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐
  │    gap_analysis      │ → writes: gaps
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐
  │    risk_scoring      │ → writes: scored_gaps, overall_risk_score,
  │                      │          risk_score_range, confidence_level
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐
  │    remediation       │ → writes: remediation_plan
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐
  │  report_generator    │ → writes: final_report, pdf_path
  └──────────────────────┘

State is IN-MEMORY only. It exists for the duration of one graph execution.
Persistent storage happens in the report_generator node which saves
everything to PostgreSQL (analysis_runs + reports tables).

Confidence levels used across all agents:
  CONFIRMED  — publicly verifiable or directly stated by user
  PROBABLE   — inferred from industry norms or partial information
  UNKNOWN    — cannot determine without internal access to the company
"""

from typing import TypedDict, Optional


class ComplianceState(TypedDict):
    """
    Shared state for the LangGraph compliance analysis pipeline.
    All 5 agent nodes read from and write to this state.
    """

    # ── Input Fields ─────────────────────────────────────────
    # Set once at graph invocation, never modified by agents.

    # The full company profile dict from CompanyProfileRequest.
    # Contains: target_company_name, industry, business_type,
    # business_description, data_types, user_regions,
    # processes_payments, stores_health_data, existing_compliance
    company_profile: dict

    # "self" or "external" — controls whether web_search is used
    analysis_mode: str

    # "product", "service", or "company" — changes agent prompts
    analysis_type: str

    # "full", "partial", or "minimal" — controls confidence tagging
    information_availability: str

    # Redis session key — used by agents to push progress updates
    # via set_agent_progress(session_id, agent_name, status)
    session_id: str

    # User UUID — used by report_generator to save to PostgreSQL
    user_id: str

    # ── Node 1 Output: regulation_identifier ─────────────────
    # List of regulations that apply to this company/product/service.
    # Each item: {"name": str, "relevance": str, "confidence": str}
    # Confidence is one of: CONFIRMED, PROBABLE, UNKNOWN
    applicable_regulations: list[dict]

    # ── Node 2 Output: gap_analysis ──────────────────────────
    # List of compliance gaps found.
    # Each item: {"regulation": str, "requirement": str,
    #             "gap": str, "confidence": str}
    gaps: list[dict]

    # ── Node 3 Output: risk_scoring ──────────────────────────
    # Gaps with severity scores added.
    # Each item: {"...gap fields...", "severity": int, "risk_level": str}
    scored_gaps: list[dict]

    # Single overall risk score (0-100). Always set.
    overall_risk_score: int

    # For partial/minimal modes: {"min": int, "max": int, "estimated": int}
    # None for "full" mode where a single score is definitive.
    risk_score_range: Optional[dict]

    # Mirrors information_availability: "full" / "partial" / "minimal"
    # Tells the frontend which UI to render (gauge vs range bar).
    confidence_level: str

    # ── Node 4 Output: remediation ───────────────────────────
    # Remediation steps per gap.
    # Each item: {"gap": str, "action": str, "priority": str,
    #             "label": str, "timeline": str}
    # label is one of: "mandatory", "recommended", "verify_first"
    # "verify_first" is used for UNKNOWN confidence gaps.
    remediation_plan: list[dict]

    # ── Node 5 Output: report_generator ──────────────────────
    # Structured JSON summary of the entire analysis.
    # This is what gets saved to PostgreSQL and also used
    # to generate the PDF report.
    final_report: dict

    # File path or identifier for the generated PDF.
    # After report_generator runs, the PDF bytes are saved
    # to the reports table; this field tracks the reference.
    pdf_path: str

    # ── Error Tracking ───────────────────────────────────────
    # If any agent node fails, the error message is stored here.
    # The graph checks this between nodes — if set, remaining
    # nodes are skipped and status is set to "failed".
    error: Optional[str]

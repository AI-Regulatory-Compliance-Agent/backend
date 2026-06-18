"""
LangGraph Compliance Pipeline — Orchestrates all 5 agent nodes.

This is the core of the system. It defines a LINEAR StateGraph where
each node runs sequentially and passes its outputs through shared state.

Pipeline Flow:
  START → regulation_identifier → gap_analysis → risk_scoring
        → remediation → report_generator → END

There are NO conditional branches in this graph. Every analysis runs
through all 5 nodes regardless of analysis_type or information_availability.
The nodes themselves handle different behaviour internally based on
these parameters.

Error Handling:
  If any node fails, it writes an error message to state["error"].
  Subsequent nodes check for this and skip their work, passing the
  error forward. The report_generator marks the run as "failed" in
  PostgreSQL.

Usage:
  from app.agents.graph import run_compliance_graph

  result = run_compliance_graph({
      "company_profile": {...},
      "analysis_mode": "self",
      "analysis_type": "product",
      "information_availability": "full",
      "session_id": "abc123",
      "user_id": "user-uuid",
      ...initial state fields...
  })
"""

from langgraph.graph import StateGraph, END
from app.agents.state import ComplianceState
from app.agents.regulation_identifier import identify_regulations
from app.agents.gap_analysis import analyze_gaps
from app.agents.risk_scoring import score_risks
from app.agents.remediation import generate_remediation
from app.agents.report_generator import generate_report


def _build_graph() -> StateGraph:
    """
    Build the LangGraph StateGraph with all 5 nodes.

    Node order (linear, no branching):
      1. regulation_identifier → find applicable regulations
      2. gap_analysis          → compare regs vs company profile
      3. risk_scoring          → score each gap's severity
      4. remediation           → generate fix steps per gap
      5. report_generator      → build report, PDF, save to DB

    Each node function signature:
      def node_func(state: ComplianceState) -> dict
    The returned dict is merged into the shared state.
    """

    # Create a StateGraph that uses ComplianceState as its schema
    graph = StateGraph(ComplianceState)

    # ── Add Nodes ────────────────────────────────────────────
    # Each node is a function that takes the full state and returns
    # a partial dict of updates to merge into state.

    graph.add_node("regulation_identifier", identify_regulations)
    graph.add_node("gap_analysis", analyze_gaps)
    graph.add_node("risk_scoring", score_risks)
    graph.add_node("remediation", generate_remediation)
    graph.add_node("report_generator", generate_report)

    # ── Define Edges (Linear Flow) ───────────────────────────
    # START → regulation_identifier
    graph.set_entry_point("regulation_identifier")

    # regulation_identifier → gap_analysis
    graph.add_edge("regulation_identifier", "gap_analysis")

    # gap_analysis → risk_scoring
    graph.add_edge("gap_analysis", "risk_scoring")

    # risk_scoring → remediation
    graph.add_edge("risk_scoring", "remediation")

    # remediation → report_generator
    graph.add_edge("remediation", "report_generator")

    # report_generator → END
    graph.add_edge("report_generator", END)

    return graph


# ── Compile the Graph ────────────────────────────────────────
# Compiled once at module level. The compiled graph is a runnable
# object that can be invoked with an initial state dict.
_graph = _build_graph()
compliance_app = _graph.compile()


def run_compliance_graph(initial_state: dict) -> dict:
    """
    Execute the full compliance analysis pipeline.

    This is the main entry point called by the analysis router.
    It runs synchronously inside a background thread.

    Args:
        initial_state: Dict matching ComplianceState with at minimum:
            - company_profile: dict
            - analysis_mode: str
            - analysis_type: str
            - information_availability: str
            - session_id: str
            - user_id: str
            Plus empty defaults for output fields.

    Returns:
        Final ComplianceState dict with all fields populated
        by the 5 agent nodes.

    Example:
        result = run_compliance_graph({
            "company_profile": {
                "target_company_name": "PayEasy",
                "industry": "fintech",
                "business_description": "...",
                ...
            },
            "analysis_mode": "self",
            "analysis_type": "product",
            "information_availability": "full",
            "session_id": "sess-abc123",
            "user_id": "uuid-of-user",
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
        })
    """
    # Invoke the compiled graph with the initial state.
    # LangGraph handles state passing between nodes automatically.
    result = compliance_app.invoke(initial_state)
    return result

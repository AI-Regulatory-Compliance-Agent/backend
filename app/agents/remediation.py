"""
Remediation Agent — Node 4 of the compliance pipeline.

PURPOSE:
  For each scored gap, generates specific remediation steps.
  Uses RAG to fetch relevant regulation clauses to ensure
  recommendations are grounded in actual legal text.

REMEDIATION LABELS:
  mandatory    — required by law, must be implemented
  recommended  — best practice, strongly advised
  verify_first — for UNKNOWN confidence gaps; verify the gap
                 actually exists before implementing the fix

EXTERNAL MODE:
  When analysis_mode is "external", the web_search_results from Node 1
  are injected into the remediation prompt. This allows the LLM to:
  - Reference known enforcement actions and what regulators penalised
  - Suggest remediation steps that directly address documented violations
  - Prioritise actions that match patterns of real regulatory scrutiny
  For example: "Regulators fined X company for missing a DPA appointment
  — prioritize appointing a Data Protection Officer first."

COMPANY TYPE BEHAVIOUR:
  When analysis_type is "company":
  - Remediations focus on obtaining licenses/registrations
  - Steps include: application processes, required documents,
    filing deadlines, registration authorities
  - Does NOT recommend product feature changes

OUTPUT:
  Writes remediation_plan to state:
  [{"gap": "No consent mechanism", "action": "Implement cookie consent banner...",
    "priority": "high", "label": "mandatory", "timeline": "30 days",
    "regulation": "DPDP Act"}]
"""

import json
from langchain_groq import ChatGroq
from app.agents.state import ComplianceState
from app.tools.qdrant_search import search_regulations
from app.redis_client import set_agent_progress
from app.config import get_settings

settings = get_settings()

# ── LLM Instance ────────────────────────────────────────────
# Temperature 0.3 — slightly creative for actionable remediation advice.
_llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=get_settings().groq_api_key,
    temperature=0.3
)


def generate_remediation(state: ComplianceState) -> dict:
    """
    Node 4: Generate remediation steps for each scored gap.

    Reads from state:
      - scored_gaps (from Node 3, gaps with severity + risk_level)
      - web_search_results (from Node 1, populated in external mode)
      - company_profile
      - analysis_type
      - analysis_mode
      - session_id

    Writes to state:
      - remediation_plan: list[dict]

    Returns:
      Dict with keys to merge into ComplianceState.
    """
    session_id = state["session_id"]
    scored_gaps = state.get("scored_gaps", [])
    analysis_type = state["analysis_type"]
    analysis_mode = state["analysis_mode"]
    profile = state["company_profile"]
    company_id = profile.get("company_id")

    # Pull web search results gathered by Node 1 (external mode only).
    # In self mode this is an empty list and web_context stays "".
    web_search_results = state.get("web_search_results", [])

    if state.get("error"):
        return {"remediation_plan": [], "error": state["error"]}

    set_agent_progress(session_id, "remediation", "running")

    try:
        if not scored_gaps:
            set_agent_progress(session_id, "remediation", "complete")
            return {"remediation_plan": []}

        # ── Gather regulation context via RAG ────────────────
        # Group gaps by regulation for efficient RAG retrieval
        gaps_by_regulation = {}
        for gap in scored_gaps:
            reg = gap.get("regulation", "Unknown")
            if reg not in gaps_by_regulation:
                gaps_by_regulation[reg] = []
            gaps_by_regulation[reg].append(gap)

        # Fetch relevant regulation clauses for each regulation
        reg_contexts = {}
        for reg_name in gaps_by_regulation:
            chunks = search_regulations(
                query=f"{reg_name} compliance requirements remediation",
                regulation_name=reg_name,
                top_k=5,
                company_id=company_id
            )
            if chunks:
                context = "\n".join(c["text"] for c in chunks)
                reg_contexts[reg_name] = context

        # ── Build and send prompt ────────────────────────────
        prompt = _build_remediation_prompt(
            scored_gaps=scored_gaps,
            profile=profile,
            analysis_type=analysis_type,
            analysis_mode=analysis_mode,
            reg_contexts=reg_contexts,
            web_search_results=web_search_results
        )

        response = _llm.invoke(prompt)
        remediation_plan = _parse_response(response.content)

        set_agent_progress(session_id, "remediation", "complete")
        return {"remediation_plan": remediation_plan}

    except Exception as e:
        import traceback; traceback.print_exc()
        set_agent_progress(session_id, "remediation", "failed")
        return {
            "remediation_plan": [],
            "error": f"Remediation generation failed: {str(e)}"
        }


def _build_remediation_prompt(
    scored_gaps: list[dict],
    profile: dict,
    analysis_type: str,
    analysis_mode: str,
    reg_contexts: dict,
    web_search_results: list[str]
) -> str:
    """Build the remediation prompt with gap details and regulation context.

    In external mode, also injects the web search results as enforcement
    intelligence so the LLM can suggest remediation steps that directly
    address documented regulatory penalties and enforcement patterns.
    """

    # Format gaps
    gaps_text = ""
    for i, gap in enumerate(scored_gaps, 1):
        gaps_text += f"""
Gap {i}:
  Regulation: {gap.get('regulation', 'Unknown')}
  Requirement: {gap.get('requirement', 'Unknown')}
  Gap: {gap.get('gap', 'Unknown')}
  Severity: {gap.get('severity', 50)}/100
  Risk Level: {gap.get('risk_level', 'MEDIUM')}
  Confidence: {gap.get('confidence', 'UNKNOWN')}
"""

    # Format regulation contexts from RAG
    reg_context_text = ""
    if reg_contexts:
        reg_context_text = "\n\nRelevant regulation text for reference:\n"
        for reg_name, context in reg_contexts.items():
            reg_context_text += f"\n--- {reg_name} ---\n{context}\n"

    # External mode: inject web research as enforcement intelligence.
    # Placed BEFORE the labeling rules so it informs prioritisation.
    web_context_block = ""
    if analysis_mode == "external" and web_search_results:
        web_context_block = """
ENFORCEMENT INTELLIGENCE (from external web research):
Use these publicly known facts about the company and its regulatory environment
to suggest more targeted remediation. Where enforcement actions are documented,
prioritise those specific remediation steps higher and mention the precedent
in your action description.
"""
        for snippet in web_search_results:
            web_context_block += f"• {snippet}\n"
        web_context_block += "\n"

    # Analysis type specific instructions
    if analysis_type == "company":
        type_instructions = """
REMEDIATION FOCUS (Company Analysis):
- How to obtain required licenses/registrations
- Required documents and application processes
- Filing deadlines and registration authorities
- Corporate governance steps needed
- DO NOT recommend product feature changes
"""
    else:
        type_instructions = f"""
REMEDIATION FOCUS ({'Product' if analysis_type == 'product' else 'Service'} Analysis):
- Technical implementations needed (consent mechanisms, data encryption, etc.)
- Policy and documentation requirements
- Process changes for data handling
- User rights implementation steps
"""

    prompt = f"""You are a regulatory compliance remediation expert.

TASK: For each compliance gap, generate a specific, actionable remediation step.

COMPANY: {profile.get('target_company_name', 'Unknown')}
INDUSTRY: {profile.get('industry', 'Unknown')}
{type_instructions}
{web_context_block}
LABELING RULES:
- "mandatory": Required by law. Non-compliance = penalties. MUST implement.
- "recommended": Best practice. Strongly advised but not legally required.
- "verify_first": For gaps with UNKNOWN confidence. Verify the gap exists
                  before implementing. Don't spend resources fixing a gap
                  that might not exist.

PRIORITY RULES:
- "critical": CRITICAL risk level gaps → must fix within 30 days
- "high": HIGH risk level gaps → fix within 60 days
- "medium": MEDIUM risk level gaps → fix within 90 days
- "low": LOW risk level gaps → plan for next quarter

COMPLIANCE GAPS:
{gaps_text}
{reg_context_text}

RESPOND IN EXACTLY THIS JSON FORMAT (no markdown, no extra text):
[
  {{
    "gap_index": 1,
    "gap": "Brief description of the gap",
    "regulation": "Regulation name",
    "action": "Specific, actionable remediation step",
    "priority": "critical or high or medium or low",
    "label": "mandatory or recommended or verify_first",
    "timeline": "Recommended timeline (e.g., 30 days, 60 days)"
  }}
]
"""
    return prompt


def _parse_response(response_text: str) -> list[dict]:
    """Parse the LLM remediation response."""
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        remediations = json.loads(text)
        if isinstance(remediations, list):
            validated = []
            for rem in remediations:
                validated.append({
                    "gap": rem.get("gap", "Not specified"),
                    "regulation": rem.get("regulation", "Unknown"),
                    "action": rem.get("action", "No action specified"),
                    "priority": rem.get("priority", "medium"),
                    "label": rem.get("label", "recommended"),
                    "timeline": rem.get("timeline", "90 days")
                })
            return validated
        return []
    except json.JSONDecodeError:
        print("⚠️  Failed to parse remediation response")
        return []

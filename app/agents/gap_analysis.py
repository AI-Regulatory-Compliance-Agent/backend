"""
Gap Analysis Agent — Node 2 of the compliance pipeline.

PURPOSE:
  For each regulation identified by Node 1, fetch the actual regulation
  text from Qdrant and compare its requirements against what the company
  currently does (as described in the business_description).

HOW IT WORKS:
  1. Loops through each regulation from applicable_regulations
  2. RAG searches Qdrant for detailed clauses of that specific regulation
  3. Sends regulation text + company description to Gemini
  4. Gemini identifies specific gaps (what the reg requires vs what's missing)
  5. Each gap is tagged with a confidence level:
       CONFIRMED  — gap is clearly present based on stated info
       PROBABLE   — gap is likely based on industry norms
       UNKNOWN    — cannot determine without internal access

COMPANY TYPE BEHAVIOUR:
  When analysis_type is "company", the agent focuses on:
  - Missing licenses/registrations (not feature gaps)
  - Corporate governance gaps
  - Mandatory filing requirements

OUTPUT:
  Writes gaps to state:
  [{"regulation": "DPDP Act", "requirement": "Consent before processing",
    "gap": "No consent mechanism described", "confidence": "CONFIRMED"}]
"""

import json
from langchain_groq import ChatGroq
from app.agents.state import ComplianceState
from app.tools.qdrant_search import search_regulations
from app.redis_client import set_agent_progress
from app.config import get_settings

settings = get_settings()

# ── LLM Instance ────────────────────────────────────────────
# Temperature 0.1 for more precise gap identification.
# Lower temp = less creative = more factual gap analysis.
_llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=get_settings().groq_api_key,
    temperature=0.1
)


def analyze_gaps(state: ComplianceState) -> dict:
    """
    Node 2: Compare regulation requirements against company profile.

    Reads from state:
      - applicable_regulations (from Node 1)
      - company_profile
      - analysis_type
      - information_availability
      - session_id

    Writes to state:
      - gaps: list[dict]

    Returns:
      Dict with keys to merge into ComplianceState.
    """
    session_id = state["session_id"]
    profile = state["company_profile"]
    regulations = state.get("applicable_regulations", [])
    analysis_type = state["analysis_type"]
    info_availability = state["information_availability"]
    company_id = profile.get("company_id")

    # Check for upstream errors — skip if regulation identification failed
    if state.get("error"):
        return {"gaps": [], "error": state["error"]}

    set_agent_progress(session_id, "gap_analysis", "running")

    try:
        all_gaps = []

        # ── Process each regulation ──────────────────────────
        for regulation in regulations:
            reg_name = regulation.get("name", "")

            # RAG: fetch detailed regulation chunks for this specific regulation
            reg_chunks = search_regulations(
                query=f"{reg_name} requirements obligations",
                regulation_name=reg_name,
                top_k=8,
                company_id=company_id
            )

            # If no chunks found with exact name, try broader search
            if not reg_chunks:
                reg_chunks = search_regulations(
                    query=reg_name,
                    top_k=5,
                    company_id=company_id
                )

            # Build regulation context from retrieved chunks
            reg_context = ""
            if reg_chunks:
                reg_context = f"\nDetailed provisions from {reg_name}:\n"
                for chunk in reg_chunks:
                    reg_context += f"\n{chunk['text']}\n"

            # Build the gap analysis prompt
            prompt = _build_gap_prompt(
                profile=profile,
                regulation=regulation,
                reg_context=reg_context,
                analysis_type=analysis_type,
                info_availability=info_availability
            )

            # Call Gemini
            response = _llm.invoke(prompt)

            # Parse gaps for this regulation
            regulation_gaps = _parse_response(response.content, reg_name)
            all_gaps.extend(regulation_gaps)

        set_agent_progress(session_id, "gap_analysis", "complete")
        return {"gaps": all_gaps}

    except Exception as e:
        set_agent_progress(session_id, "gap_analysis", "failed")
        return {
            "gaps": [],
            "error": f"Gap analysis failed: {str(e)}"
        }


def _build_gap_prompt(
    profile: dict,
    regulation: dict,
    reg_context: str,
    analysis_type: str,
    info_availability: str
) -> str:
    """
    Build the gap analysis prompt for a specific regulation.

    The prompt structure:
      1. System context (what you are, what you're doing)
      2. Regulation details (name, relevance, actual text from Qdrant)
      3. Company details (what the company does)
      4. Instructions (what to look for, how to tag confidence)
      5. Output format
    """
    reg_name = regulation.get("name", "Unknown")
    reg_relevance = regulation.get("relevance", "")

    # Company details
    company_section = f"""
Company: {profile.get('target_company_name', 'Unknown')}
Industry: {profile.get('industry', 'Unknown')}
Business Description: {profile.get('business_description', 'Not provided')}
Data Types: {', '.join(profile.get('data_types', []))}
Regions: {', '.join(profile.get('user_regions', []))}
Processes Payments: {profile.get('processes_payments', False)}
Stores Health Data: {profile.get('stores_health_data', False)}
Existing Compliance: {', '.join(profile.get('existing_compliance', [])) or 'None'}
"""

    if analysis_type == "company":
        focus = """
FOCUS: Identify gaps in LICENSING, REGISTRATION, and CORPORATE OBLIGATIONS only.
Do NOT analyse product features or data handling.
Look for:
- Missing mandatory licenses or registrations
- Incomplete regulatory filings
- Corporate governance gaps
- Mandatory reporting requirements not being met
"""
    else:
        focus = f"""
FOCUS: Identify gaps in {'PRODUCT FEATURE' if analysis_type == 'product' else 'SERVICE DELIVERY'} COMPLIANCE.
Look for:
- Data handling gaps (collection, storage, processing, deletion)
- {'User rights not implemented (access, correction, deletion)' if analysis_type == 'product' else 'Vendor obligations not met'}
- Consent mechanism gaps
- Cross-border data transfer issues
- Security requirements not addressed
"""

    # Confidence tagging instructions
    confidence_rules = {
        "full": "Tag as CONFIRMED when the gap is clearly present based on the stated information. Only use PROBABLE if genuinely uncertain.",
        "partial": "Tag as CONFIRMED only when obvious from stated info. Use PROBABLE for gaps inferred from industry norms. Use UNKNOWN for areas the description doesn't address.",
        "minimal": "Tag most gaps as UNKNOWN since information is minimal. Only tag as CONFIRMED if explicitly contradicted by the description."
    }

    prompt = f"""You are a regulatory compliance auditor performing a detailed gap analysis.

REGULATION: {reg_name}
Why it applies: {reg_relevance}
{reg_context}

COMPANY BEING ANALYSED:
{company_section}
{focus}

CONFIDENCE TAGGING RULES:
Information availability: {info_availability}
{confidence_rules.get(info_availability, confidence_rules['partial'])}

If the company has listed "{reg_name}" or related certifications in existing compliance, acknowledge it but still check for specific sub-requirements that may be missing.

RESPOND IN EXACTLY THIS JSON FORMAT (no markdown, no extra text):
[
  {{
    "regulation": "{reg_name}",
    "requirement": "What the regulation requires",
    "gap": "What is missing or not addressed",
    "confidence": "CONFIRMED or PROBABLE or UNKNOWN"
  }}
]

If there are NO gaps for this regulation, return an empty array: []
"""
    return prompt


def _parse_response(response_text: str, regulation_name: str) -> list[dict]:
    """
    Parse the LLM response into a list of gap dicts.
    Adds regulation_name fallback if the LLM omits it.
    """
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        gaps = json.loads(text)
        if isinstance(gaps, list):
            validated = []
            for gap in gaps:
                validated.append({
                    "regulation": gap.get("regulation", regulation_name),
                    "requirement": gap.get("requirement", "Not specified"),
                    "gap": gap.get("gap", "Not specified"),
                    "confidence": gap.get("confidence", "UNKNOWN")
                })
            return validated
        return []
    except json.JSONDecodeError:
        print(f"⚠️  Failed to parse gap_analysis response for {regulation_name}")
        return []

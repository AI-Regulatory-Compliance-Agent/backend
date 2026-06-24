"""
Regulation Identifier Agent — Node 1 of the compliance pipeline.

PURPOSE:
  Determines which government regulations apply to the given company
  based on its industry, business description, data types, and regions.

BEHAVIOUR BY ANALYSIS TYPE:
  product/service + full/partial:
    → RAG search Qdrant with business_description
    → Gemini reasons which regulations actually apply
  product/service + minimal:
    → Industry baseline prompt (no RAG over description)
    → Gemini infers from industry alone
  company type:
    → Searches for licensing/registration requirements
    → Different prompt focused on corporate obligations

EXTERNAL MODE:
  When analysis_mode is "external", the web_search tool is called
  FIRST to gather public info about the target company. These
  search results are added to the LLM prompt as context before
  regulation identification.

OUTPUT:
  Writes applicable_regulations to state:
  [{"name": "DPDP Act", "relevance": "Handles personal data of Indian users",
    "confidence": "CONFIRMED"}]
"""

import json
from langchain_groq import ChatGroq
from app.agents.state import ComplianceState
from app.tools.qdrant_search import search_regulations
from app.tools.web_search import search_web
from app.redis_client import set_agent_progress
from app.config import get_settings

settings = get_settings()

# ── LLM Instance ────────────────────────────────────────────
# Using Gemini via langchain-google-genai for structured reasoning.
# Temperature 0.2 for more deterministic regulation identification.
_llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=get_settings().groq_api_key,
    temperature=0.2
)


def identify_regulations(state: ComplianceState) -> dict:
    """
    Node 1: Identify which regulations apply to this company.

    Reads from state:
      - company_profile (dict with all company details)
      - analysis_type ("product" / "service" / "company")
      - analysis_mode ("self" / "external")
      - information_availability ("full" / "partial" / "minimal")
      - session_id (for Redis progress updates)

    Writes to state:
      - applicable_regulations: list[dict]

    Returns:
      Dict with keys to merge into ComplianceState.
    """
    session_id = state["session_id"]
    profile = state["company_profile"]
    analysis_type = state["analysis_type"]
    analysis_mode = state["analysis_mode"]
    info_availability = state["information_availability"]

    # ── Step 0: Signal start ─────────────────────────────────
    set_agent_progress(session_id, "regulation_identifier", "running")

    try:
        # ── Step 1: Gather context ───────────────────────────

        # If external mode, search the web first for public info
        web_context = ""
        if analysis_mode == "external":
            company_name = profile.get("target_company_name", "")
            industry = profile.get("industry", "")
            search_query = f"{company_name} {industry} compliance regulations India"
            web_results = search_web(search_query)
            if web_results:
                web_context = "\n\nPublic information found about this company:\n"
                web_context += "\n".join(f"- {r}" for r in web_results)

        # ── Step 2: RAG search (skip for minimal info) ───────
        rag_context = ""
        if info_availability != "minimal":
            # Use business description to find relevant regulation chunks
            description = profile.get("business_description", "")
            rag_results = search_regulations(
                description, top_k=10,
                company_id=profile.get("company_id")
            )
            if rag_results:
                rag_context = "\n\nRelevant regulation excerpts:\n"
                for chunk in rag_results:
                    rag_context += (
                        f"\n[{chunk['regulation_name']}] "
                        f"(Page {chunk['page_number']}):\n"
                        f"{chunk['text']}\n"
                    )

        # ── Step 3: Build the LLM prompt ─────────────────────
        prompt = _build_prompt(
            profile=profile,
            analysis_type=analysis_type,
            info_availability=info_availability,
            rag_context=rag_context,
            web_context=web_context
        )

        # ── Step 4: Call Gemini ───────────────────────────────
        response = _llm.invoke(prompt)

        # ── Step 5: Parse the response ────────────────────────
        regulations = _parse_response(response.content)

        # ── Step 6: Signal completion ─────────────────────────
        set_agent_progress(session_id, "regulation_identifier", "complete")

        return {"applicable_regulations": regulations}

    except Exception as e:
        set_agent_progress(session_id, "regulation_identifier", "failed")
        return {
            "applicable_regulations": [],
            "error": f"Regulation identification failed: {str(e)}"
        }


def _build_prompt(
    profile: dict,
    analysis_type: str,
    info_availability: str,
    rag_context: str,
    web_context: str
) -> str:
    """
    Build the LLM prompt based on analysis_type and info_availability.

    Different prompt templates are used for:
      - product/service analysis → focus on data handling & features
      - company analysis → focus on licenses & registrations
      - minimal info → industry baseline only
    """

    # Common company details section
    company_details = f"""
Company Name: {profile.get('target_company_name', 'Unknown')}
Industry: {profile.get('industry', 'Unknown')}
Business Type: {profile.get('business_type', 'Unknown')}
Business Description: {profile.get('business_description', 'Not provided')}
Data Types Handled: {', '.join(profile.get('data_types', []))}
User Regions: {', '.join(profile.get('user_regions', []))}
Processes Payments: {profile.get('processes_payments', False)}
Stores Health Data: {profile.get('stores_health_data', False)}
Existing Compliance: {', '.join(profile.get('existing_compliance', [])) or 'None declared'}
"""

    if analysis_type == "company":
        # Company-level analysis: focus on licensing requirements
        prompt = f"""You are a regulatory compliance expert specialising in Indian and international business law.

TASK: Identify all mandatory licenses, registrations, and regulatory obligations that this company needs to legally operate.

COMPANY DETAILS:
{company_details}

FOCUS AREAS:
- RBI licensing requirements (if fintech/payments)
- SEBI registration (if dealing with securities)
- MCA/ROC filings and corporate governance
- CERT-In incident reporting obligations
- GST/tax registrations
- Industry-specific licenses
- Data protection registrations (DPDP Act)
- International registrations if operating in EU/US

DO NOT focus on product features or data handling — focus ONLY on what this company needs to legally exist and operate.
{rag_context}
{web_context}
"""
    elif info_availability == "minimal":
        # Minimal info: industry baseline, no RAG
        prompt = f"""You are a regulatory compliance expert.

TASK: Based ONLY on the industry and business type, identify the baseline regulations that would typically apply to this kind of company. You have LIMITED information.

COMPANY DETAILS:
{company_details}

Since information is minimal, identify regulations based on industry standards.
Tag ALL regulations with confidence level "UNKNOWN" since we cannot verify applicability.
{web_context}
"""
    else:
        # Standard product/service analysis
        prompt = f"""You are a regulatory compliance expert specialising in Indian and international data protection and technology law.

TASK: Identify all government regulations that apply to this company's {'products' if analysis_type == 'product' else 'services'}.

COMPANY DETAILS:
{company_details}

ANALYSIS FOCUS:
- Data handling and privacy requirements
- {'Product features and user rights' if analysis_type == 'product' else 'Service delivery and vendor obligations'}
- Consent mechanisms
- Cross-border data transfer rules
- Sector-specific regulations

Information Availability: {info_availability}
- If "full": tag regulations as CONFIRMED when clearly applicable
- If "partial": tag as CONFIRMED only when obvious, PROBABLE for inferred ones
{rag_context}
{web_context}
"""

    # Common output format instruction
    prompt += """

RESPOND IN EXACTLY THIS JSON FORMAT (no markdown, no extra text):
[
  {
    "name": "Full regulation name",
    "relevance": "Brief explanation of why this regulation applies",
    "confidence": "CONFIRMED or PROBABLE or UNKNOWN"
  }
]
"""
    return prompt


def _parse_response(response_text: str) -> list[dict]:
    """
    Parse the LLM response into a list of regulation dicts.
    Handles cases where the LLM wraps JSON in markdown code blocks.
    """
    # Strip markdown code blocks if present
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        regulations = json.loads(text)
        # Validate structure
        if isinstance(regulations, list):
            validated = []
            for reg in regulations:
                validated.append({
                    "name": reg.get("name", "Unknown Regulation"),
                    "relevance": reg.get("relevance", "Not specified"),
                    "confidence": reg.get("confidence", "UNKNOWN")
                })
            return validated
        return []
    except json.JSONDecodeError:
        # If JSON parsing fails, return empty list
        # The error will be logged but won't crash the pipeline
        print(f"⚠️  Failed to parse regulation_identifier response as JSON")
        return []

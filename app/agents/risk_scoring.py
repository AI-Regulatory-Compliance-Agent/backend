"""
Risk Scoring Agent — Node 3 of the compliance pipeline.

PURPOSE:
  Takes the list of compliance gaps from Node 2 and assigns a severity
  score (0-100) to each gap. Then calculates an overall risk score.

SCORING BEHAVIOUR BY INFORMATION AVAILABILITY:
  full mode:
    → Single definitive score per gap
    → Single overall risk score (e.g., 74)
    → No score range needed

  partial mode:
    → Single score per gap but with acknowledged uncertainty
    → Overall score range: {min: 60, max: 85, estimated: 74}
    → Confidence level: "partial"

  minimal mode:
    → Scores are rough estimates
    → Wide overall score range: {min: 40, max: 90, estimated: 68}
    → Confidence level: "minimal"

EXTERNAL MODE:
  When analysis_mode is "external", two things happen:
  1. The web_search_results from Node 1 are injected into the scoring
     prompt so the LLM can reference known enforcement actions and fines.
  2. A SECOND targeted web search is run for enforcement precedents
     (e.g. "Razorpay GDPR fine penalty enforcement"). This gives the
     LLM concrete examples of regulatory action to calibrate scores.
  3. Each scored gap gets a "score_range" field (e.g. "65–80") in
     addition to the single "severity" integer. This expresses
     uncertainty when public information is incomplete.

RISK LEVELS:
  CRITICAL: 80-100 (immediate action required)
  HIGH:     60-79  (action required soon)
  MEDIUM:   40-59  (should be addressed)
  LOW:      0-39   (nice to have)

OUTPUT:
  Writes to state:
    scored_gaps: gaps with severity, risk_level, (and score_range in external mode)
    overall_risk_score: int (always set)
    risk_score_range: dict (only for partial/minimal)
    confidence_level: str
"""

import json
from langchain_groq import ChatGroq
from app.agents.state import ComplianceState
from app.redis_client import set_agent_progress
from app.config import get_settings

settings = get_settings()

# ── LLM Instance ────────────────────────────────────────────
# Temperature 0.1 for consistent scoring across runs.
_llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=get_settings().groq_api_key,
    temperature=0.1
)


def _get_risk_level(score: int) -> str:
    """
    Convert numeric score to risk level label.

    Thresholds:
      80-100 → CRITICAL (regulatory penalties likely)
      60-79  → HIGH (significant compliance risk)
      40-59  → MEDIUM (moderate risk, should address)
      0-39   → LOW (minor gaps, low priority)
    """
    if score >= 80:
        return "CRITICAL"
    elif score >= 60:
        return "HIGH"
    elif score >= 40:
        return "MEDIUM"
    else:
        return "LOW"


def score_risks(state: ComplianceState) -> dict:
    """
    Node 3: Score each gap's severity and calculate overall risk.

    Reads from state:
      - gaps (from Node 2)
      - information_availability
      - analysis_mode
      - company_profile (for enforcement search query in external mode)
      - web_search_results (from Node 1, reused here in external mode)
      - session_id

    Writes to state:
      - scored_gaps: list[dict]
      - overall_risk_score: int
      - risk_score_range: dict or None
      - confidence_level: str

    Returns:
      Dict with keys to merge into ComplianceState.
    """
    session_id = state["session_id"]
    gaps = state.get("gaps", [])
    info_availability = state["information_availability"]
    analysis_mode = state["analysis_mode"]
    profile = state["company_profile"]
    web_search_results = state.get("web_search_results", [])

    if state.get("error"):
        return {
            "scored_gaps": [],
            "overall_risk_score": 0,
            "risk_score_range": None,
            "confidence_level": info_availability,
            "error": state["error"]
        }

    set_agent_progress(session_id, "risk_scoring", "running")

    try:
        # ── Handle no gaps case ──────────────────────────────
        if not gaps:
            set_agent_progress(session_id, "risk_scoring", "complete")
            return {
                "scored_gaps": [],
                "overall_risk_score": 0,
                "risk_score_range": None,
                "confidence_level": info_availability
            }

        # ── External mode: gather enforcement context ────────
        # Run a targeted enforcement search in addition to the general
        # web search already done in Node 1. This provides the LLM with
        # concrete examples of regulatory fines for similar companies,
        # leading to better-calibrated scores.
        enforcement_snippets = []
        if analysis_mode == "external":
            try:
                from app.tools.web_search import search_web
                company_name = profile.get("target_company_name", "")
                regions = ", ".join(profile.get("user_regions", [])) or "India"
                # Extract unique regulation names from gaps for targeted search
                reg_names = list({g.get("regulation", "") for g in gaps if g.get("regulation")})
                reg_query_part = reg_names[0] if reg_names else "data protection"
                enforcement_query = (
                    f"{company_name} {reg_query_part} regulatory fine "
                    f"penalty enforcement action {regions}"
                )
                enforcement_snippets = search_web(enforcement_query, num_results=4)
            except Exception as search_err:
                # Non-fatal: scoring continues without enforcement context
                print(f"⚠️  Enforcement search failed (non-fatal): {search_err}")

        # ── Build scoring prompt ─────────────────────────────
        prompt = _build_scoring_prompt(
            gaps=gaps,
            info_availability=info_availability,
            analysis_mode=analysis_mode,
            web_search_results=web_search_results,
            enforcement_snippets=enforcement_snippets
        )

        # ── Call LLM ─────────────────────────────────────────
        response = _llm.invoke(prompt)

        # ── Parse scored gaps ────────────────────────────────
        scored_gaps = _parse_response(
            response_text=response.content,
            original_gaps=gaps,
            analysis_mode=analysis_mode
        )

        # ── Calculate overall risk ───────────────────────────
        result = _calculate_overall_risk(scored_gaps, info_availability)

        set_agent_progress(session_id, "risk_scoring", "complete")
        return result

    except Exception as e:
        set_agent_progress(session_id, "risk_scoring", "failed")
        return {
            "scored_gaps": [],
            "overall_risk_score": 0,
            "risk_score_range": None,
            "confidence_level": info_availability,
            "error": f"Risk scoring failed: {str(e)}"
        }


def _build_scoring_prompt(
    gaps: list[dict],
    info_availability: str,
    analysis_mode: str,
    web_search_results: list[str],
    enforcement_snippets: list[str]
) -> str:
    """Build the LLM prompt for risk scoring."""

    # Format gaps as numbered list for the LLM
    gaps_text = ""
    for i, gap in enumerate(gaps, 1):
        gaps_text += f"""
Gap {i}:
  Regulation: {gap.get('regulation', 'Unknown')}
  Requirement: {gap.get('requirement', 'Unknown')}
  Gap: {gap.get('gap', 'Unknown')}
  Confidence: {gap.get('confidence', 'UNKNOWN')}
"""

    # Info availability affects scoring instructions
    scoring_guidance = {
        "full": """
Score each gap based on:
1. Regulatory penalty severity (fines, license revocation)
2. How critical the requirement is (mandatory vs recommended)
3. Impact on data subjects/users if not addressed
4. How far the company is from compliance
Provide a SINGLE definitive score per gap.""",

        "partial": """
Score each gap considering uncertainty:
1. Where information confirms a gap, score based on severity
2. Where information is inferred (PROBABLE), acknowledge uncertainty
3. Account for the possibility that some gaps may not actually exist
Scores should reflect PROBABLE severity, not worst-case.""",

        "minimal": """
Scoring with minimal information:
1. Score based on industry-typical severity
2. Acknowledge that scores are rough estimates
3. UNKNOWN confidence gaps should be scored conservatively
4. Results will include wide score ranges to reflect uncertainty."""
    }

    # External mode: inject company web research and enforcement precedents
    # as context blocks to ground scores in real-world regulatory outcomes.
    external_context_block = ""
    if analysis_mode == "external":
        if web_search_results:
            external_context_block += "\nPUBLIC COMPANY CONTEXT (from web research):\n"
            for snippet in web_search_results:
                external_context_block += f"• {snippet}\n"

        if enforcement_snippets:
            external_context_block += "\nENFORCEMENT PRECEDENTS (recent regulatory actions):\n"
            for snippet in enforcement_snippets:
                external_context_block += f"• {snippet}\n"

        if external_context_block:
            external_context_block = (
                "\nEXTERNAL RESEARCH CONTEXT:\n"
                "Use the following publicly available information to calibrate "
                "your scores. Known enforcement actions for similar companies "
                "or regulations should push scores higher where relevant.\n"
                + external_context_block
            )

    # In external mode, ask LLM to also provide a score range per gap
    score_range_instruction = ""
    if analysis_mode == "external":
        score_range_instruction = """
Additionally, for each gap provide a "score_range" string (e.g. "65-80") that
reflects the plausible range of severity given the uncertainty in public data.
The score_range should be included in your JSON response."""

    prompt = f"""You are a regulatory risk assessment expert.

TASK: Score the severity of each compliance gap on a scale of 0-100.

SCORING SCALE:
  80-100: CRITICAL — Regulatory penalties likely, immediate action required
  60-79:  HIGH — Significant risk, action required soon
  40-59:  MEDIUM — Moderate risk, should be addressed in planning
  0-39:   LOW — Minor gap, low priority

Information Availability: {info_availability}
{scoring_guidance.get(info_availability, scoring_guidance['partial'])}
{external_context_block}

COMPLIANCE GAPS TO SCORE:
{gaps_text}
{score_range_instruction}

RESPOND IN EXACTLY THIS JSON FORMAT (no markdown, no extra text):
[
  {{
    "gap_index": 1,
    "severity": 85,
    "score_range": "75-90",
    "reasoning": "Brief explanation of why this score"
  }}
]

Note: "score_range" is only meaningful in external mode. In self-assessment mode,
you may set it to the same value as severity (e.g. "85-85") or omit it.
"""
    return prompt


def _parse_response(
    response_text: str,
    original_gaps: list[dict],
    analysis_mode: str
) -> list[dict]:
    """
    Parse LLM scoring response and merge with original gap data.

    In external mode, also extracts "score_range" from the LLM response
    and attaches it to each scored gap.
    """
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    scored_gaps = []
    try:
        scores = json.loads(text)
        if isinstance(scores, list):
            for score_item in scores:
                idx = score_item.get("gap_index", 0) - 1  # 0-indexed
                severity = score_item.get("severity", 50)
                reasoning = score_item.get("reasoning", "")
                score_range = score_item.get("score_range", "")

                # Clamp severity to 0-100
                severity = max(0, min(100, severity))

                # Merge with original gap data
                if 0 <= idx < len(original_gaps):
                    gap = original_gaps[idx].copy()
                else:
                    gap = {"regulation": "Unknown", "requirement": "Unknown",
                           "gap": "Unknown", "confidence": "UNKNOWN"}

                gap["severity"] = severity
                gap["risk_level"] = _get_risk_level(severity)
                gap["reasoning"] = reasoning

                # Attach score_range in external mode when the LLM provides it
                if analysis_mode == "external" and score_range:
                    gap["score_range"] = score_range

                scored_gaps.append(gap)

    except json.JSONDecodeError:
        print("⚠️  Failed to parse risk_scoring response")
        # Fallback: assign default scores to all gaps
        for gap in original_gaps:
            scored = gap.copy()
            scored["severity"] = 50
            scored["risk_level"] = "MEDIUM"
            scored["reasoning"] = "Default score — LLM response parsing failed"
            scored_gaps.append(scored)

    return scored_gaps


def _calculate_overall_risk(
    scored_gaps: list[dict],
    info_availability: str
) -> dict:
    """
    Calculate the overall risk score and range from individual gap scores.

    For "full" mode: weighted average of gap severities
    For "partial"/"minimal": range with min/max/estimated
    """
    if not scored_gaps:
        return {
            "scored_gaps": [],
            "overall_risk_score": 0,
            "risk_score_range": None,
            "confidence_level": info_availability
        }

    # Extract severity scores
    severities = [g.get("severity", 0) for g in scored_gaps]

    # Weighted average — critical gaps weigh more heavily.
    # Use square-root weighting so very high scores pull the
    # overall score up more than low scores pull it down.
    weights = [s ** 0.5 for s in severities]
    total_weight = sum(weights) or 1
    weighted_avg = sum(s * w for s, w in zip(severities, weights)) / total_weight
    estimated = round(weighted_avg)

    # Clamp to 0-100
    estimated = max(0, min(100, estimated))

    if info_availability == "full":
        # Full info: single definitive score, no range needed
        return {
            "scored_gaps": scored_gaps,
            "overall_risk_score": estimated,
            "risk_score_range": None,
            "confidence_level": "full"
        }
    else:
        # Partial/minimal: calculate range
        min_score = max(0, min(severities))
        max_score = min(100, max(severities))

        # Widen range for minimal info
        if info_availability == "minimal":
            min_score = max(0, min_score - 15)
            max_score = min(100, max_score + 10)

        return {
            "scored_gaps": scored_gaps,
            "overall_risk_score": estimated,
            "risk_score_range": {
                "min": min_score,
                "max": max_score,
                "estimated": estimated
            },
            "confidence_level": info_availability
        }

"""
Company Schemas — Pydantic models for company profile API requests/responses.

CompanyProfileRequest is the PRIMARY input schema for the entire system.
Every field here directly influences how the 5 agent nodes behave:
  - analysis_mode  → decides if web_search tool is activated
  - analysis_type  → changes agent prompts and focus areas
  - information_availability → controls confidence tagging
  - business_description → used as RAG query against Qdrant
  - data_types / user_regions → trigger specific regulation checks

The Literal types enforce exact allowed values at the API boundary,
so agents never receive unexpected inputs.
"""

from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime


class CompanyProfileRequest(BaseModel):
    """
    Input schema for POST /analyze.

    This is the form the user fills out on the frontend.
    Every field is validated with Literal types to ensure
    only expected values reach the agent pipeline.
    """

    # ── Analysis Configuration ───────────────────────────────

    # "self" = analysing your own company (no web search needed)
    # "external" = analysing another company (web_search activated)
    analysis_mode: Literal["self", "external"] = Field(
        description="Whether the user is analysing their own company or an external one"
    )

    # Determines which agent prompts and focus areas to use:
    #   "product"  → feature-level compliance gaps
    #   "service"  → service delivery compliance gaps
    #   "company"  → licensing and registration obligations
    analysis_type: Literal["product", "service", "company"] = Field(
        description="Type of compliance analysis to perform"
    )

    # Controls confidence tagging on gaps:
    #   "full"    → user has complete knowledge → CONFIRMED gaps
    #   "partial" → some knowledge → PROBABLE gaps + score range
    #   "minimal" → limited knowledge → UNKNOWN gaps + wide range
    information_availability: Literal["full", "partial", "minimal"] = Field(
        description="How much information the user has about the target company"
    )

    # ── Company Identity ─────────────────────────────────────

    target_company_name: str = Field(
        min_length=1,
        max_length=200,
        description="Name of the company being analysed"
    )

    # Industry determines baseline regulation checks.
    # Expanded to include consulting, managed_services, marketplace.
    industry: Literal[
        "fintech", "healthtech", "edtech", "saas", "ecommerce",
        "consulting", "managed_services", "marketplace", "other"
    ] = Field(
        description="Industry sector of the target company"
    )

    # Business type determines remediation recommendations.
    business_type: Literal[
        "software_product", "physical_product",
        "professional_services", "managed_services",
        "marketplace", "other"
    ] = Field(
        description="Type of business the company operates"
    )

    # ── Business Details ─────────────────────────────────────

    # This is the most important field for RAG.
    # The regulation_identifier agent embeds this text and searches
    # Qdrant to find which regulations apply.
    business_description: str = Field(
        min_length=10,
        max_length=5000,
        description="Detailed description of what the company does, "
                    "its products/services, and how it handles data"
    )

    # Multi-select: what kind of data the company processes.
    # Common values: personal_identifiable, financial, health,
    #   biometric, children_data, behavioral, location,
    #   communications, employment, none
    # Also accepts custom free-text values from the frontend.
    data_types: list[str] = Field(
        description="Types of data the company collects or processes"
    )

    # Multi-select: where the company's users are located.
    # Common values: india, eu, us, uk, singapore, uae, japan, australia, global
    # Also accepts custom free-text values from the frontend.
    user_regions: list[str] = Field(
        description="Geographic regions where the company's users are located"
    )

    # ── Sector-Specific Triggers ─────────────────────────────

    # If True → RBI Payment Aggregator regulations are checked
    processes_payments: bool = Field(
        default=False,
        description="Whether the company processes financial payments"
    )

    # If True → health data regulations are checked
    stores_health_data: bool = Field(
        default=False,
        description="Whether the company stores health-related data"
    )

    # ── Existing Compliance ──────────────────────────────────

    # Free-text list of certifications already held.
    # The gap_analysis agent uses this to skip already-met requirements.
    # Examples: ["ISO 27001", "SOC 2 Type II", "PCI DSS"]
    existing_compliance: list[str] = Field(
        default=[],
        description="List of compliance certifications the company already has"
    )


class CompanyProfileResponse(BaseModel):
    """
    Response schema when returning a saved company profile.
    Used by the history endpoint to pre-populate the form
    for re-analysis with updated information.
    """
    id: str
    company_name: str
    industry: str
    business_type: str
    analysis_type: str
    information_availability: str
    business_description: str
    data_types: list[str]
    user_regions: list[str]
    processes_payments: bool
    stores_health_data: bool
    existing_compliance: list[str]
    created_at: datetime

    class Config:
        from_attributes = True  # enables ORM mode for SQLAlchemy models

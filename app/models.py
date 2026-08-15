"""Shared type definitions for job dictionaries used by the pipeline.

These classes are static type hints only. They do not create PostgreSQL tables
and they do not perform runtime validation. Database tables are defined by the
SQLAlchemy classes in ``app.database.models``.

The pipeline gradually enriches a job dictionary: extraction supplies the
basic posting fields, classification adds current sponsorship evidence, and
historical matching adds prior DOL evidence. ``total=False`` reflects that a
job may legitimately contain only the fields available at its current stage.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


# ---------------------------------------------------------------------------
# Sponsorship classification types
# ---------------------------------------------------------------------------

# Restrict current-policy values to the four states emitted by the rules-based
# classifier. Type checkers can then detect misspellings and unsupported labels.
CurrentPolicy = Literal[
    "AVAILABLE",
    "UNAVAILABLE",
    "CONFLICTING",
    "UNKNOWN",
]


class ClassificationEvidence(TypedDict):
    """One explainable rules-based match from a job description."""

    # Stable identifier of the regular-expression rule that matched.
    rule_id: str

    # Exact portion of the sentence matched by the rule.
    matched_text: str

    # Complete sentence shown to users as human-readable evidence.
    sentence: str


# ---------------------------------------------------------------------------
# Pipeline job schema
# ---------------------------------------------------------------------------

class JobPosting(TypedDict, total=False):
    """Typed shape of a job dictionary as it moves through the pipeline.

    ``total=False`` makes every field optional at the type level because early
    pipeline stages have not yet produced classification or historical fields.
    Individual functions should still guarantee the fields required by the
    stage immediately following them.
    """

    # Source identity
    source: str
    source_job_id: str

    # Core posting information
    title: str
    company: str
    company_website: str | None
    location: str | None
    city: str | None
    state: str | None
    country: str | None
    is_remote: bool
    employment_type: str | None
    posted_at: str | None
    description: str
    apply_url: str | None
    publisher: str | None

    # Optional compensation information supplied by the provider
    salary_min: float | None
    salary_max: float | None
    salary_period: str | None

    # Search provenance and title relevance
    search_queries: list[str]
    is_relevant: bool
    relevance_reason: str

    # Current-posting sponsorship classification
    current_policy: CurrentPolicy
    current_policy_evidence: list[ClassificationEvidence]
    h1b_transfer_supported: bool
    h1b_transfer_evidence: list[ClassificationEvidence]
    classifier_version: str

    # Historical employer-and-occupation evidence from DOL records
    historical_support: bool
    historical_evidence: dict[str, Any] | None
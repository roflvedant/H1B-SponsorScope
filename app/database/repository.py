"""Persist normalized jobs, query lineage, and versioned sponsorship evidence.

This repository is the database boundary for both batch ingestion and live
search. It centralizes normalization, deduplication keys, upsert behavior,
transactions, and versioned enrichment storage so callers do not duplicate SQL
logic across services.
"""

import hashlib
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    AgentSponsorshipReview,
    Company,
    HistoricalSponsorshipEvidence,
    JobPosting,
    SearchQuery,
    SearchResult,
    SponsorshipClassification,
)


# ---------------------------------------------------------------------------
# Shared parsing and identity helpers
# ---------------------------------------------------------------------------

def normalize_text(value: str | None) -> str:
    """Create a stable lowercase key for database lookups."""

    normalized = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO timestamp, returning None for missing or invalid input."""

    if not value:
        return None

    try:
        # Python's ISO parser accepts an explicit UTC offset rather than the
        # provider's commonly used trailing ``Z`` representation.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fallback_source_id(job: dict[str, Any]) -> str:
    """Build a deterministic identifier when the provider omits its job ID.

    Hashing stable identifying fields allows repeated ingestion to update the
    same JobPosting instead of inserting duplicates.
    """

    identifying_text = "|".join(
        str(job.get(field) or "")
        for field in ("company", "title", "location", "apply_url")
    )
    return hashlib.sha256(identifying_text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Query and company resolution
# ---------------------------------------------------------------------------

def get_or_create_query(
    database: Session,
    raw_query: str,
) -> SearchQuery:
    """Return the canonical SearchQuery row for a user-entered query."""

    normalized_query = normalize_text(raw_query)
    stored_query = database.scalar(
        select(SearchQuery).where(
            SearchQuery.normalized_query == normalized_query
        )
    )
    if stored_query is not None:
        return stored_query

    stored_query = SearchQuery(
        raw_query=raw_query,
        normalized_query=normalized_query,
        country="US",
    )
    database.add(stored_query)
    database.flush()  # Populate the UUID before creating SearchResult links.
    return stored_query


def get_or_create_company(
    database: Session,
    company_name: str,
    website: str | None = None,
) -> Company:
    """Resolve a normalized company or insert a new canonical company row."""

    normalized_name = normalize_text(company_name)
    company = database.scalar(
        select(Company).where(
            Company.normalized_name == normalized_name
        )
    )

    if company is not None:
        # Enrich an existing company without replacing a known website.
        if website and not company.website_domain:
            company.website_domain = website
        return company

    company = Company(
        canonical_name=company_name,
        normalized_name=normalized_name,
        website_domain=website,
    )
    database.add(company)
    database.flush()
    return company


# ---------------------------------------------------------------------------
# Job and query-result persistence
# ---------------------------------------------------------------------------

def upsert_job(
    database: Session,
    job: dict[str, Any],
    company: Company,
) -> JobPosting:
    """Insert a new provider job or refresh its mutable fields."""

    source = job.get("source") or "jsearch"
    source_job_id = job.get("source_job_id") or fallback_source_id(job)

    stored_job = database.scalar(
        select(JobPosting).where(
            JobPosting.source == source,
            JobPosting.source_job_id == source_job_id,
        )
    )

    values = {
        "company_id": company.id,
        "source_company_name": job.get("company") or "Unknown",
        "title": job.get("title") or "Untitled job",
        "description": job.get("description"),
        "city": job.get("city"),
        "state": job.get("state"),
        "country": job.get("country"),
        "employment_type": job.get("employment_type"),
        "apply_url": job.get("apply_url") or "",
        "posted_at": parse_datetime(job.get("posted_at")),
        "is_active": True,
        "raw_payload": job,
    }

    if stored_job is not None:
        for field, value in values.items():
            setattr(stored_job, field, value)
        database.flush()
        return stored_job

    stored_job = JobPosting(
        source=source,
        source_job_id=source_job_id,
        **values,
    )
    database.add(stored_job)
    database.flush()
    return stored_job


def link_query_to_job(
    database: Session,
    search_query: SearchQuery,
    job: JobPosting,
) -> None:
    """Create an idempotent query-to-job lineage link."""

    existing_link = database.scalar(
        select(SearchResult).where(
            SearchResult.search_query_id == search_query.id,
            SearchResult.job_id == job.id,
        )
    )
    if existing_link is not None:
        return

    database.add(
        SearchResult(
            search_query_id=search_query.id,
            job_id=job.id,
        )
    )


# ---------------------------------------------------------------------------
# Versioned enrichment persistence
# ---------------------------------------------------------------------------

def save_classification(
    database: Session,
    job: JobPosting,
    data: dict[str, Any],
) -> None:
    """Insert or update one deterministic classifier version for a job."""

    classifier_version = data.get("classifier_version") or "rules-v1"
    classification = database.scalar(
        select(SponsorshipClassification).where(
            SponsorshipClassification.job_id == job.id,
            SponsorshipClassification.classifier_version
            == classifier_version,
        )
    )

    values = {
        "policy": data.get("current_policy") or "UNKNOWN",
        "method": "DETERMINISTIC_RULES",
        "confidence": None,
        "evidence": data.get("current_policy_evidence") or [],
        "h1b_transfer_supported": bool(
            data.get("h1b_transfer_supported")
        ),
        "requires_human_review": data.get("current_policy")
        in {"UNKNOWN", "CONFLICTING"},
    }

    if classification is not None:
        for field, value in values.items():
            setattr(classification, field, value)
        return

    database.add(
        SponsorshipClassification(
            job_id=job.id,
            classifier_version=classifier_version,
            **values,
        )
    )


def save_historical_evidence(
    database: Session,
    job: JobPosting,
    data: dict[str, Any],
) -> None:
    """Insert or update one version of historical evidence for a job.

    Matcher versions coexist so algorithm changes remain auditable. The API can
    select the newest version without deleting evidence produced by earlier
    matching strategies.
    """

    evidence = data.get("historical_evidence") or {}
    matching_version = (
        evidence.get("matching_version") or "historical-v3"
    )

    stored_evidence = database.scalar(
        select(HistoricalSponsorshipEvidence).where(
            HistoricalSponsorshipEvidence.job_id == job.id,
            HistoricalSponsorshipEvidence.matching_version
            == matching_version,
        )
    )

    values = {
        "historical_support": bool(data.get("historical_support")),
        "employer_match_type": evidence.get("employer_match_type"),
        "occupation_match_type": evidence.get("occupation_match_type"),
        "matched_dol_employer": evidence.get("matched_dol_employer"),
        "matched_dol_job_title": evidence.get("matched_dol_job_title"),
        "matched_soc_code": evidence.get("matched_soc_code"),
        "matched_soc_title": evidence.get("matched_soc_title"),
        "certified_lca_cases": int(
            evidence.get("certified_lca_cases") or 0
        ),
        "worker_positions": int(evidence.get("worker_positions") or 0),
        "fiscal_year": evidence.get("fiscal_year"),
        # Confidence belongs to the matcher. The repository stores it without
        # inventing or recalculating a value.
        "match_confidence": evidence.get("match_confidence"),
        "requires_human_review": bool(
            evidence.get("requires_human_review")
        ),
        # Preserve the complete explanation for debugging and future audits.
        "evidence_payload": evidence if evidence else None,
    }

    if stored_evidence is not None:
        for field, value in values.items():
            setattr(stored_evidence, field, value)
        return

    database.add(
        HistoricalSponsorshipEvidence(
            job_id=job.id,
            matching_version=matching_version,
            **values,
        )
    )


def save_agent_review(
    database: Session,
    job: JobPosting,
    data: dict[str, Any],
) -> None:
    """Insert or refresh one versioned, auditable Bedrock agent review."""

    review = data.get("agent_review")
    if not isinstance(review, dict):
        return

    agent_version = review.get("agent_version")
    if not agent_version:
        return

    stored_review = database.scalar(
        select(AgentSponsorshipReview).where(
            AgentSponsorshipReview.job_id == job.id,
            AgentSponsorshipReview.agent_version == agent_version,
        )
    )

    values = {
        "prompt_version": review.get("prompt_version") or "unknown",
        "model_id": review.get("model_id") or "unknown",
        "description_hash": review.get("description_hash") or "",
        "status": review.get("status") or "ERROR",
        "proposed_policy": review.get("proposed_policy") or "UNKNOWN",
        "effective_policy": review.get("effective_policy") or "UNKNOWN",
        "confidence": review.get("confidence") or 0,
        "evidence": review.get("evidence") or [],
        "rationale": review.get("rationale"),
        "requires_human_review": bool(
            review.get("requires_human_review", True)
        ),
        "latency_ms": int(review.get("latency_ms") or 0),
        "input_tokens": int(review.get("input_tokens") or 0),
        "output_tokens": int(review.get("output_tokens") or 0),
        "estimated_cost_usd": review.get("estimated_cost_usd") or 0,
        "error_code": review.get("error_code"),
    }

    if stored_review is not None:
        for field, value in values.items():
            setattr(stored_review, field, value)
        return

    database.add(
        AgentSponsorshipReview(
            job_id=job.id,
            agent_version=agent_version,
            **values,
        )
    )


# ---------------------------------------------------------------------------
# Transactional batch save
# ---------------------------------------------------------------------------

def save_enriched_jobs(
    database: Session,
    jobs: list[dict[str, Any]],
) -> dict[str, int]:
    """Persist one enriched job batch as a single transaction.

    Any exception rolls back the entire unit of work, preventing partially
    persisted searches in which jobs, classifications, and query links disagree.
    """

    saved_jobs = 0
    created_links = 0

    try:
        for job_data in jobs:
            company = get_or_create_company(
                database,
                job_data.get("company") or "Unknown",
                job_data.get("company_website"),
            )
            job = upsert_job(database, job_data, company)

            save_classification(database, job, job_data)
            save_agent_review(database, job, job_data)
            save_historical_evidence(database, job, job_data)

            for raw_query in job_data.get("search_queries", []):
                if not raw_query:
                    continue

                search_query = get_or_create_query(database, raw_query)
                before_count = len(job.search_results)
                link_query_to_job(database, search_query, job)
                database.flush()

                if len(job.search_results) > before_count:
                    created_links += 1

            saved_jobs += 1

        database.commit()

    except Exception:
        database.rollback()
        raise

    return {
        "saved_jobs": saved_jobs,
        "created_links": created_links,
    }

"""
FastAPI entry point for the H-1B Job Intelligence application.

Responsibilities
----------------
This module exposes the backend HTTP endpoints used by the frontend:

    GET  /health
    GET  /jobs
    GET  /dashboard
    POST /search

The module coordinates API input/output. It does not contain ingestion,
classification, or database-writing business logic. Those responsibilities
remain in their dedicated service and repository modules.

Data precedence
---------------
A job's user-facing sponsorship category is calculated in this order:

1. The current posting explicitly offers sponsorship.
2. The current posting explicitly rejects sponsorship.
3. The current posting contains conflicting evidence.
4. The employer has relevant historical H-1B evidence.
5. No conclusive evidence exists.

Historical employer activity never overrides an explicit restriction in the
current job posting.

Version handling
----------------
A job can have several classifications as the rules improve:

    rules-v2 -> UNKNOWN
    rules-v3 -> UNAVAILABLE

Older versions are deliberately retained for auditing. Public API responses
must use only the newest classification and newest historical match so that
jobs are not duplicated and outdated results are not displayed.
"""

# =============================================================================
# Standard-Library Imports
# =============================================================================

from typing import Annotated, Any


# =============================================================================
# Third-Party Imports
# =============================================================================

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session


# =============================================================================
# Application Imports
# =============================================================================

from app.database.connection import (
    get_database_session,
)
from app.database.models import (
    Company,
    HistoricalSponsorshipEvidence,
    JobPosting,
    SearchQuery,
    SearchResult,
    SponsorshipClassification,
)
from app.database.repository import normalize_text
from app.services.live_search import run_live_search


# =============================================================================
# Application Configuration
# =============================================================================

app = FastAPI(
    title="H-1B Job Intelligence API",
    description=(
        "Search and analyze job postings using explicit sponsorship language "
        "and historical H-1B evidence."
    ),
    version="1.0.0",
)


# =============================================================================
# Browser Access / CORS
# =============================================================================

# During local development, the frontend may run on either:
#
#   localhost:3000  -> common Next.js development address
#   localhost:5173  -> common Vite development address
#
# Browsers consider each host-and-port combination a separate origin. FastAPI
# must explicitly allow these origins before frontend JavaScript can call it.
#
# Production origins must be supplied through environment configuration before
# deployment. We should not use allow_origins=["*"] with credentials enabled.
LOCAL_FRONTEND_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# FastAPI Database Dependency
# =============================================================================

# Every endpoint that declares `database: DatabaseSession` receives a fresh
# SQLAlchemy Session. The dependency closes the session after the request,
# including when the endpoint raises an exception.
DatabaseSession = Annotated[
    Session,
    Depends(get_database_session),
]


# =============================================================================
# Request Schemas
# =============================================================================

class SearchRequest(BaseModel):
    """
    Validate a live job-search request from the frontend.

    `max_pages` is deliberately restricted to three so one browser request
    cannot unexpectedly consume a large portion of the external API quota.

    `force_refresh` bypasses the stored-query cache. It is useful for manual
    refreshes and testing but should normally remain False.
    """

    query: str = Field(
        min_length=2,
        max_length=200,
        description="Arbitrary job-search text supplied by the user.",
    )

    max_pages: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Maximum number of JSearch pages to fetch.",
    )

    force_refresh: bool = Field(
        default=False,
        description="Fetch fresh results even when cached jobs exist.",
    )


# =============================================================================
# Sponsorship Category Logic
# =============================================================================

def determine_category(
    current_policy: str,
    historical_support: bool,
) -> str:
    """
    Convert current and historical evidence into one frontend category.

    Current-posting evidence has higher authority than historical behavior.
    For example, a company may have sponsored workers in FY2025 while the
    current posting explicitly says sponsorship is unavailable. That job must
    be red, not yellow.

    Parameters
    ----------
    current_policy:
        Current-description classifier result such as AVAILABLE, UNAVAILABLE,
        CONFLICTING, or UNKNOWN.

    historical_support:
        Whether employer and occupation matching found relevant certified
        historical H-1B filings.

    Returns
    -------
    str
        The category consumed by the frontend donut chart and job cards.
    """

    if current_policy == "AVAILABLE":
        return "CONFIRMED_AVAILABLE"

    if current_policy == "UNAVAILABLE":
        return "CONFIRMED_UNAVAILABLE"

    if current_policy == "CONFLICTING":
        return "REVIEW"

    if historical_support:
        return "HISTORICALLY_SUPPORTED"

    return "UNKNOWN"


# =============================================================================
# Database Query Construction
# =============================================================================

def build_jobs_statement(
    normalized_query: str | None = None,
):
    """
    Build the SQLAlchemy query used by jobs, search, and dashboard endpoints.

    Why latest-record subqueries are required
    -----------------------------------------
    Classification and historical matching are versioned. A job can therefore
    have multiple stored records:

        Job 123
        ├── rules-v2 -> UNKNOWN
        └── rules-v3 -> UNAVAILABLE

    Joining the classification table directly would return the job once for
    each version. It could therefore duplicate jobs and expose stale results.

    The two subqueries below find the newest timestamp for each job. The main
    query then joins only the record associated with that timestamp.

    Query filtering
    ---------------
    When `normalized_query` is provided, jobs are restricted through the
    search_results many-to-many table:

        search_queries -> search_results -> job_postings

    One search can return many jobs, while one job can appear under many
    searches.
    """

    # -------------------------------------------------------------------------
    # Newest sponsorship classification for every job
    # -------------------------------------------------------------------------

    latest_classification = (
        select(
            SponsorshipClassification.job_id.label(
                "job_id"
            ),
            func.max(
                SponsorshipClassification.classified_at
            ).label(
                "latest_classified_at"
            ),
        )
        .group_by(
            SponsorshipClassification.job_id
        )
        .subquery(
            "latest_classification"
        )
    )

    # -------------------------------------------------------------------------
    # Newest historical match for every job
    # -------------------------------------------------------------------------

    latest_history = (
        select(
            HistoricalSponsorshipEvidence.job_id.label(
                "job_id"
            ),
            func.max(
                HistoricalSponsorshipEvidence.matched_at
            ).label(
                "latest_matched_at"
            ),
        )
        .group_by(
            HistoricalSponsorshipEvidence.job_id
        )
        .subquery(
            "latest_history"
        )
    )

    # -------------------------------------------------------------------------
    # Base job query
    # -------------------------------------------------------------------------

    statement = (
        select(
            JobPosting,
            Company,
            SponsorshipClassification,
            HistoricalSponsorshipEvidence,
        )

        # Keep the job even if employer resolution has not assigned a company.
        .join(
            Company,
            JobPosting.company_id == Company.id,
            isouter=True,
        )

        # Identify the newest available classifier timestamp for this job.
        .join(
            latest_classification,
            latest_classification.c.job_id
            == JobPosting.id,
            isouter=True,
        )

        # Join only the classifier row associated with that newest timestamp.
        .join(
            SponsorshipClassification,
            (
                SponsorshipClassification.job_id
                == JobPosting.id
            )
            & (
                SponsorshipClassification.classified_at
                == latest_classification.c.latest_classified_at
            ),
            isouter=True,
        )

        # Identify the newest historical-match timestamp for this job.
        .join(
            latest_history,
            latest_history.c.job_id
            == JobPosting.id,
            isouter=True,
        )

        # Join only the historical row associated with that newest timestamp.
        .join(
            HistoricalSponsorshipEvidence,
            (
                HistoricalSponsorshipEvidence.job_id
                == JobPosting.id
            )
            & (
                HistoricalSponsorshipEvidence.matched_at
                == latest_history.c.latest_matched_at
            ),
            isouter=True,
        )

        # Expired or deliberately archived jobs should not appear publicly.
        .where(
            JobPosting.is_active.is_(True)
        )
    )

    # -------------------------------------------------------------------------
    # Optional search-query restriction
    # -------------------------------------------------------------------------

    if normalized_query:
        statement = (
            statement
            .join(
                SearchResult,
                SearchResult.job_id == JobPosting.id,
            )
            .join(
                SearchQuery,
                SearchQuery.id
                == SearchResult.search_query_id,
            )
            .where(
                SearchQuery.normalized_query
                == normalized_query
            )
        )

    # Newer postings appear first. Jobs without a known posting date are placed
    # after dated postings instead of being discarded.
    return statement.order_by(
        JobPosting.posted_at.desc().nullslast()
    )


# =============================================================================
# Response Serialization
# =============================================================================

def serialize_job(row: Any) -> dict[str, Any]:
    """
    Convert one SQLAlchemy result row into frontend-ready JSON.

    SQLAlchemy model objects cannot be returned directly because they contain
    database-specific state and values such as UUIDs and datetime objects.
    This function creates an explicit, stable API contract.

    Missing enrichment records are handled safely:

        missing classification -> UNKNOWN
        missing history        -> historical_support=False
    """

    job, company, classification, history = row

    current_policy = (
        classification.policy
        if classification
        else "UNKNOWN"
    )

    historical_support = bool(
        history
        and history.historical_support
    )

    return {
        # Core job identity
        "id": str(job.id),
        "title": job.title,
        "company": (
            company.canonical_name
            if company
            else job.source_company_name
        ),

        # Location and employment metadata
        "city": job.city,
        "state": job.state,
        "country": job.country,
        "employment_type": job.employment_type,
        "posted_at": (
            job.posted_at.isoformat()
            if job.posted_at
            else None
        ),

        # Application destination
        "apply_url": job.apply_url,

        # Current-posting classification
        "current_policy": current_policy,
        "current_policy_evidence": (
            classification.evidence
            if classification
            else []
        ),
        "h1b_transfer_supported": bool(
            classification
            and classification.h1b_transfer_supported
        ),

        # Historical employer/occupation evidence
        "historical_support": historical_support,
        "historical_evidence": (
            history.evidence_payload
            if history
            else None
        ),

        # Final user-facing color/category
        "category": determine_category(
            current_policy=current_policy,
            historical_support=historical_support,
        ),

        # The UI may display an additional review warning when either the
        # current classifier or historical matcher lacks strong confidence.
        "requires_review": bool(
            (
                classification
                and classification.requires_human_review
            )
            or (
                history
                and history.requires_human_review
            )
        ),

        # Versions make displayed evidence traceable during development and
        # quality audits. They are also useful when debugging stale results.
        "classifier_version": (
            classification.classifier_version
            if classification
            else None
        ),
        "historical_matching_version": (
            history.matching_version
            if history
            else None
        ),
    }


# =============================================================================
# Health Endpoint
# =============================================================================

@app.get("/health")
def health() -> dict[str, str]:
    """
    Confirm that the FastAPI process is running.

    This lightweight endpoint intentionally does not query PostgreSQL. A later
    production readiness endpoint can separately verify database connectivity
    and required external dependencies.
    """

    return {
        "status": "healthy",
    }


# =============================================================================
# Jobs Endpoint
# =============================================================================

@app.get("/jobs")
def list_jobs(
    database: DatabaseSession,
    query: str | None = Query(
        default=None,
        description="Return jobs associated with this stored search query.",
    ),
    policy: str | None = Query(
        default=None,
        description="Filter by AVAILABLE, UNAVAILABLE, CONFLICTING, or UNKNOWN.",
    ),
    historical_support: bool | None = Query(
        default=None,
        description="Filter by the presence of historical H-1B evidence.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Maximum number of jobs returned.",
    ),
) -> dict[str, Any]:
    """
    Return stored jobs with optional query and sponsorship filters.

    The search-query restriction is performed in PostgreSQL. The small policy
    and historical filters are currently applied after serialization for code
    clarity. They can be moved into SQL when dataset size requires it.
    """

    normalized_query = (
        normalize_text(query)
        if query
        else None
    )

    rows = database.execute(
        build_jobs_statement(normalized_query)
    ).all()

    jobs = [
        serialize_job(row)
        for row in rows
    ]

    if policy:
        requested_policy = policy.strip().upper()

        jobs = [
            job
            for job in jobs
            if job["current_policy"]
            == requested_policy
        ]

    if historical_support is not None:
        jobs = [
            job
            for job in jobs
            if job["historical_support"]
            is historical_support
        ]

    limited_jobs = jobs[:limit]

    return {
        # `count` represents the number returned after the limit.
        "count": len(limited_jobs),

        # `total_matching` lets the frontend know whether more matching jobs
        # exist beyond the current limit.
        "total_matching": len(jobs),

        "jobs": limited_jobs,
    }


# =============================================================================
# Dashboard Endpoint
# =============================================================================

@app.get("/dashboard")
def dashboard(
    database: DatabaseSession,
    query: str | None = Query(
        default=None,
        description="Calculate the dashboard for one stored search query.",
    ),
) -> dict[str, Any]:
    """
    Calculate donut-chart totals and percentages.

    Every job is assigned to exactly one category through
    `determine_category()`. Current restrictions therefore cannot appear in the
    historical/yellow category even if a historical match exists.
    """

    normalized_query = (
        normalize_text(query)
        if query
        else None
    )

    rows = database.execute(
        build_jobs_statement(normalized_query)
    ).all()

    counts = {
        "CONFIRMED_AVAILABLE": 0,
        "HISTORICALLY_SUPPORTED": 0,
        "CONFIRMED_UNAVAILABLE": 0,
        "UNKNOWN": 0,
        "REVIEW": 0,
    }

    for row in rows:
        serialized_job = serialize_job(row)
        category = serialized_job["category"]
        counts[category] += 1

    total_jobs = sum(counts.values())

    percentages = {
        category: (
            round(
                (count / total_jobs) * 100,
                1,
            )
            if total_jobs
            else 0.0
        )
        for category, count in counts.items()
    }

    return {
        "query": query,
        "total_jobs": total_jobs,
        "counts": counts,
        "percentages": percentages,
    }


# =============================================================================
# Live Search Endpoint
# =============================================================================

@app.post("/search")
def search_jobs(
    request: SearchRequest,
    database: DatabaseSession,
) -> dict[str, Any]:
    """
    Search for arbitrary jobs and return their enriched results.

    Processing flow
    ---------------
    1. Normalize and validate the query.
    2. Return cached results when available and fresh enough.
    3. Otherwise fetch jobs from JSearch.
    4. Normalize and deduplicate jobs.
    5. Classify current sponsorship language.
    6. Match historical employer/occupation evidence.
    7. Upsert jobs and relationships into PostgreSQL.
    8. Read the stored results through the same version-aware query used by
       the other endpoints.

    Returning data from PostgreSQL after writing ensures the frontend sees the
    canonical persisted representation rather than a temporary in-memory form.
    """

    try:
        search_result = run_live_search(
            database=database,
            query=request.query,
            max_pages=request.max_pages,
            force_refresh=request.force_refresh,
        )

        normalized_query = normalize_text(
            request.query
        )

        rows = database.execute(
            build_jobs_statement(normalized_query)
        ).all()

        jobs = [
            serialize_job(row)
            for row in rows
        ]

        return {
            **search_result,
            "count": len(jobs),
            "jobs": jobs,
        }

    except ValueError as error:
        # ValueError represents invalid user input or invalid enrichment data.
        # It is exposed as a client error rather than a server failure.
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except Exception as error:
        # JSearch outages, database problems, and unexpected enrichment errors
        # should not expose full stack traces or secrets to the browser.
        #
        # For production, the original exception should also be written to
        # structured application logs with a request identifier.
        raise HTTPException(
            status_code=502,
            detail=(
                "The job provider or enrichment pipeline failed: "
                f"{error}"
            ),
        ) from error
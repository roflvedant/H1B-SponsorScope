"""Run and cache the API's request-time job-search pipeline.

The live-search service has two execution paths:

1. A recent query already exists in PostgreSQL, so the API immediately returns
   the stored query-job links.
2. The query is missing, expired, or explicitly refreshed, so the service calls
   JSearch and runs normalization, classification, historical matching, and
   database persistence.

The processed DOL dataset is also cached in the FastAPI process. Re-reading and
preparing that large file for every new search created avoidable latency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config.settings import PROCESSED_DIRECTORY, REFERENCE_DIRECTORY
from app.database.models import SearchQuery, SearchResult
from app.database.repository import normalize_text, save_enriched_jobs
from app.enrichment.classification import classify_description
from app.enrichment.matching import (
    find_historical_match,
    load_company_aliases,
    prepare_historical_data,
)
from app.extraction.jsearch import fetch_jobs, save_raw_jobs
from app.pipeline.transformation import deduplicate_jobs, normalize_job


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Repeated queries reuse PostgreSQL results for one day. A caller may bypass
# this policy through the API's `force_refresh` option.
CACHE_HOURS = 24

BROAD_TECH_QUERY_MARKERS = {
    "tech jobs in usa",
    "tech jobs in us",
    "technology jobs in usa",
    "technology jobs in us",
}

TECH_ROLE_QUERIES = (
    "software engineer jobs in United States",
    "data engineer jobs in United States",
    "data analyst jobs in United States",
    "cloud engineer jobs in United States",
)


def expand_search_queries(query: str) -> list[str]:
    """Translate a broad tech search into focused provider queries."""

    normalized = normalize_text(query)
    if normalized in BROAD_TECH_QUERY_MARKERS:
        return list(TECH_ROLE_QUERIES)
    return [query]


# ---------------------------------------------------------------------------
# PostgreSQL query-result cache
# ---------------------------------------------------------------------------

def _as_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC timestamp.

    PostgreSQL normally returns timezone-aware values. This fallback keeps
    SQLite-based tests and older local databases safe if they return a naive
    timestamp.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def query_has_fresh_results(
    database: Session,
    raw_query: str,
    minimum_results: int = 1,
) -> bool:
    """Return True only when a query has recent linked job results."""

    normalized_query = normalize_text(raw_query)
    stored_query = database.scalar(
        select(SearchQuery).where(
            SearchQuery.normalized_query == normalized_query
        )
    )

    if stored_query is None or stored_query.last_fetched_at is None:
        return False

    cache_age = datetime.now(timezone.utc) - _as_utc(
        stored_query.last_fetched_at
    )
    if cache_age > timedelta(hours=CACHE_HOURS):
        return False

    # A SearchQuery row without any SearchResult links cannot satisfy the API,
    # even when its timestamp is recent.
    result_count = database.scalar(
        select(func.count(SearchResult.id)).where(
            SearchResult.search_query_id == stored_query.id
        )
    )
    return bool(result_count and result_count >= minimum_results)


# Preserve the previous public function name for any tests or callers that
# still import it. Its behavior is now correctly freshness-aware.
def query_has_results(database: Session, raw_query: str) -> bool:
    """Compatibility wrapper for the freshness-aware cache check."""

    return query_has_fresh_results(database, raw_query)


# ---------------------------------------------------------------------------
# In-process historical-reference cache
# ---------------------------------------------------------------------------

def _modified_at_ns(path) -> int:
    """Return a stable file-version value, or zero when a file is absent."""

    return path.stat().st_mtime_ns if path.exists() else 0


@lru_cache(maxsize=2)
def _load_historical_data_cached(
    history_path: str,
    history_modified_at_ns: int,
    aliases_modified_at_ns: int,
):
    """Read and prepare historical evidence once per source-file version.

    Modification timestamps are part of the cache key. Updating either the DOL
    CSV or verified alias CSV automatically invalidates the cached preparation
    on the next request.
    """

    # These values participate in the `lru_cache` key. Deleting the local names
    # clarifies that their purpose is invalidation rather than business logic.
    del history_modified_at_ns, aliases_modified_at_ns

    history = pd.read_csv(
        history_path,
        dtype={"SOC_CODE": str},
    )
    aliases = load_company_aliases()
    prepared_history = prepare_historical_data(
        history=history,
        aliases=aliases,
    )
    return prepared_history, aliases


def load_historical_data():
    """Return prepared DOL evidence while avoiding repeated CSV processing."""

    history_file = PROCESSED_DIRECTORY / "dol_h1b_history_2025.csv"
    if not history_file.exists():
        return None, {}

    alias_file = REFERENCE_DIRECTORY / "company_aliases.csv"
    return _load_historical_data_cached(
        str(history_file.resolve()),
        _modified_at_ns(history_file),
        _modified_at_ns(alias_file),
    )


# ---------------------------------------------------------------------------
# Live-search pipeline
# ---------------------------------------------------------------------------

def run_live_search(
    database: Session,
    query: str,
    max_pages: int = 1,
    force_refresh: bool = False,
) -> dict:
    """Run a cached or fresh job search and persist its complete provenance."""

    clean_query = " ".join(query.split())
    if not clean_query:
        raise ValueError("Search query cannot be empty.")

    # The API endpoint reads the linked jobs after this function returns, so a
    # cache hit needs no provider call or enrichment work here.
    if (
        not force_refresh
        and query_has_fresh_results(
            database,
            clean_query,
            minimum_results=12 if max_pages > 1 else 1,
        )
    ):
        return {
            "query": clean_query,
            "source": "CACHE",
            "jobs_saved": 0,
        }

    # Fetch and retain the provider response before performing transformations.
    # This raw snapshot makes pipeline results reproducible and debuggable.
    provider_queries = expand_search_queries(clean_query)
    provider_pages = 1 if len(provider_queries) > 1 else max_pages
    payload = fetch_jobs(
        queries=provider_queries,
        max_pages=provider_pages,
    )
    raw_file = save_raw_jobs(payload)

    raw_jobs = payload["data"]["jobs"]
    normalized_jobs = [normalize_job(job) for job in raw_jobs]
    jobs = deduplicate_jobs(normalized_jobs)

    history, aliases = load_historical_data()

    for job in jobs:
        job.update(classify_description(job.get("description", "")))

        # Historical evidence cannot change an explicit current restriction,
        # so skip the most expensive matcher for unavailable postings.
        if job.get("current_policy") == "UNAVAILABLE":
            job.update({"historical_support": False, "historical_evidence": None})
            job["search_queries"] = [clean_query]
            continue

        if history is None:
            job.update(
                {
                    "historical_support": False,
                    "historical_evidence": None,
                }
            )
        else:
            # Live and batch ingestion deliberately share the same versioned
            # matcher so an identical posting cannot receive different labels.
            job.update(
                find_historical_match(
                    job=job,
                    history=history,
                    aliases=aliases,
                )
            )

        # Query provenance powers cached retrieval through SearchResult links.
        job["search_queries"] = [clean_query]

    # -----------------------------------------------------------------------
    # Replace the query's previous result snapshot
    # -----------------------------------------------------------------------
    #
    # JobPosting records remain available for historical analysis, but the
    # SearchResult links for this query should describe only the latest fetch.
    # Otherwise every refresh grows the dashboard from 30 to 45, 60, and so on.
    normalized_query = normalize_text(clean_query)
    stored_query = database.scalar(
        select(SearchQuery).where(
            SearchQuery.normalized_query == normalized_query
        )
    )

    if stored_query is not None:
        database.execute(
            delete(SearchResult).where(
                SearchResult.search_query_id == stored_query.id
            )
        )
        database.flush()

    # `save_enriched_jobs` recreates links for the current result set while
    # deduplicating the underlying JobPosting records.
    result = save_enriched_jobs(database, jobs)

    stored_query = database.scalar(
        select(SearchQuery).where(
            SearchQuery.normalized_query == normalized_query
        )
    )
    if stored_query is not None:
        stored_query.last_fetched_at = datetime.now(timezone.utc)
        database.commit()

    return {
        "query": clean_query,
        "source": "JSEARCH",
        "provider_queries": provider_queries,
        "received": len(raw_jobs),
        "jobs_saved": result["saved_jobs"],
        "query_job_links": result["created_links"],
        "raw_snapshot": str(raw_file),
    }

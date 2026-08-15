"""Transform raw JSearch records into the application's stable job schema.

This stage separates provider-specific field names from the rest of the app,
adds explainable title relevance, deduplicates postings, and writes a processed
snapshot that downstream enrichment can consume without another API request.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import (
    PROCESSED_DIRECTORY,
    RAW_JSEARCH_DIRECTORY,
    create_data_directories,
)
from app.pipeline.relevance import evaluate_job_relevance


# ---------------------------------------------------------------------------
# Provider-to-application normalization
# ---------------------------------------------------------------------------

def normalize_job(raw_job: dict[str, Any]) -> dict[str, Any]:
    """Convert one JSearch record into the application's stable job schema.

    Missing optional provider fields become ``None`` or an empty string. The
    relevance decision is retained for auditing; filtering is intentionally a
    separate choice so unsupported results are not silently discarded here.
    """

    relevant, relevance_reason = evaluate_job_relevance(
        raw_job.get("job_title")
    )

    search_query = (
        raw_job.get("_search_query")
        or "data engineer jobs in United States"
    )

    return {
        "source": "jsearch",
        "source_job_id": (
            raw_job.get("job_uid") or raw_job.get("job_id")
        ),
        "title": raw_job.get("job_title") or "",
        "company": raw_job.get("employer_name") or "",
        "company_website": raw_job.get("employer_website"),
        "location": raw_job.get("job_location"),
        "city": raw_job.get("job_city"),
        "state": raw_job.get("job_state"),
        "country": raw_job.get("job_country"),
        "is_remote": bool(raw_job.get("job_is_remote")),
        "employment_type": raw_job.get("job_employment_type"),
        "posted_at": raw_job.get("job_posted_at_datetime_utc"),
        "description": raw_job.get("job_description") or "",
        "apply_url": raw_job.get("job_apply_link"),
        "publisher": raw_job.get("job_publisher"),
        "salary_min": raw_job.get("job_min_salary"),
        "salary_max": raw_job.get("job_max_salary"),
        "salary_period": raw_job.get("job_salary_period"),
        "search_queries": [str(search_query)],
        # Preserve the explainable relevance result instead of calculating and
        # then discarding it, as the previous implementation did.
        "is_relevant": relevant,
        "relevance_reason": relevance_reason,
    }


# ---------------------------------------------------------------------------
# Deterministic deduplication
# ---------------------------------------------------------------------------

def deduplication_key(job: dict[str, Any]) -> str:
    """Return a stable identity key for one normalized posting.

    Provider IDs are preferred. If the provider omits an ID, a SHA-256 digest
    of identifying fields gives the same fallback key across repeated runs.
    """

    if job.get("source_job_id"):
        return f"jsearch:{job['source_job_id']}"

    identifying_text = "|".join(
        str(job.get(field) or "").strip().lower()
        for field in ("company", "title", "location", "apply_url")
    )
    return hashlib.sha256(
        identifying_text.encode("utf-8")
    ).hexdigest()


def deduplicate_jobs(
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove duplicate postings while preserving every discovery query."""

    unique_jobs: dict[str, dict[str, Any]] = {}

    for job in jobs:
        key = deduplication_key(job)

        if key not in unique_jobs:
            unique_jobs[key] = job
            continue

        # A posting may appear under several searches. Retaining all query
        # values lets PostgreSQL link that one job to every relevant search.
        known_queries = set(unique_jobs[key]["search_queries"])
        known_queries.update(job["search_queries"])
        unique_jobs[key]["search_queries"] = sorted(known_queries)

    return list(unique_jobs.values())


# ---------------------------------------------------------------------------
# Raw snapshot loading
# ---------------------------------------------------------------------------

def load_latest_raw_jobs() -> tuple[list[dict[str, Any]], Path]:
    """Load jobs from the most recently modified raw JSearch snapshot."""

    raw_files = list(RAW_JSEARCH_DIRECTORY.glob("jobs_*.json"))
    if not raw_files:
        raise FileNotFoundError("No raw JSearch file was found.")

    latest_file = max(
        raw_files,
        key=lambda file: file.stat().st_mtime,
    )
    with latest_file.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    jobs = payload.get("data", {}).get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Raw JSearch data does not contain data.jobs.")

    return jobs, latest_file


# ---------------------------------------------------------------------------
# Batch transformation entry point
# ---------------------------------------------------------------------------

def run_transformation() -> Path:
    """Normalize and deduplicate the newest raw snapshot, then save it."""

    create_data_directories()
    raw_jobs, source_file = load_latest_raw_jobs()

    normalized_jobs = [normalize_job(job) for job in raw_jobs]
    unique_jobs = deduplicate_jobs(normalized_jobs)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = (
        PROCESSED_DIRECTORY / f"normalized_jobs_{timestamp}.json"
    )
    with output_file.open("w", encoding="utf-8") as file:
        json.dump(unique_jobs, file, indent=2)

    relevant_count = sum(
        bool(job.get("is_relevant")) for job in unique_jobs
    )

    print("Reading raw data from:", source_file)
    print("Raw jobs:", len(raw_jobs))
    print("Structurally valid jobs:", len(normalized_jobs))
    print("Jobs after deduplication:", len(unique_jobs))
    print("Jobs matching V1 title scope:", relevant_count)
    print("Normalized data saved to:", output_file)

    return output_file
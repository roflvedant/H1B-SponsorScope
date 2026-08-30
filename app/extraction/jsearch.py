"""Fetch job postings from JSearch and preserve raw API snapshots.

This module is the extraction layer of the pipeline. Its responsibilities are
deliberately limited to requesting jobs, validating the provider response,
recording ingestion metadata, and saving the untouched response to disk.
Normalization, deduplication, and sponsorship analysis happen later.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    import boto3
except ImportError:  # pragma: no cover - optional outside AWS
    boto3 = None

from app.config.settings import (
    DEFAULT_SEARCH_QUERIES,
    JSEARCH_API_KEY,
    JSEARCH_URL,
    RAW_JSEARCH_DIRECTORY,
    RAW_SNAPSHOT_BUCKET,
    create_data_directories,
    validate_settings,
)


# ---------------------------------------------------------------------------
# Request configuration
# ---------------------------------------------------------------------------

# These status codes usually represent temporary rate limits or provider-side
# failures. Retrying them is reasonable; permanent client errors such as 401
# and 403 should fail immediately through ``raise_for_status``.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Keep provider calls bounded so a stalled external API cannot block the
# application indefinitely.
REQUEST_TIMEOUT_SECONDS = 25
DEFAULT_MAX_ATTEMPTS = 2


# ---------------------------------------------------------------------------
# Single-page requests
# ---------------------------------------------------------------------------

def request_page(
    parameters: dict[str, Any],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Request and validate one page of JSearch results.

    Temporary network/provider failures use exponential backoff: one second
    before the second attempt, then two seconds before the third. The final
    exception is allowed to propagate so the API can return a useful error
    instead of silently treating a failed request as an empty result.
    """

    headers = {"x-api-key": JSEARCH_API_KEY}

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(
                JSEARCH_URL,
                headers=headers,
                params=parameters,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            # Convert retryable HTTP responses into exceptions so they follow
            # the same retry path as timeouts and connection failures.
            if response.status_code in RETRYABLE_STATUS_CODES:
                raise requests.HTTPError(
                    f"Temporary JSearch error: {response.status_code}",
                    response=response,
                )

            response.raise_for_status()
            payload = response.json()

            # Validate the minimum response shape needed downstream. This
            # prevents a provider error object from reaching normalization as
            # though it were a successful jobs response.
            if not isinstance(payload, dict):
                raise ValueError("JSearch response must be a JSON object.")

            if not isinstance(payload.get("data"), dict):
                raise ValueError(
                    "JSearch response is missing the data object."
                )

            if not isinstance(payload["data"].get("jobs"), list):
                raise ValueError(
                    "JSearch response is missing the jobs list."
                )

            return payload

        except (requests.RequestException, ValueError) as error:
            if attempt == max_attempts:
                raise

            wait_seconds = 2 ** (attempt - 1)
            print(
                f"Request failed ({error}). "
                f"Retrying in {wait_seconds} seconds..."
            )
            time.sleep(wait_seconds)

    # The loop always returns or raises. This defensive line mainly helps type
    # checkers understand that the function cannot fall through silently.
    raise RuntimeError("JSearch request ended without a response.")


# ---------------------------------------------------------------------------
# Cursor pagination
# ---------------------------------------------------------------------------

def fetch_query(
    query: str,
    max_pages: int = 3,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch up to ``max_pages`` of cursor-paginated jobs for one query.

    Each raw job receives ``_search_query`` so query provenance survives later
    normalization and can be represented by ``search_results`` in PostgreSQL.
    Pagination stops early when the provider returns no next cursor.
    """

    jobs: list[dict[str, Any]] = []
    cursor: str | None = None
    pages_fetched = 0

    for page_number in range(1, max_pages + 1):
        parameters: dict[str, Any] = {
            "query": query,
            "country": "us",
            "language": "en",
        }

        if cursor:
            parameters["cursor"] = cursor

        print(f"Requesting page {page_number} for: {query}")
        payload = request_page(parameters)
        page_data = payload["data"]
        page_jobs = page_data["jobs"]

        for job in page_jobs:
            job["_search_query"] = query

        jobs.extend(page_jobs)
        pages_fetched += 1
        print(f"Received {len(page_jobs)} jobs")

        cursor_value = page_data.get("cursor")
        cursor = str(cursor_value) if cursor_value else None
        if not cursor:
            break

    return jobs, pages_fetched


# ---------------------------------------------------------------------------
# Multi-query ingestion
# ---------------------------------------------------------------------------

def fetch_jobs(
    queries: list[str] | None = None,
    max_pages: int = 3,
) -> dict[str, Any]:
    """Fetch configured searches and return jobs with ingestion metadata."""

    # Validate the API key immediately, before doing any network work.
    validate_settings()

    selected_queries = queries or DEFAULT_SEARCH_QUERIES
    all_jobs: list[dict[str, Any]] = []
    total_pages = 0

    for query in selected_queries:
        query_jobs, pages_fetched = fetch_query(
            query,
            max_pages=max_pages,
        )
        all_jobs.extend(query_jobs)
        total_pages += pages_fetched

    return {
        "metadata": {
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "queries": selected_queries,
            "pages_fetched": total_pages,
            "jobs_received": len(all_jobs),
        },
        "data": {"jobs": all_jobs},
    }


# ---------------------------------------------------------------------------
# Raw snapshot persistence
# ---------------------------------------------------------------------------

def save_raw_jobs(payload: dict[str, Any]) -> Path:
    """Save an immutable raw snapshot and return its filesystem path.

    Raw responses allow transformation and enrichment to be rerun without
    spending API quota or losing the exact provider input used by a pipeline
    run. Timestamped filenames also prevent one ingestion from overwriting
    another.
    """

    create_data_directories()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = RAW_JSEARCH_DIRECTORY / f"jobs_{timestamp}.json"

    with output_file.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)

    if RAW_SNAPSHOT_BUCKET:
        if boto3 is None:
            raise RuntimeError(
                "RAW_SNAPSHOT_BUCKET is configured but boto3 is unavailable."
            )
        boto3.client("s3").upload_file(
            str(output_file),
            RAW_SNAPSHOT_BUCKET,
            f"jsearch/{output_file.name}",
        )

    return output_file


# ---------------------------------------------------------------------------
# Command-line pipeline entry point
# ---------------------------------------------------------------------------

def run_ingestion(
    queries: list[str] | None = None,
    max_pages: int = 3,
) -> Path:
    """Fetch jobs, save the raw snapshot, print a summary, and return it."""

    payload = fetch_jobs(
        queries=queries,
        max_pages=max_pages,
    )
    output_file = save_raw_jobs(payload)

    print("Total jobs received:", payload["metadata"]["jobs_received"])
    print("Raw data saved to:", output_file)

    return output_file

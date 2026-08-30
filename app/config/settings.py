"""Central configuration for SponsorScope.

This module loads environment variables and defines the filesystem paths used
by ingestion, transformation, enrichment, database access, and deployment.

Secrets are read from environment variables and must never be hard-coded or
committed to Git.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Project root and environment loading
# ---------------------------------------------------------------------------

# settings.py lives inside:
#
#     <project-root>/app/config/settings.py
#
# Moving two parent directories upward therefore resolves the project root.
# Anchoring paths here prevents commands from behaving differently depending
# on the directory from which Python was started.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load local development variables from <project-root>/.env.
#
# load_dotenv() does not overwrite variables already supplied by a production
# platform such as Render, so hosted values take priority automatically.
load_dotenv(PROJECT_ROOT / ".env")


# ---------------------------------------------------------------------------
# JSearch configuration
# ---------------------------------------------------------------------------

# The endpoint can be overridden for testing or future provider changes.
JSEARCH_URL = os.getenv(
    "JSEARCH_URL",
    "https://api.openwebninja.com/jsearch/search-v2",
)

# The API key has no default because committing a real credential would expose
# the account. validate_settings() checks it before an API request is made.
JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY")

RAW_SNAPSHOT_BUCKET = os.getenv("RAW_SNAPSHOT_BUCKET", "").strip()


# ---------------------------------------------------------------------------
# PostgreSQL configuration
# ---------------------------------------------------------------------------

# This fallback connects to the PostgreSQL container exposed by the local
# docker-compose.yml file.
LOCAL_DATABASE_URL = (
    "postgresql+psycopg://"
    "h1b_user:h1b_password@localhost:5432/h1b_jobs"
)


def normalize_database_url(database_url: str) -> str:
    """Convert hosted PostgreSQL URLs to SQLAlchemy's Psycopg 3 format.

    Hosting providers commonly supply connection strings beginning with
    ``postgres://`` or ``postgresql://``. Explicitly using the
    ``postgresql+psycopg`` dialect ensures SQLAlchemy selects the installed
    Psycopg 3 driver.

    URLs that already specify a SQLAlchemy driver are returned unchanged.
    """

    if database_url.startswith("postgres://"):
        return database_url.replace(
            "postgres://",
            "postgresql+psycopg://",
            1,
        )

    if database_url.startswith("postgresql://"):
        return database_url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    return database_url


DATABASE_URL = normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        LOCAL_DATABASE_URL,
    )
)


# ---------------------------------------------------------------------------
# Browser and CORS configuration
# ---------------------------------------------------------------------------

# These origins allow the local Next.js frontend to call FastAPI during
# development.
LOCAL_FRONTEND_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Production origins are supplied as a comma-separated environment variable.
#
# Example:
#
# CORS_ALLOWED_ORIGINS=https://h1b-sponsorscope.vercel.app
#
# More than one deployed frontend can be configured:
#
# CORS_ALLOWED_ORIGINS=https://site-one.com,https://site-two.com
DEPLOYED_FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "",
    ).split(",")
    if origin.strip()
]

# dict.fromkeys removes duplicates while preserving the original order.
CORS_ALLOWED_ORIGINS = list(
    dict.fromkeys(
        LOCAL_FRONTEND_ORIGINS
        + DEPLOYED_FRONTEND_ORIGINS
    )
)


# ---------------------------------------------------------------------------
# Pipeline data directories
# ---------------------------------------------------------------------------

# DATA_DIRECTORY can be overridden during deployment. When it is omitted, all
# pipeline files are stored under <project-root>/data.
DATA_DIRECTORY = Path(
    os.getenv(
        "DATA_DIRECTORY",
        str(PROJECT_ROOT / "data"),
    )
)

# Raw snapshots preserve the original provider responses and DOL workbooks.
RAW_JSEARCH_DIRECTORY = DATA_DIRECTORY / "raw" / "jsearch"
RAW_DOL_DIRECTORY = DATA_DIRECTORY / "raw" / "dol"

# Processed data contains normalized jobs and aggregated historical records.
PROCESSED_DIRECTORY = DATA_DIRECTORY / "processed"

# Enriched data contains sponsorship classifications and historical matches.
ENRICHED_DIRECTORY = DATA_DIRECTORY / "enriched"

# Reference data contains version-controlled inputs such as verified employer
# aliases.
REFERENCE_DIRECTORY = DATA_DIRECTORY / "references"

# Review data contains uncertain candidates intended for human inspection.
REVIEW_DIRECTORY = DATA_DIRECTORY / "review"


# ---------------------------------------------------------------------------
# Default batch-ingestion workload
# ---------------------------------------------------------------------------

# Keep the default workload within the external API quota. Additional searches
# can be supplied through fetch_main.py without changing this configuration.
DEFAULT_SEARCH_QUERIES = [
    "data engineer jobs in United States",
]


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------

def validate_settings() -> None:
    """Fail before ingestion when the required JSearch key is missing.

    Database-only commands do not require JSearch, so this validation is called
    by the extraction layer rather than immediately when settings are imported.
    """

    if not JSEARCH_API_KEY:
        raise ValueError(
            "JSEARCH_API_KEY is missing. "
            "Add it to the project .env file or deployment environment."
        )


# ---------------------------------------------------------------------------
# Directory initialization
# ---------------------------------------------------------------------------

def create_data_directories() -> None:
    """Create every directory that the data pipeline may write to.

    ``exist_ok=True`` makes this operation safe to run repeatedly. Existing
    directories and their contents are preserved.
    """

    for directory in (
        RAW_JSEARCH_DIRECTORY,
        RAW_DOL_DIRECTORY,
        PROCESSED_DIRECTORY,
        ENRICHED_DIRECTORY,
        REFERENCE_DIRECTORY,
        REVIEW_DIRECTORY,
    ):
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

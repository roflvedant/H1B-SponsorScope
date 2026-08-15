"""Central application configuration and filesystem locations.

Local development values are loaded from ``.env``. Production deployments
provide the same values through the hosting platform's environment settings,
which keeps API keys and database credentials out of source control.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------

# ``load_dotenv`` is convenient locally and does not override variables already
# supplied by Docker, Render, or another production environment.
load_dotenv()


# ---------------------------------------------------------------------------
# External service configuration
# ---------------------------------------------------------------------------

JSEARCH_URL = os.getenv(
    "JSEARCH_URL",
    "https://api.openwebninja.com/jsearch/search-v2",
)
JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY")


# ---------------------------------------------------------------------------
# Database configuration
# ---------------------------------------------------------------------------

# The fallback connects to the PostgreSQL container exposed by the local Docker
# Compose setup. Production must provide its managed PostgreSQL connection as
# ``DATABASE_URL`` through the hosting platform—not through a committed file.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    (
        "postgresql+psycopg://"
        "h1b_user:h1b_password@localhost:5432/h1b_jobs"
    ),
)


# ---------------------------------------------------------------------------
# Project and data directories
# ---------------------------------------------------------------------------

# Resolve data paths from the repository root instead of the current working
# directory. Commands therefore behave consistently when started by VS Code,
# Docker, a test runner, or a cloud process manager.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = Path(
    os.getenv("DATA_DIRECTORY", str(PROJECT_ROOT / "data"))
)

RAW_JSEARCH_DIRECTORY = DATA_DIRECTORY / "raw" / "jsearch"
RAW_DOL_DIRECTORY = DATA_DIRECTORY / "raw" / "dol"
PROCESSED_DIRECTORY = DATA_DIRECTORY / "processed"
ENRICHED_DIRECTORY = DATA_DIRECTORY / "enriched"
REFERENCE_DIRECTORY = DATA_DIRECTORY / "references"
REVIEW_DIRECTORY = DATA_DIRECTORY / "review"


# ---------------------------------------------------------------------------
# Default batch workload
# ---------------------------------------------------------------------------

# Keep the default fetch small enough for the provider quota. Additional role
# families can be introduced through scheduled ingestion after V1.
DEFAULT_SEARCH_QUERIES = [
    "data engineer jobs in United States",
]


# ---------------------------------------------------------------------------
# Validation and directory initialization
# ---------------------------------------------------------------------------

def validate_settings() -> None:
    """Fail before ingestion when a required provider credential is missing."""

    if not JSEARCH_API_KEY:
        raise ValueError(
            "JSEARCH_API_KEY is missing. Add it to the project .env file."
        )


def create_data_directories() -> None:
    """Create every directory written by ingestion and enrichment stages."""

    for directory in (
        RAW_JSEARCH_DIRECTORY,
        RAW_DOL_DIRECTORY,
        PROCESSED_DIRECTORY,
        ENRICHED_DIRECTORY,
        REFERENCE_DIRECTORY,
        REVIEW_DIRECTORY,
    ):
        directory.mkdir(parents=True, exist_ok=True)

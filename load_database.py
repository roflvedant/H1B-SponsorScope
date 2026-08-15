"""Load the newest fully enriched job snapshot into PostgreSQL.

The repository layer performs idempotent inserts and updates, so rerunning this
command updates matching records rather than creating duplicate jobs. This
script does not fetch or enrich data; run ``main.py`` first when a new final
snapshot is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config.settings import ENRICHED_DIRECTORY
from app.database.connection import SessionLocal
from app.database.repository import save_enriched_jobs


# ---------------------------------------------------------------------------
# Snapshot discovery and validation
# ---------------------------------------------------------------------------

def find_latest_enriched_file() -> Path:
    """Return the newest final enrichment snapshot on disk."""

    files = list(ENRICHED_DIRECTORY.glob("final_jobs_*.json"))
    if not files:
        raise FileNotFoundError(
            "No final_jobs JSON file was found. Run main.py first."
        )

    return max(
        files,
        key=lambda path: path.stat().st_mtime,
    )


def load_jobs(source_file: Path) -> list[dict[str, Any]]:
    """Read and minimally validate the final job snapshot."""

    with source_file.open("r", encoding="utf-8") as file:
        jobs = json.load(file)

    if not isinstance(jobs, list):
        raise ValueError(
            "The final jobs snapshot must contain a JSON list."
        )

    if not all(isinstance(job, dict) for job in jobs):
        raise ValueError(
            "Every item in the final jobs snapshot must be an object."
        )

    return jobs


# ---------------------------------------------------------------------------
# Program entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Load the newest final snapshot through the database repository."""

    latest_file = find_latest_enriched_file()
    jobs = load_jobs(latest_file)

    # The context manager always closes the SQLAlchemy session. Transaction
    # commit and rollback behavior remains centralized in save_enriched_jobs.
    with SessionLocal() as database:
        result = save_enriched_jobs(database, jobs)

    print("Source:", latest_file)
    print("Jobs saved:", result["saved_jobs"])
    print("Query-job links created:", result["created_links"])


if __name__ == "__main__":
    main()
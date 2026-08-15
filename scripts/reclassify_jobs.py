"""
Reclassify every stored job using the current sponsorship classifier.

Purpose
-------
The normal ingestion pipeline classifies only jobs in the current fetched
batch. When the sponsorship rules are upgraded, older PostgreSQL records retain
their earlier classifier versions unless we explicitly process them again.

This maintenance script:

1. Reads every stored job description from PostgreSQL.
2. Runs the current classifier against each description.
3. Inserts or updates the current classifier-version record.
4. Preserves earlier versions for auditing.
5. Commits work in batches so one large transaction is avoided.

Example version history
-----------------------
After running this script, one job may have:

    rules-v2 -> UNKNOWN
    rules-v3 -> UNAVAILABLE

Both records remain stored. The API selects only the newest record for public
results, while the older version remains available for accuracy analysis.

This script does not:
---------------------
- fetch new jobs;
- change query-job relationships;
- change historical H-1B evidence;
- delete earlier classifications;
- modify raw JSON snapshots.
"""

# =============================================================================
# Standard-Library Imports
# =============================================================================

import argparse
from collections import Counter


# =============================================================================
# Third-Party Imports
# =============================================================================

from sqlalchemy import select


# =============================================================================
# Application Imports
# =============================================================================

from app.database.connection import SessionLocal
from app.database.models import JobPosting
from app.database.repository import save_classification
from app.enrichment.classification import classify_description
from app.enrichment.sponsorship_rules import CLASSIFIER_VERSION


# =============================================================================
# Configuration
# =============================================================================

# Committing periodically prevents every classification from remaining in one
# very large transaction. The current database is small, but retaining this
# pattern makes the script safer as the number of jobs grows.
DEFAULT_BATCH_SIZE = 100


# =============================================================================
# Reclassification Logic
# =============================================================================

def reclassify_all_jobs(
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    """
    Run the current classifier against every job stored in PostgreSQL.

    Parameters
    ----------
    batch_size:
        Number of processed jobs between database commits. The value must be
        positive.

    Returns
    -------
    dict[str, int]
        Summary containing the number of processed jobs and policy counts.

    Transaction behavior
    --------------------
    `save_classification()` performs an upsert using:

        job_id + classifier_version

    Therefore:

    - the first run creates one rules-v3 record per job;
    - a repeated run updates the existing rules-v3 records;
    - repeated runs do not create duplicates;
    - rules-v2 records remain untouched.
    """

    if batch_size < 1:
        raise ValueError(
            "batch_size must be at least 1."
        )

    policy_counts: Counter[str] = Counter()
    processed_count = 0

    with SessionLocal() as database:
        # Stream jobs in a stable order. A stable order makes progress output
        # predictable and simplifies investigation if a particular job fails.
        statement = (
            select(JobPosting)
            .order_by(JobPosting.id)
        )

        jobs = database.scalars(statement).all()

        try:
            for job in jobs:
                # Empty descriptions remain valid records, but the classifier
                # should correctly return UNKNOWN because no explicit evidence
                # can be extracted.
                classification_data = classify_description(
                    job.description or ""
                )

                # Reuse the repository's classification upsert logic instead
                # of duplicating database-write behavior inside this script.
                save_classification(
                    database=database,
                    job=job,
                    data=classification_data,
                )

                policy = classification_data[
                    "current_policy"
                ]
                policy_counts[policy] += 1
                processed_count += 1

                # Flush and commit completed batches. If a later batch fails,
                # the successfully committed earlier work remains available.
                if processed_count % batch_size == 0:
                    database.commit()

                    print(
                        "Processed jobs:",
                        processed_count,
                    )

            # Commit the final partial batch, if one exists.
            database.commit()

        except Exception:
            # Roll back only the currently uncommitted batch. Earlier committed
            # batches remain intact.
            database.rollback()
            raise

    return {
        "processed_jobs": processed_count,
        **dict(policy_counts),
    }


# =============================================================================
# Command-Line Interface
# =============================================================================

def parse_arguments() -> argparse.Namespace:
    """Read optional maintenance-script settings."""

    parser = argparse.ArgumentParser(
        description=(
            "Reclassify every PostgreSQL job using "
            "the current sponsorship rules."
        )
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            "Number of jobs committed per transaction. "
            f"Default: {DEFAULT_BATCH_SIZE}"
        ),
    )

    return parser.parse_args()


# =============================================================================
# Script Entry Point
# =============================================================================

def main() -> None:
    """Run the complete database reclassification."""

    arguments = parse_arguments()

    print(
        "Current classifier version:",
        CLASSIFIER_VERSION,
    )
    print(
        "Starting complete database reclassification..."
    )

    summary = reclassify_all_jobs(
        batch_size=arguments.batch_size,
    )

    print("\nReclassification complete")
    print("=========================")

    for key, value in summary.items():
        print(
            f"{key}: {value}"
        )


if __name__ == "__main__":
    main()
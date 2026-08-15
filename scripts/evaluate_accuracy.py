"""
Evaluate the sponsorship classifier against manually reviewed job postings.

Workflow
--------
1. Export database jobs into a CSV:

   python -m scripts.evaluate_accuracy export

2. Manually complete the human-label columns in:

   data/evaluation/sponsorship_labels.csv

3. Calculate accuracy metrics:

   python -m scripts.evaluate_accuracy evaluate

Why manual labels?
------------------
The classifier cannot evaluate itself. We need a human-reviewed "correct answer"
for each description before precision, recall, and errors can be measured.
"""

# =============================================================================
# Imports
# =============================================================================

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.connection import SessionLocal
from app.database.models import (
    Company,
    JobPosting,
    SponsorshipClassification,
)

from app.enrichment.classification import classify_description
from app.enrichment.sponsorship_rules import CLASSIFIER_VERSION


# =============================================================================
# Configuration
# =============================================================================

LABEL_FILE = Path(
    "data/evaluation/sponsorship_labels.csv"
)

VALID_POLICIES = {
    "AVAILABLE",
    "UNAVAILABLE",
    "CONFLICTING",
    "UNKNOWN",
}

CSV_COLUMNS = [
    # Identifiers and job information
    "job_id",
    "source_job_id",
    "company",
    "title",
    "description",

    # Current automated prediction
    "classifier_policy",
    "classifier_version",
    "classifier_evidence",
    "classifier_h1b_transfer_supported",

    # Human-reviewed answer
    "expected_policy",
    "expected_h1b_transfer_supported",
    "label_reason",
    "reviewed_by",
    "reviewed_at",
]


# =============================================================================
# General Helpers
# =============================================================================

def normalize_policy(value: str | None) -> str:
    """Normalize policy labels for reliable comparisons."""

    return str(value or "").strip().upper()


def normalize_boolean(value: str | bool | None) -> bool | None:
    """
    Convert common CSV boolean values into True, False, or None.

    None means that the reviewer has not supplied a valid answer.
    """

    normalized = str(value or "").strip().lower()

    if normalized in {"true", "yes", "1", "y"}:
        return True

    if normalized in {"false", "no", "0", "n"}:
        return False

    return None


def format_evidence(
    evidence: list[dict[str, Any]] | None,
) -> str:
    """Convert structured evidence into readable text for CSV review."""

    if not evidence:
        return ""

    sentences = []

    for item in evidence:
        sentence = str(item.get("sentence") or "").strip()

        if sentence and sentence not in sentences:
            sentences.append(sentence)

    return " || ".join(sentences)


# =============================================================================
# Existing Label Preservation
# =============================================================================

def load_existing_labels(
    label_file: Path = LABEL_FILE,
) -> dict[str, dict[str, str]]:
    """
    Load existing CSV rows by job ID.

    This prevents completed human labels from being erased when newly fetched
    jobs are exported later.
    """

    if not label_file.exists():
        return {}

    with label_file.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        reader = csv.DictReader(csv_file)

        return {
            row["job_id"]: row
            for row in reader
            if row.get("job_id")
        }


def preserve_human_fields(
    new_row: dict[str, str],
    existing_row: dict[str, str] | None,
) -> dict[str, str]:
    """Copy manually entered fields from an earlier CSV row."""

    if not existing_row:
        return new_row

    human_fields = [
        "expected_policy",
        "expected_h1b_transfer_supported",
        "label_reason",
        "reviewed_by",
        "reviewed_at",
    ]

    for field in human_fields:
        new_row[field] = existing_row.get(field, "")

    return new_row


# =============================================================================
# Database Export
# =============================================================================

def load_database_rows(
    database: Session,
) -> list[dict[str, str]]:
    """
    Export one row for each job/classifier-version combination.

    The newest classification is selected for each job. This prevents one job
    from appearing several times after the classifier is upgraded.
    """

    statement = (
        select(
            JobPosting,
            Company,
            SponsorshipClassification,
        )
        .join(
            Company,
            JobPosting.company_id == Company.id,
            isouter=True,
        )
        .join(
            SponsorshipClassification,
            SponsorshipClassification.job_id == JobPosting.id,
            isouter=True,
        )
        .order_by(
            JobPosting.id,
            SponsorshipClassification.classified_at.desc(),
        )
    )

    rows = database.execute(statement).all()
    exported_jobs = []
    seen_job_ids = set()

    for job, company, classification in rows:
        job_id = str(job.id)

        # Because classifications are ordered newest-first, keep the first
        # classification encountered for each job.
        if job_id in seen_job_ids:
            continue

        seen_job_ids.add(job_id)

        exported_jobs.append(
            {
                "job_id": job_id,
                "source_job_id": job.source_job_id,
                "company": (
                    company.canonical_name
                    if company
                    else job.source_company_name
                ),
                "title": job.title,
                "description": job.description or "",
                "classifier_policy": (
                    classification.policy
                    if classification
                    else "MISSING"
                ),
                "classifier_version": (
                    classification.classifier_version
                    if classification
                    else ""
                ),
                "classifier_evidence": format_evidence(
                    classification.evidence
                    if classification
                    else []
                ),
                "classifier_h1b_transfer_supported": (
                    str(
                        classification.h1b_transfer_supported
                    )
                    if classification
                    else ""
                ),
                # Human-review fields begin empty.
                "expected_policy": "",
                "expected_h1b_transfer_supported": "",
                "label_reason": "",
                "reviewed_by": "",
                "reviewed_at": "",
            }
        )

    return exported_jobs


def export_review_file() -> None:
    """
    Export current jobs while preserving labels completed in earlier exports.
    """

    existing_labels = load_existing_labels()

    with SessionLocal() as database:
        database_rows = load_database_rows(database)

    final_rows = [
        preserve_human_fields(
            row,
            existing_labels.get(row["job_id"]),
        )
        for row in database_rows
    ]

    LABEL_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with LABEL_FILE.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=CSV_COLUMNS,
        )

        writer.writeheader()
        writer.writerows(final_rows)

    preserved_count = sum(
        bool(row["expected_policy"])
        for row in final_rows
    )

    print("\nExport complete")
    print("-------------------------------")
    print("Jobs exported:", len(final_rows))
    print("Existing labels preserved:", preserved_count)
    print("Review file:", LABEL_FILE)


# =============================================================================
# Label Validation
# =============================================================================

def load_completed_reviews() -> list[dict[str, str]]:
    """
    Load reviewed examples and run the current classifier on every description.

    Why predictions are recalculated
    ---------------------------------
    The CSV contains `classifier_policy`, but that value represents the
    classifier version active when the file was originally exported.

    If we compared expected labels with that old column after upgrading the
    classifier, the reported metrics would still describe the older system.

    Therefore, every evaluation run:

    1. reads the human-reviewed expected answer;
    2. classifies the original description using the currently installed code;
    3. stores the new result in `evaluated_policy`;
    4. compares that new result against `expected_policy`.

    The original CSV prediction remains untouched for historical comparison.
    """

    if not LABEL_FILE.exists():
        raise FileNotFoundError(
            f"Review file not found: {LABEL_FILE}. "
            "Run the export command first."
        )

    completed_rows = []
    errors = []

    with LABEL_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        reader = csv.DictReader(csv_file)

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            expected_policy = normalize_policy(
                row.get("expected_policy")
            )

            # An empty expected policy means the example has not been reviewed
            # yet and therefore cannot contribute to evaluation metrics.
            if not expected_policy:
                continue

            if expected_policy not in VALID_POLICIES:
                errors.append(
                    f"Row {row_number}: invalid expected_policy "
                    f"'{expected_policy}'"
                )
                continue

            description = row.get("description") or ""

            # Run the actual current classifier against the original posting.
            # This is the prediction we evaluate—not the stale exported value.
            current_result = classify_description(
                description
            )

            reviewed_row = dict(row)

            # Preserve normalized expected labels for reliable comparisons.
            reviewed_row[
                "expected_policy"
            ] = expected_policy

            # Preserve the original exported policy under a clearer name.
            reviewed_row[
                "exported_policy"
            ] = normalize_policy(
                row.get("classifier_policy")
            )

            # Store the prediction produced by the current code.
            reviewed_row[
                "classifier_policy"
            ] = normalize_policy(
                current_result.get(
                    "current_policy"
                )
            )

            reviewed_row[
                "evaluated_classifier_version"
            ] = str(
                current_result.get(
                    "classifier_version"
                )
                or CLASSIFIER_VERSION
            )

            reviewed_row[
                "evaluated_evidence"
            ] = format_evidence(
                current_result.get(
                    "current_policy_evidence"
                )
            )

            reviewed_row[
                "evaluated_h1b_transfer_supported"
            ] = str(
                bool(
                    current_result.get(
                        "h1b_transfer_supported"
                    )
                )
            )

            completed_rows.append(
                reviewed_row
            )

    if errors:
        joined_errors = "\n".join(errors)

        raise ValueError(
            "Invalid human labels were found:\n"
            f"{joined_errors}"
        )

    return completed_rows


# =============================================================================
# Classification Metrics
# =============================================================================

def safe_divide(
    numerator: int,
    denominator: int,
) -> float:
    """Avoid division-by-zero errors in small evaluation datasets."""

    if denominator == 0:
        return 0.0

    return numerator / denominator


def calculate_class_metrics(
    rows: list[dict[str, str]],
    policy: str,
) -> dict[str, float | int]:
    """
    Calculate one-vs-rest metrics for a sponsorship policy.

    Precision:
        Of everything predicted as this policy, how much was correct?

    Recall:
        Of everything truly belonging to this policy, how much was found?
    """

    true_positive = sum(
        row["classifier_policy"] == policy
        and row["expected_policy"] == policy
        for row in rows
    )

    false_positive = sum(
        row["classifier_policy"] == policy
        and row["expected_policy"] != policy
        for row in rows
    )

    false_negative = sum(
        row["classifier_policy"] != policy
        and row["expected_policy"] == policy
        for row in rows
    )

    precision = safe_divide(
        true_positive,
        true_positive + false_positive,
    )

    recall = safe_divide(
        true_positive,
        true_positive + false_negative,
    )

    f1_score = safe_divide(
        2 * precision * recall,
        precision + recall,
    )

    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
    }


def print_confusion_matrix(
    rows: list[dict[str, str]],
) -> None:
    """Print actual-versus-predicted counts without external dependencies."""

    policies = sorted(VALID_POLICIES)

    matrix = {
        actual: Counter(
            row["classifier_policy"]
            for row in rows
            if row["expected_policy"] == actual
        )
        for actual in policies
    }

    print("\nConfusion matrix")
    print("-------------------------------")
    print("Rows = expected; columns = predicted\n")

    header = f"{'Expected':<14}" + "".join(
        f"{policy[:8]:>11}"
        for policy in policies
    )

    print(header)

    for actual in policies:
        line = f"{actual:<14}"

        for predicted in policies:
            line += f"{matrix[actual][predicted]:>11}"

        print(line)


def print_error_examples(
    rows: list[dict[str, str]],
) -> None:
    """Print misclassified jobs so failures can guide the next improvement."""

    errors = [
        row
        for row in rows
        if row["classifier_policy"]
        != row["expected_policy"]
    ]

    print("\nMisclassified examples")
    print("-------------------------------")

    if not errors:
        print("No errors found in the reviewed sample.")
        return

    for index, row in enumerate(
        errors,
        start=1,
    ):
        print(
            f"\n{index}. {row['company']} — {row['title']}"
        )
        print(
            "   Predicted:",
            row["classifier_policy"],
        )
        print(
            "   Expected:",
            row["expected_policy"],
        )

        if row.get("evaluated_evidence"):
            print(
                "   Current classifier evidence:",
                row["evaluated_evidence"],
            )

        if row.get("exported_policy"):
            print(
                "   Original exported prediction:",
                row["exported_policy"],
            )

        if row.get("label_reason"):
            print(
                "   Reviewer reason:",
                row["label_reason"],
            )


# =============================================================================
# Evaluation Report
# =============================================================================

def evaluate_accuracy() -> None:
    """Calculate and print accuracy metrics from completed human reviews."""

    rows = load_completed_reviews()

    if not rows:
        print(
            "\nNo completed labels were found.\n"
            "Fill expected_policy in the CSV before evaluating."
        )
        return

    correct_predictions = sum(
        row["classifier_policy"]
        == row["expected_policy"]
        for row in rows
    )

    overall_accuracy = safe_divide(
        correct_predictions,
        len(rows),
    )

    # Coverage measures how often the classifier makes a definite decision.
    definite_predictions = sum(
        row["classifier_policy"]
        in {"AVAILABLE", "UNAVAILABLE"}
        for row in rows
    )

    coverage = safe_divide(
        definite_predictions,
        len(rows),
    )

    print("\nSponsorship classifier evaluation")
    print("=================================")
    print(
        "Evaluated classifier version:",
        CLASSIFIER_VERSION,
    )
    print("Reviewed examples:", len(rows))
    print(
        "Overall accuracy:",
        f"{overall_accuracy:.1%}",
    )
    print(
        "Definite-decision coverage:",
        f"{coverage:.1%}",
    )

    print("\nPer-class metrics")
    print("-------------------------------")

    for policy in sorted(VALID_POLICIES):
        metrics = calculate_class_metrics(
            rows,
            policy,
        )

        print(
            f"{policy:<12} "
            f"precision={metrics['precision']:.1%}  "
            f"recall={metrics['recall']:.1%}  "
            f"f1={metrics['f1_score']:.1%}  "
            f"support={sum(row['expected_policy'] == policy for row in rows)}"
        )

    print_confusion_matrix(rows)
    print_error_examples(rows)


# =============================================================================
# Command-Line Interface
# =============================================================================

def parse_arguments() -> argparse.Namespace:
    """Read the requested script operation."""

    parser = argparse.ArgumentParser(
        description=(
            "Export sponsorship-review records or "
            "evaluate completed human labels."
        )
    )

    parser.add_argument(
        "command",
        choices={"export", "evaluate"},
        help=(
            "'export' creates/updates the review CSV; "
            "'evaluate' calculates metrics."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run the command selected by the user."""

    arguments = parse_arguments()

    if arguments.command == "export":
        export_review_file()
    else:
        evaluate_accuracy()


if __name__ == "__main__":
    main()
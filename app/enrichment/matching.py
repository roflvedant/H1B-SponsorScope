"""Coordinate historical employer and occupation matching.

Public functions in this file intentionally preserve the interface used by the
rest of the application:

* ``load_company_aliases``
* ``prepare_historical_data``
* ``find_historical_match``
* ``run_historical_matching``

Employer and occupation algorithms live in smaller focused modules. Therefore
``live_search.py`` and the batch pipeline do not need import changes, while the
implementation remains readable and testable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.config.settings import ENRICHED_DIRECTORY, PROCESSED_DIRECTORY
from app.enrichment.employer_resolution import (
    EmployerResolution,
    load_company_aliases,
    prepare_historical_data,
    resolve_employer,
)
from app.enrichment.occupation_resolution import (
    OccupationResolution,
    infer_soc_candidates,
    resolve_occupation,
)


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

# Increment the matching version whenever matching behavior changes materially.
# Storing the version lets the API select and explain the newest evidence while
# preserving older results for reproducibility.
MATCHING_VERSION = "historical-v3"
HISTORICAL_FISCAL_YEAR = 2025


# ---------------------------------------------------------------------------
# Safe value conversion
# ---------------------------------------------------------------------------

def _optional_text(value: object) -> str | None:
    """Return clean text, converting pandas missing values to None."""

    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _integer_sum(rows: pd.DataFrame, column: str) -> int:
    """Safely total a numeric evidence column."""

    if rows.empty or column not in rows.columns:
        return 0
    values = pd.to_numeric(rows[column], errors="coerce").fillna(0)
    return int(values.sum())


def _best_evidence_row(rows: pd.DataFrame) -> pd.Series | None:
    """Select the strongest row for human-readable evidence fields."""

    if rows.empty:
        return None
    return rows.sort_values(
        "certified_lca_cases", ascending=False
    ).iloc[0]


# ---------------------------------------------------------------------------
# Evidence construction
# ---------------------------------------------------------------------------

def _base_employer_evidence(
    employer: EmployerResolution,
) -> dict[str, Any]:
    """Create evidence fields that are available after employer resolution."""

    return {
        "matching_version": MATCHING_VERSION,
        "employer_match_type": employer.match_type,
        "employer_match_confidence": round(employer.confidence, 4),
        "occupation_match_type": None,
        "occupation_match_confidence": 0.0,
        "match_confidence": 0.0,
        "matched_dol_employer": employer.candidate_dol_employer,
        "matched_dol_job_title": None,
        "matched_soc_code": None,
        "matched_soc_title": None,
        "certified_lca_cases": 0,
        "worker_positions": 0,
        "fiscal_year": HISTORICAL_FISCAL_YEAR,
        "requires_human_review": employer.requires_human_review,
        "failure_reason": None,
    }


def _completed_evidence(
    employer: EmployerResolution,
    occupation: OccupationResolution,
) -> dict[str, Any]:
    """Combine employer and occupation results into database-ready evidence."""

    evidence = _base_employer_evidence(employer)
    best_row = _best_evidence_row(occupation.rows)

    if best_row is not None:
        evidence.update(
            {
                "matched_dol_employer": _optional_text(
                    best_row.get("dol_employer_name")
                ),
                "matched_dol_job_title": _optional_text(
                    best_row.get("dol_job_title")
                ),
                "matched_soc_code": (
                    occupation.inferred_soc_code
                    or _optional_text(best_row.get("SOC_CODE"))
                ),
                "matched_soc_title": (
                    occupation.inferred_soc_title
                    or _optional_text(best_row.get("SOC_TITLE"))
                ),
                "certified_lca_cases": _integer_sum(
                    occupation.rows, "certified_lca_cases"
                ),
                "worker_positions": _integer_sum(
                    occupation.rows, "worker_positions"
                ),
            }
        )

    combined_confidence = min(
        employer.confidence,
        occupation.confidence,
    )
    evidence.update(
        {
            "occupation_match_type": occupation.match_type,
            "occupation_match_confidence": round(
                occupation.confidence, 4
            ),
            "match_confidence": round(combined_confidence, 4),
            "requires_human_review": (
                employer.requires_human_review
                or occupation.requires_human_review
            ),
            "failure_reason": occupation.failure_reason,
        }
    )
    return evidence


# ---------------------------------------------------------------------------
# Public single-job matcher
# ---------------------------------------------------------------------------

def find_historical_match(
    job: dict[str, Any],
    history: pd.DataFrame,
    aliases: dict[str, str],
) -> dict[str, Any]:
    """Match one current job against certified historical DOL evidence.

    Historical support is True only when employer and occupation both match
    automatically. Review candidates preserve their evidence but remain False,
    protecting the user interface from displaying uncertain claims as facts.
    """

    employer = resolve_employer(job.get("company"), history, aliases)

    if not employer.matched:
        return {
            "historical_support": False,
            "historical_evidence": {
                "matching_version": MATCHING_VERSION,
                "employer_match_type": None,
                "employer_match_confidence": round(
                    employer.confidence, 4
                ),
                "occupation_match_type": None,
                "occupation_match_confidence": 0.0,
                "match_confidence": 0.0,
                "requires_human_review": False,
                "failure_reason": "EMPLOYER_UNMATCHED",
            },
        }

    # A fuzzy employer review candidate cannot automatically establish support.
    # We retain its employer evidence so it can be audited or manually aliased.
    if employer.requires_human_review:
        evidence = _base_employer_evidence(employer)
        evidence["failure_reason"] = "EMPLOYER_REQUIRES_REVIEW"
        return {
            "historical_support": False,
            "historical_evidence": evidence,
        }

    occupation = resolve_occupation(
        job.get("title"),
        employer.rows,
        history,
    )
    evidence = _completed_evidence(employer, occupation)

    supported = occupation.matched and not occupation.requires_human_review
    return {
        "historical_support": bool(supported),
        "historical_evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Batch pipeline entry point
# ---------------------------------------------------------------------------

def run_historical_matching():
    """Enrich the newest classified snapshot with historical DOL evidence."""

    classified_files = list(
        ENRICHED_DIRECTORY.glob("classified_jobs_*.json")
    )
    if not classified_files:
        raise FileNotFoundError("No classified job file was found.")

    latest_file = max(
        classified_files,
        key=lambda file: file.stat().st_mtime,
    )
    with latest_file.open("r", encoding="utf-8") as file:
        jobs = json.load(file)

    history_file = PROCESSED_DIRECTORY / "dol_h1b_history_2025.csv"
    if not history_file.exists():
        raise FileNotFoundError("Processed DOL history was not found.")

    raw_history = pd.read_csv(history_file, dtype={"SOC_CODE": str})
    aliases = load_company_aliases()
    history = prepare_historical_data(raw_history, aliases)

    for job in jobs:
        job.update(find_historical_match(job, history, aliases))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = ENRICHED_DIRECTORY / f"final_jobs_{timestamp}.json"
    with output_file.open("w", encoding="utf-8") as file:
        json.dump(jobs, file, indent=2)

    supported_count = sum(
        bool(job.get("historical_support")) for job in jobs
    )
    review_count = sum(
        bool(
            (job.get("historical_evidence") or {}).get(
                "requires_human_review"
            )
        )
        for job in jobs
    )

    print("Historical matching version:", MATCHING_VERSION)
    print("Jobs with historical support:", supported_count)
    print("Historical candidates requiring review:", review_count)
    print("Final data saved to:", output_file)

    return output_file
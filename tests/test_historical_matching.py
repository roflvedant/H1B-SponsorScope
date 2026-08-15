"""Regression tests for historical employer and occupation matching.

Small in-memory DataFrames keep these tests fast and deterministic. They do
not require PostgreSQL, network access, or the complete DOL dataset.
"""

from __future__ import annotations

import pandas as pd

from app.enrichment.matching import (
    find_historical_match,
    infer_soc_candidates,
    prepare_historical_data,
)


# ---------------------------------------------------------------------------
# Representative historical fixture
# ---------------------------------------------------------------------------

def build_history() -> pd.DataFrame:
    """Create a compact DOL-like dataset covering key matching branches.

    The rows include an exact Data Engineer occupation, two plausible Google
    technology occupations, and one misleading Customer Engineer occupation.
    """

    return pd.DataFrame(
        [
            {
                "company_key": "example analytics",
                "dol_employer_name": "Example Analytics LLC",
                "dol_job_title": "Data Engineer",
                "job_title_key": "data engineer",
                "SOC_CODE": "15-2051.00",
                "SOC_TITLE": "Data Scientists",
                "certified_lca_cases": 20,
                "worker_positions": 25,
            },
            {
                "company_key": "google",
                "dol_employer_name": "Google LLC",
                "dol_job_title": "Data Scientist",
                "job_title_key": "data scientist",
                "SOC_CODE": "15-2051.00",
                "SOC_TITLE": "Data Scientists",
                "certified_lca_cases": 17,
                "worker_positions": 20,
            },
            {
                "company_key": "google",
                "dol_employer_name": "Google LLC",
                "dol_job_title": "Software Engineer",
                "job_title_key": "software engineer",
                "SOC_CODE": "15-1252.00",
                "SOC_TITLE": "Software Developers",
                "certified_lca_cases": 484,
                "worker_positions": 500,
            },
            {
                "company_key": "google",
                "dol_employer_name": "Google LLC",
                "dol_job_title": "Customer Engineer",
                "job_title_key": "customer engineer",
                "SOC_CODE": "41-9031.00",
                "SOC_TITLE": "Sales Engineers",
                "certified_lca_cases": 17,
                "worker_positions": 17,
            },
        ]
    )


# ---------------------------------------------------------------------------
# Global SOC inference
# ---------------------------------------------------------------------------

def test_data_engineer_infers_data_occupation() -> None:
    """Cloud Data Engineer should infer a data-related SOC candidate first."""

    history = prepare_historical_data(
        history=build_history(),
        aliases={},
    )

    candidates = infer_soc_candidates(
        current_title="Cloud Data Engineer",
        history=history,
    )

    assert candidates

    # DOL sources may represent the same occupation as either 15-2051 or the
    # more detailed 15-2051.00, so compare the stable occupation prefix.
    assert candidates[0].soc_code.startswith("15-2051")


def test_unrelated_engineer_title_is_not_selected() -> None:
    """A shared word like 'engineer' must not select a sales occupation."""

    history = prepare_historical_data(
        history=build_history(),
        aliases={},
    )

    candidates = infer_soc_candidates(
        current_title="Cloud Data Engineer",
        history=history,
    )

    assert all(
        not candidate.soc_code.startswith("41-9031")
        for candidate in candidates
    )


# ---------------------------------------------------------------------------
# Complete employer-and-occupation matching
# ---------------------------------------------------------------------------

def test_dynamic_soc_can_match_resolved_employer() -> None:
    """A resolved employer can match through a strongly inferred SOC."""

    history = prepare_historical_data(
        history=build_history(),
        aliases={},
    )

    result = find_historical_match(
        job={
            "company": "Google LLC",
            "title": "Cloud Data Engineer",
        },
        history=history,
        aliases={},
    )

    assert result["historical_support"] is True
    assert (
        result["historical_evidence"]["occupation_match_type"]
        == "DYNAMIC_SOC"
    )


def test_employer_only_history_does_not_become_yellow() -> None:
    """An employer match alone must not establish occupation-level support."""

    history = prepare_historical_data(
        history=build_history(),
        aliases={},
    )

    result = find_historical_match(
        job={
            "company": "Google LLC",
            "title": "Mechanical Engineer",
        },
        history=history,
        aliases={},
    )

    assert result["historical_support"] is False
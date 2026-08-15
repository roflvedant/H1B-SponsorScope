"""Employer-resolution helpers for historical H-1B matching.

This module answers one narrow question: "Which DOL employer, if any, is the
same organization as the company shown in the current job posting?"

Keeping this logic separate prevents the main matching coordinator from
growing into a thousand-line file and makes employer matching testable without
running occupation matching or the complete enrichment pipeline.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

import pandas as pd

from app.config.settings import REFERENCE_DIRECTORY
from app.enrichment.historical import normalize_company


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Automatic fuzzy matches must be very strong. A lower score is retained only
# as a review candidate and must never create historical support automatically.
EMPLOYER_AUTO_THRESHOLD = 0.92
EMPLOYER_REVIEW_THRESHOLD = 0.84


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EmployerResolution:
    """The outcome of resolving one job company against DOL employer rows."""

    rows: pd.DataFrame
    match_type: str | None
    confidence: float
    requires_human_review: bool
    input_company_key: str
    canonical_company_key: str | None
    candidate_dol_employer: str | None = None

    @property
    def matched(self) -> bool:
        """Return True when at least one historical employer row was found."""

        return not self.rows.empty


# ---------------------------------------------------------------------------
# Alias loading and historical-data preparation
# ---------------------------------------------------------------------------

def _is_verified(value: object) -> bool:
    """Convert common CSV truth values into a dependable boolean."""

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def load_company_aliases() -> dict[str, str]:
    """Load only manually verified employer aliases.

    The returned dictionary maps a normalized alias to a normalized canonical
    employer key. Missing alias files are valid; exact matching will still work.
    """

    alias_file = REFERENCE_DIRECTORY / "company_aliases.csv"
    if not alias_file.exists():
        return {}

    alias_data = pd.read_csv(alias_file)
    required_columns = {"alias_key", "canonical_key", "verified"}

    if not required_columns.issubset(alias_data.columns):
        missing = sorted(required_columns - set(alias_data.columns))
        raise ValueError(
            "company_aliases.csv is missing required columns: "
            f"{missing}"
        )

    verified_aliases = alias_data[alias_data["verified"].apply(_is_verified)]

    return {
        normalize_company(row["alias_key"]): normalize_company(
            row["canonical_key"]
        )
        for _, row in verified_aliases.iterrows()
        if normalize_company(row["alias_key"])
        and normalize_company(row["canonical_key"])
    }


def prepare_historical_data(
    history: pd.DataFrame,
    aliases: dict[str, str],
) -> pd.DataFrame:
    """Validate and prepare the DOL frame once before matching many jobs.

    A copy is returned so callers do not unexpectedly mutate the DataFrame they
    loaded from disk. Numeric evidence columns are also cleaned here, keeping
    conversion concerns out of later matching functions.
    """

    required_columns = {
        "company_key",
        "job_title_key",
        "dol_employer_name",
        "dol_job_title",
        "SOC_CODE",
        "SOC_TITLE",
        "certified_lca_cases",
        "worker_positions",
    }
    missing = sorted(required_columns - set(history.columns))
    if missing:
        raise ValueError(f"Historical DOL data is missing columns: {missing}")

    prepared = history.copy()
    prepared["company_key"] = prepared["company_key"].apply(
        normalize_company
    )
    prepared["canonical_company_key"] = prepared["company_key"].apply(
        lambda key: aliases.get(key, key)
    )

    for column in ("certified_lca_cases", "worker_positions"):
        prepared[column] = pd.to_numeric(
            prepared[column], errors="coerce"
        ).fillna(0)

    # Keep codes as strings and remove Excel's occasional trailing `.0`.
    prepared["SOC_CODE"] = (
        prepared["SOC_CODE"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    # Dynamic SOC inference does not need to inspect every employer filing.
    # Build one compact title/SOC catalog now and attach it to the prepared
    # DataFrame. This turns repeated scans of the full DOL dataset into scans of
    # unique occupational examples and keeps the batch pipeline responsive.
    soc_catalog = (
        prepared[
            [
                "job_title_key",
                "dol_job_title",
                "SOC_CODE",
                "SOC_TITLE",
                "certified_lca_cases",
            ]
        ]
        .dropna(subset=["job_title_key"])
        .sort_values("certified_lca_cases", ascending=False)
        .drop_duplicates(subset=["job_title_key", "SOC_CODE"])
        .reset_index(drop=True)
    )
    prepared.attrs["soc_catalog"] = soc_catalog

    # Build an inverted index once: each title word points to the catalog rows
    # containing that word. Occupation inference can then create a small
    # shortlist without repeatedly scanning every historical title.
    token_index: dict[str, list[int]] = defaultdict(list)
    for row_position, title in enumerate(soc_catalog["job_title_key"]):
        for token in set(str(title).split()):
            if token:
                token_index[token].append(row_position)

    prepared.attrs["soc_token_index"] = dict(token_index)

    # Fuzzy employer matching also needs a shortlist. Index canonical employer
    # names by complete words and by a compact three-character prefix. The word
    # index handles multi-word companies; the prefix index preserves tolerance
    # for small spelling mistakes in single-word employer names.
    canonical_keys = tuple(
        str(key)
        for key in prepared["canonical_company_key"].dropna().unique()
        if str(key)
    )
    employer_token_index: dict[str, list[str]] = defaultdict(list)
    employer_prefix_index: dict[str, list[str]] = defaultdict(list)

    for canonical_key in canonical_keys:
        for token in set(canonical_key.split()):
            if token:
                employer_token_index[token].append(canonical_key)

        compact_key = canonical_key.replace(" ", "")
        if compact_key:
            employer_prefix_index[compact_key[:3]].append(canonical_key)

    prepared.attrs["canonical_company_keys"] = canonical_keys
    prepared.attrs["employer_token_index"] = dict(employer_token_index)
    prepared.attrs["employer_prefix_index"] = dict(employer_prefix_index)

    return prepared


# ---------------------------------------------------------------------------
# Employer similarity and resolution
# ---------------------------------------------------------------------------

def employer_similarity(left: str, right: str) -> float:
    """Score two already-normalized employer names from 0.0 to 1.0.

    Character similarity handles small spelling differences, while token
    overlap prevents unrelated organizations with superficially similar names
    from receiving an overly generous score.
    """

    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    left_tokens = set(left.split())
    right_tokens = set(right.split())
    union = left_tokens | right_tokens
    token_score = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence_score = SequenceMatcher(None, left, right).ratio()

    return round((0.60 * sequence_score) + (0.40 * token_score), 4)


def resolve_employer(
    company: object,
    history: pd.DataFrame,
    aliases: dict[str, str],
) -> EmployerResolution:
    """Resolve a current company name to historical DOL employer rows.

    Resolution order:
    1. exact normalized employer;
    2. manually verified alias;
    3. conservative fuzzy candidate.

    A review-level fuzzy candidate is returned with its rows for inspection,
    but `requires_human_review=True` prevents automatic historical support.
    """

    company_key = normalize_company(company)
    if not company_key:
        return EmployerResolution(
            rows=history.iloc[0:0],
            match_type=None,
            confidence=0.0,
            requires_human_review=False,
            input_company_key="",
            canonical_company_key=None,
        )

    canonical_key = aliases.get(company_key, company_key)
    exact_rows = history[
        history["canonical_company_key"] == canonical_key
    ]

    if not exact_rows.empty:
        used_alias = canonical_key != company_key
        return EmployerResolution(
            rows=exact_rows,
            match_type="VERIFIED_ALIAS" if used_alias else "EXACT_NORMALIZED",
            confidence=1.0,
            requires_human_review=False,
            input_company_key=company_key,
            canonical_company_key=canonical_key,
            candidate_dol_employer=str(
                exact_rows.iloc[0]["dol_employer_name"]
            ),
        )

    # Compare only unique canonical keys so large employers do not get an
    # unfair advantage merely because they have more historical filing rows.
    all_candidate_keys = history.attrs.get(
        "canonical_company_keys",
        tuple(history["canonical_company_key"].dropna().unique()),
    )
    employer_token_index = history.attrs.get("employer_token_index")
    employer_prefix_index = history.attrs.get("employer_prefix_index")

    if employer_token_index and employer_prefix_index:
        shortlisted_keys: set[str] = set()
        for token in company_key.split():
            shortlisted_keys.update(employer_token_index.get(token, []))

        compact_key = company_key.replace(" ", "")
        if compact_key:
            shortlisted_keys.update(
                employer_prefix_index.get(compact_key[:3], [])
            )

        candidate_keys = shortlisted_keys
    else:
        # Unit-test fixtures and older prepared frames may not have indexes.
        candidate_keys = all_candidate_keys

    scored_candidates = sorted(
        (
            (employer_similarity(company_key, str(candidate)), str(candidate))
            for candidate in candidate_keys
            if str(candidate)
        ),
        reverse=True,
    )

    if not scored_candidates:
        return EmployerResolution(
            rows=history.iloc[0:0],
            match_type=None,
            confidence=0.0,
            requires_human_review=False,
            input_company_key=company_key,
            canonical_company_key=None,
        )

    best_score, best_key = scored_candidates[0]
    if best_score < EMPLOYER_REVIEW_THRESHOLD:
        return EmployerResolution(
            rows=history.iloc[0:0],
            match_type=None,
            confidence=best_score,
            requires_human_review=False,
            input_company_key=company_key,
            canonical_company_key=None,
        )

    candidate_rows = history[
        history["canonical_company_key"] == best_key
    ]
    requires_review = best_score < EMPLOYER_AUTO_THRESHOLD

    return EmployerResolution(
        rows=candidate_rows,
        match_type=(
            "FUZZY_REVIEW" if requires_review else "FUZZY_HIGH_CONFIDENCE"
        ),
        confidence=best_score,
        requires_human_review=requires_review,
        input_company_key=company_key,
        canonical_company_key=best_key,
        candidate_dol_employer=str(
            candidate_rows.iloc[0]["dol_employer_name"]
        ),
    )
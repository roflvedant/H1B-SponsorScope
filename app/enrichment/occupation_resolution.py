"""Occupation and SOC resolution for historical H-1B evidence.

The current posting title rarely matches a DOL filing title word-for-word.
This module therefore uses two evidence layers:

1. direct title matching inside the already-resolved employer;
2. cautious SOC inference learned from title/SOC pairs across the DOL dataset.

The global SOC inference does not prove that an employer sponsored a role. It
only identifies likely occupations. Historical support is created only when
the resolved employer also has certified filings in one of those occupations.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
import math

import pandas as pd

from app.enrichment.historical import normalize_job_title


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DIRECT_TITLE_AUTO_THRESHOLD = 0.86
DIRECT_TITLE_REVIEW_THRESHOLD = 0.74
SOC_CANDIDATE_THRESHOLD = 0.72
SOC_AUTO_THRESHOLD = 0.84
SOC_REVIEW_THRESHOLD = 0.74
SOC_AMBIGUITY_MARGIN = 0.05
MAX_SOC_CANDIDATES = 3

# If a very generic title still produces a large shortlist, retain the most
# relevant rows before running the more expensive sequence comparison.
MAX_TITLE_SHORTLIST = 10_000


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SocCandidate:
    """One SOC occupation inferred from the current job title."""

    soc_code: str
    soc_title: str | None
    score: float
    supporting_title: str | None
    global_cases: int


@dataclass(frozen=True)
class OccupationResolution:
    """The occupation evidence selected for one resolved employer."""

    rows: pd.DataFrame
    match_type: str | None
    confidence: float
    requires_human_review: bool
    failure_reason: str | None = None
    inferred_soc_code: str | None = None
    inferred_soc_title: str | None = None

    @property
    def matched(self) -> bool:
        """Return True when occupation evidence rows were found."""

        return not self.rows.empty


# ---------------------------------------------------------------------------
# Title similarity
# ---------------------------------------------------------------------------

def _meaningful_tokens(title_key: str) -> set[str]:
    """Return title words that carry useful occupational meaning."""

    ignored = {
        "associate",
        "chief",
        "director",
        "head",
        "i",
        "ii",
        "iii",
        "iv",
        "manager",
        "president",
        "staff",
        "vice",
    }
    return {word for word in title_key.split() if word not in ignored}


def occupation_similarity(left: object, right: object) -> float:
    """Score two job titles from 0.0 to 1.0 after normalization.

    A containment bonus handles titles such as "Cloud Data Engineer" versus
    "Data Engineer" without treating every title containing "Engineer" as the
    same occupation. At least two meaningful shared words are required.
    """

    left_key = normalize_job_title(left)
    right_key = normalize_job_title(right)

    return _normalized_occupation_similarity(left_key, right_key)


@lru_cache(maxsize=200_000)
def _normalized_occupation_similarity(
    left_key: str,
    right_key: str,
) -> float:
    """Compare normalized titles and cache repeated comparisons.

    DOL history contains the same occupational titles across many employers.
    Caching avoids repeating identical token and sequence calculations.
    """

    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0

    left_tokens = _meaningful_tokens(left_key)
    right_tokens = _meaningful_tokens(right_key)
    shared = left_tokens & right_tokens
    union = left_tokens | right_tokens

    token_score = len(shared) / len(union) if union else 0.0
    sequence_score = SequenceMatcher(None, left_key, right_key).ratio()
    score = (0.70 * token_score) + (0.30 * sequence_score)

    smaller = min(len(left_tokens), len(right_tokens))
    if smaller >= 2 and len(shared) == smaller:
        score = max(score, 0.88)

    return round(min(score, 1.0), 4)


# ---------------------------------------------------------------------------
# Dynamic SOC inference
# ---------------------------------------------------------------------------

def infer_soc_candidates(
    current_title: object,
    history: pd.DataFrame,
) -> list[SocCandidate]:
    """Infer likely SOC codes from title/SOC examples in all DOL history.

    The algorithm is data-driven: it does not maintain a brittle hard-coded
    list saying that every engineering job belongs to a particular SOC code.
    For each SOC, it retains the strongest supporting historical title and adds
    only a tiny case-volume bonus to break otherwise similar candidates.
    """

    title_key = normalize_job_title(current_title)
    if not title_key:
        return []

    best_by_soc: dict[str, SocCandidate] = {}

    # `prepare_historical_data` attaches a reduced catalog containing unique
    # title/SOC examples. Fall back to the supplied frame so unit-test fixtures
    # and older callers remain compatible.
    catalog = history.attrs.get("soc_catalog", history)
    token_index = history.attrs.get("soc_token_index")

    # Use the inverted title-token index prepared once during data loading.
    # A multi-word title must share at least two meaningful words; therefore
    # "Cloud Data Engineer" will not compare against every unrelated title
    # containing only the generic word "Engineer".
    query_tokens = _meaningful_tokens(title_key)
    if token_index and query_tokens:
        row_counts: Counter[int] = Counter()
        for token in query_tokens:
            row_counts.update(token_index.get(token, []))

        minimum_shared_tokens = 2 if len(query_tokens) >= 2 else 1
        candidate_positions = [
            position
            for position, shared_count in row_counts.most_common()
            if shared_count >= minimum_shared_tokens
        ][:MAX_TITLE_SHORTLIST]

        # No qualifying title means there is no defensible SOC inference.
        if not candidate_positions:
            return []

        catalog = catalog.iloc[candidate_positions]

    required_columns = [
        "job_title_key",
        "dol_job_title",
        "SOC_CODE",
        "SOC_TITLE",
        "certified_lca_cases",
    ]
    available_columns = [
        column for column in required_columns if column in catalog.columns
    ]
    catalog_rows = catalog[available_columns]

    # `itertuples` is substantially faster than `iterrows` and avoids creating
    # a new Pandas Series for every historical row.
    for row in catalog_rows.itertuples(index=False, name="SocCatalogRow"):
        soc_code = str(getattr(row, "SOC_CODE", "")).strip()
        if not soc_code or soc_code.lower() == "nan":
            continue

        similarity = occupation_similarity(
            title_key,
            getattr(row, "job_title_key", ""),
        )
        if similarity < SOC_CANDIDATE_THRESHOLD:
            continue

        raw_cases = getattr(row, "certified_lca_cases", 0)
        cases = 0 if pd.isna(raw_cases) else int(raw_cases)

        # Volume may add at most 0.03. Title similarity remains the dominant
        # signal, while repeated certified filings provide a modest tie-break.
        volume_bonus = min(math.log1p(max(cases, 0)) / 200, 0.03)
        candidate_score = round(min(similarity + volume_bonus, 1.0), 4)

        candidate = SocCandidate(
            soc_code=soc_code,
            soc_title=(
                None
                if pd.isna(getattr(row, "SOC_TITLE", None))
                else str(getattr(row, "SOC_TITLE"))
            ),
            score=candidate_score,
            supporting_title=(
                None
                if pd.isna(getattr(row, "dol_job_title", None))
                else str(getattr(row, "dol_job_title"))
            ),
            global_cases=cases,
        )

        existing = best_by_soc.get(soc_code)
        if existing is None or candidate.score > existing.score:
            best_by_soc[soc_code] = candidate

    return sorted(
        best_by_soc.values(),
        key=lambda candidate: (candidate.score, candidate.global_cases),
        reverse=True,
    )[:MAX_SOC_CANDIDATES]


# ---------------------------------------------------------------------------
# Employer-specific occupation resolution
# ---------------------------------------------------------------------------

def _direct_title_resolution(
    job_title: object,
    employer_rows: pd.DataFrame,
) -> OccupationResolution | None:
    """Try exact and high-confidence title matching within one employer."""

    title_key = normalize_job_title(job_title)
    exact_rows = employer_rows[
        employer_rows["job_title_key"].apply(normalize_job_title) == title_key
    ]
    if title_key and not exact_rows.empty:
        return OccupationResolution(
            rows=exact_rows,
            match_type="EXACT_CORE_TITLE",
            confidence=1.0,
            requires_human_review=False,
        )

    scored_rows = employer_rows.copy()
    scored_rows["_occupation_score"] = scored_rows["job_title_key"].apply(
        lambda historical_title: occupation_similarity(
            title_key, historical_title
        )
    )
    best_score = float(scored_rows["_occupation_score"].max())

    if best_score < DIRECT_TITLE_REVIEW_THRESHOLD:
        return None

    best_rows = scored_rows[
        scored_rows["_occupation_score"] == best_score
    ].drop(columns=["_occupation_score"])
    requires_review = best_score < DIRECT_TITLE_AUTO_THRESHOLD

    return OccupationResolution(
        rows=best_rows,
        match_type=(
            "TITLE_SIMILARITY_REVIEW"
            if requires_review
            else "TITLE_SIMILARITY"
        ),
        confidence=best_score,
        requires_human_review=requires_review,
    )


def _soc_resolution(
    job_title: object,
    employer_rows: pd.DataFrame,
    history: pd.DataFrame,
) -> OccupationResolution | None:
    """Match globally inferred SOC candidates against one employer's filings."""

    candidates = infer_soc_candidates(job_title, history)
    employer_codes = set(employer_rows["SOC_CODE"].astype(str))
    available = [
        candidate
        for candidate in candidates
        if candidate.soc_code in employer_codes
    ]

    if not available:
        return None

    best = available[0]
    second_score = available[1].score if len(available) > 1 else 0.0
    margin = best.score - second_score

    if best.score < SOC_REVIEW_THRESHOLD:
        return None

    # One candidate is unambiguous. With multiple candidates, the best one must
    # lead by a meaningful margin before it can create automatic support.
    unambiguous = len(available) == 1 or margin >= SOC_AMBIGUITY_MARGIN
    automatic = best.score >= SOC_AUTO_THRESHOLD and unambiguous

    matched_rows = employer_rows[
        employer_rows["SOC_CODE"].astype(str) == best.soc_code
    ]

    return OccupationResolution(
        rows=matched_rows,
        match_type=("DYNAMIC_SOC" if automatic else "DYNAMIC_SOC_REVIEW"),
        confidence=best.score,
        requires_human_review=not automatic,
        inferred_soc_code=best.soc_code,
        inferred_soc_title=best.soc_title,
    )


def resolve_occupation(
    job_title: object,
    employer_rows: pd.DataFrame,
    history: pd.DataFrame,
) -> OccupationResolution:
    """Resolve occupation evidence using direct title, then dynamic SOC logic."""

    direct = _direct_title_resolution(job_title, employer_rows)
    if direct is not None:
        return direct

    inferred = _soc_resolution(job_title, employer_rows, history)
    if inferred is not None:
        return inferred

    return OccupationResolution(
        rows=employer_rows.iloc[0:0],
        match_type=None,
        confidence=0.0,
        requires_human_review=False,
        failure_reason="EMPLOYER_MATCHED_OCCUPATION_UNMATCHED",
    )
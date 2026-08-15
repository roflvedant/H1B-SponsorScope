"""Evaluate whether a job title belongs to the V1 data-engineering scope.

This is a deliberately conservative title-based relevance layer. It prevents
obvious false positives such as Data Center Technician while accepting the
small collection of data-engineering title families supported by V1.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Relevance rules
# ---------------------------------------------------------------------------

# Rejection rules run first because some unrelated titles contain broad words
# such as "data" or "engineer." Rule identifiers are saved as explanations so
# the decision can be inspected without reading the regular expression.
REJECTED_TITLE_PATTERNS = {
    "DATA_CENTER": r"\bdata center\b|\bdatacenter\b",
    "DATA_ENTRY": r"\bdata entry\b",
    "CABLING_NETWORK": r"\bcabling\b|\bstructured cable\b",
}

# Accepted rules represent the job families displayed by the V1 product.
# Word boundaries avoid accidental substring matches inside larger words.
ACCEPTED_TITLE_PATTERNS = {
    "DATA_ENGINEER": r"\bdata engineer(?:ing)?\b",
    "ANALYTICS_ENGINEER": r"\banalytics engineer\b",
    "DATA_PLATFORM_ENGINEER": r"\bdata platform engineer\b",
    "ETL_ENGINEER": r"\betl engineer\b",
    "DATA_WAREHOUSE_ENGINEER": r"\bdata warehouse engineer\b",
}


# ---------------------------------------------------------------------------
# Public relevance evaluator
# ---------------------------------------------------------------------------

def evaluate_job_relevance(title: object) -> tuple[bool, str]:
    """Return a relevance decision and an explainable rule identifier.

    The function returns ``(False, reason)`` when a title is explicitly
    rejected or unsupported. It returns ``(True, reason)`` only when an
    accepted title rule matches.
    """

    normalized_title = " ".join(str(title or "").lower().split())

    # Apply exclusions first so a known false positive cannot be accepted by a
    # broader rule added later.
    for rule_id, pattern in REJECTED_TITLE_PATTERNS.items():
        if re.search(pattern, normalized_title):
            return False, f"REJECTED_{rule_id}"

    for rule_id, pattern in ACCEPTED_TITLE_PATTERNS.items():
        if re.search(pattern, normalized_title):
            return True, f"ACCEPTED_{rule_id}"

    return False, "REJECTED_UNSUPPORTED_TITLE"
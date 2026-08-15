"""Classify explicit sponsorship language in current job descriptions.

This module is intentionally deterministic. It applies versioned regular-
expression rules, preserves the sentence that triggered each decision, and
never assumes that sponsorship is available when a posting says nothing about
immigration support.

The classifier answers a different question from historical DOL matching:

* this file evaluates the language in the current job posting;
* historical matching evaluates an employer's certified past H-1B activity.

Keeping those signals separate makes the final result easier to explain and
prevents historical behavior from overriding an explicit current restriction.
"""

import json
import re
from datetime import datetime, timezone

from app.config.settings import ENRICHED_DIRECTORY, PROCESSED_DIRECTORY
from app.enrichment.sponsorship_rules import (
    CLASSIFIER_VERSION,
    NEGATIVE_RULES,
    POSITIVE_RULES,
    TRANSFER_RULES,
)


# ---------------------------------------------------------------------------
# Sentence preparation
# ---------------------------------------------------------------------------

def split_sentences(description: object) -> list[str]:
    """Split a description while preserving readable evidence sentences.

    A lightweight splitter is sufficient because the rules search for explicit
    phrases rather than performing full linguistic parsing. Common abbreviations
    are protected temporarily so punctuation inside values such as ``U.S.`` does
    not split an evidence sentence in the wrong place.
    """

    # Normalize repeated whitespace from HTML-derived or poorly formatted job
    # descriptions before attempting to find sentence boundaries.
    clean_text = " ".join(str(description or "").split())
    if not clean_text:
        return []

    abbreviations = {
        "U.S.": "U<PERIOD>S<PERIOD>",
        "D.C.": "D<PERIOD>C<PERIOD>",
        "e.g.": "e<PERIOD>g<PERIOD>",
        "i.e.": "i<PERIOD>e<PERIOD>",
    }

    protected_text = clean_text
    for abbreviation, placeholder in abbreviations.items():
        protected_text = protected_text.replace(abbreviation, placeholder)

    sentences = re.split(r"(?<=[.!?])\s+", protected_text)

    # Restore protected punctuation before evidence is saved or displayed.
    return [
        sentence.replace("<PERIOD>", ".")
        for sentence in sentences
    ]


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------

def find_rule_matches(
    sentences: list[str],
    rules: dict[str, str],
) -> list[dict[str, str]]:
    """Return every rule match together with its human-readable evidence.

    Multiple matches are retained deliberately. They allow the API and UI to
    explain why a label was assigned and make later classifier evaluation
    possible without rerunning text extraction.
    """

    matches: list[dict[str, str]] = []

    for sentence in sentences:
        for rule_id, pattern in rules.items():
            match = re.search(pattern, sentence, flags=re.IGNORECASE)
            if match is None:
                continue

            matches.append(
                {
                    "rule_id": rule_id,
                    "matched_text": match.group(0),
                    "sentence": sentence,
                }
            )

    return matches


# ---------------------------------------------------------------------------
# Single-description classification
# ---------------------------------------------------------------------------

def classify_description(description: object) -> dict:
    """Classify explicit current sponsorship language and preserve evidence.

    Decision priority:

    1. positive and negative evidence -> ``CONFLICTING``;
    2. negative evidence only -> ``UNAVAILABLE``;
    3. positive evidence only -> ``AVAILABLE``;
    4. no explicit evidence -> ``UNKNOWN``.

    Transfer support is stored as a separate signal because a posting may
    discuss H-1B transfers without describing sponsorship for new applicants.
    """

    sentences = split_sentences(description)
    positive_matches = find_rule_matches(sentences, POSITIVE_RULES)
    negative_matches = find_rule_matches(sentences, NEGATIVE_RULES)
    transfer_matches = find_rule_matches(sentences, TRANSFER_RULES)

    if positive_matches and negative_matches:
        policy = "CONFLICTING"
        policy_evidence = positive_matches + negative_matches
    elif negative_matches:
        policy = "UNAVAILABLE"
        policy_evidence = negative_matches
    elif positive_matches:
        policy = "AVAILABLE"
        policy_evidence = positive_matches
    else:
        # Silence is not evidence of availability or unavailability.
        policy = "UNKNOWN"
        policy_evidence = []

    return {
        "current_policy": policy,
        "current_policy_evidence": policy_evidence,
        "h1b_transfer_supported": bool(transfer_matches),
        "h1b_transfer_evidence": transfer_matches,
        "classifier_version": CLASSIFIER_VERSION,
    }


# ---------------------------------------------------------------------------
# Batch pipeline entry point
# ---------------------------------------------------------------------------

def run_classification():
    """Classify the newest normalized snapshot and save enriched JSON output."""

    normalized_files = list(
        PROCESSED_DIRECTORY.glob("normalized_jobs_*.json")
    )
    if not normalized_files:
        raise FileNotFoundError("No normalized job file was found.")

    # File modification time identifies the newest pipeline snapshot without
    # depending on users to pass a generated timestamp between stages.
    latest_file = max(
        normalized_files,
        key=lambda file: file.stat().st_mtime,
    )
    with latest_file.open("r", encoding="utf-8") as file:
        jobs = json.load(file)

    for job in jobs:
        classification = classify_description(
            job.get("description", "")
        )
        job.update(classification)

    # Timestamped output keeps each run reproducible and prevents a later run
    # from silently overwriting an earlier classification snapshot.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = (
        ENRICHED_DIRECTORY / f"classified_jobs_{timestamp}.json"
    )
    with output_file.open("w", encoding="utf-8") as file:
        json.dump(jobs, file, indent=2)

    counts: dict[str, int] = {}
    for job in jobs:
        policy = job["current_policy"]
        counts[policy] = counts.get(policy, 0) + 1

    print("Classification counts:", counts)
    print("Classified data saved to:", output_file)

    return output_file
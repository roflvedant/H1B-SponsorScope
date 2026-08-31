"""Regression tests for current-posting sponsorship classification.

Every example protects a general language pattern. The tests intentionally
focus on explicit evidence because the classifier should return UNKNOWN rather
than make an unsupported sponsorship guess.
"""

from __future__ import annotations

from app.enrichment.classification import classify_description


# ---------------------------------------------------------------------------
# Core policy outcomes
# ---------------------------------------------------------------------------

def test_positive_sponsorship_language() -> None:
    """An explicit offer of sponsorship is AVAILABLE."""

    result = classify_description(
        "Visa sponsorship is available for this position."
    )
    assert result["current_policy"] == "AVAILABLE"


def test_negative_sponsorship_language() -> None:
    """An explicit refusal to sponsor is UNAVAILABLE."""

    result = classify_description(
        "We are unable to sponsor candidates for this role."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_generic_authorization_language_stays_unknown() -> None:
    """Generic work authorization does not necessarily answer sponsorship."""

    result = classify_description(
        "Applicants must be authorized to work in the US."
    )
    assert result["current_policy"] == "UNKNOWN"


def test_conflicting_language_is_not_guessed() -> None:
    """Positive and negative evidence together must be flagged as conflicting."""

    result = classify_description(
        "Visa sponsorship is available. We will not sponsor this position."
    )
    assert result["current_policy"] == "CONFLICTING"


# ---------------------------------------------------------------------------
# Citizenship and work-authorization restrictions
# ---------------------------------------------------------------------------

def test_citizenship_requirement_is_unavailable() -> None:
    """A mandatory U.S. citizenship requirement excludes sponsored workers."""

    result = classify_description(
        "This position requires U.S. citizenship."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_us_abbreviation_does_not_break_evidence_sentence() -> None:
    """Sentence splitting must preserve abbreviations inside evidence."""

    result = classify_description(
        "The position may be remote, requiring U.S. citizenship."
    )
    assert result["current_policy"] == "UNAVAILABLE"
    assert (
        "U.S. citizenship"
        in result["current_policy_evidence"][0]["sentence"]
    )


def test_united_states_citizenship_minimum_is_unavailable() -> None:
    """Spell-out citizenship requirements remain explicit restrictions."""

    result = classify_description(
        "United States Citizenship is a strict minimum requirement."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_work_authorization_sponsorship_is_unavailable() -> None:
    """Work-authorization sponsorship refusal is explicit negative evidence."""

    result = classify_description(
        "This role is not eligible for Mastercard's work authorization "
        "sponsorship."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_current_or_future_sponsorship_is_unavailable() -> None:
    """A current-or-future restriction includes later sponsorship needs."""

    result = classify_description(
        "Applicants must have work authorization that does not now or in the "
        "future require sponsorship of a visa."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_any_type_of_sponsorship_is_unavailable() -> None:
    """A refusal of every sponsorship type is conclusive."""

    result = classify_description(
        "UPMC does not offer any type of sponsorship for this position."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_employer_based_sponsorship_is_unavailable() -> None:
    """Employer-based visa sponsorship refusal is conclusive."""

    result = classify_description(
        "This position does not offer employer-based visa sponsorship now "
        "or in the future."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_employer_sponsored_authorization_refusal_is_unavailable() -> None:
    """Some employers describe sponsorship as sponsored authorization."""

    result = classify_description(
        "This role does not qualify for employer-sponsored work authorization."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_work_without_sponsorship_is_unavailable() -> None:
    """Explicit 'without sponsorship' language is a definite restriction."""

    result = classify_description(
        "Applicants must be eligible to work in the U.S. without sponsorship."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_citizen_or_green_card_mandatory_is_unavailable() -> None:
    """Citizen-or-permanent-resident-only eligibility excludes sponsorship."""

    result = classify_description(
        "Eligibility Requirements: US Citizen or Green Card holder mandatory."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_h1b_lottery_restriction_is_unavailable() -> None:
    """Explicit H-1B lottery refusal is negative current-posting evidence."""

    result = classify_description(
        "The company does not intend to hire job seekers who will need, "
        "now or in the future, sponsorship through the H-1B lottery."
    )
    assert result["current_policy"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Security-clearance requirements
# ---------------------------------------------------------------------------

def test_current_clearance_is_unavailable() -> None:
    """A mandatory existing security clearance is unavailable for V1 users."""

    result = classify_description(
        "Candidates must currently have security clearance."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_standalone_active_clearance_is_unavailable() -> None:
    """An active clearance listed as a qualification is a current requirement."""

    result = classify_description(
        "Basic Qualifications: Active Top Secret security clearance."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_hold_active_ts_sci_is_unavailable() -> None:
    """Requiring candidates to hold an active clearance is conclusive."""

    result = classify_description(
        "Candidates must hold an active TS/SCI security clearance."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_current_clearance_required_is_unavailable() -> None:
    """A current-clearance requirement differs from future eligibility."""

    result = classify_description(
        "Current TS/SCI clearance is required for this position."
    )
    assert result["current_policy"] == "UNAVAILABLE"


def test_active_clearance_strong_plus_remains_unknown() -> None:
    """Preferred clearance language must not be treated as mandatory."""

    result = classify_description("Active clearance is a strong plus.")
    assert result["current_policy"] == "UNKNOWN"


def test_ability_to_obtain_clearance_remains_unknown() -> None:
    """Future clearance eligibility is not an existing-clearance requirement."""

    result = classify_description(
        "Candidate must be able to obtain a Secret security clearance."
    )
    assert result["current_policy"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# H-1B transfer evidence
# ---------------------------------------------------------------------------

def test_h1b_transfer_is_stored_separately() -> None:
    """Transfer support must not override refusal of new H-1B sponsorship."""

    result = classify_description(
        "H-1B transfer candidates are encouraged to apply. "
        "We are unable to sponsor new H-1B petitions."
    )

    assert result["current_policy"] == "UNAVAILABLE"
    assert result["h1b_transfer_supported"] is True

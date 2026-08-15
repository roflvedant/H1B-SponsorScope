"""Administrative helper for reviewing possible company aliases.

Fuzzy results from this module are suggestions only. The matching pipeline reads
only manually verified aliases from data/references/company_aliases.csv.
"""

from difflib import SequenceMatcher

from app.enrichment.historical import normalize_company


def company_similarity(left, right):
    left_key = normalize_company(left)
    right_key = normalize_company(right)
    return round(SequenceMatcher(None, left_key, right_key).ratio() * 100, 2)

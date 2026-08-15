"""Transform raw DOL LCA disclosure data into matching-ready history.

The raw Department of Labor workbook contains individual case records. This
module filters that source to certified H-1B filings, normalizes employer and
occupation names, and aggregates repeated cases into a compact CSV used by the
historical matching layer.

The output represents past certified activity. It is supporting evidence and
must not be interpreted as a guarantee that a current posting offers
sponsorship.
"""

import re

import pandas as pd

from app.config.settings import PROCESSED_DIRECTORY, RAW_DOL_DIRECTORY


# ---------------------------------------------------------------------------
# Normalization configuration
# ---------------------------------------------------------------------------

# Legal suffixes generally describe company structure rather than identity.
# Removing them lets names such as "Google LLC" and "Google" share one key.
LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "corp",
    "corporation",
    "company",
    "co",
    "llp",
    "plc",
}

# Seniority terms usually do not change the underlying occupation. Removing
# them allows titles such as "Senior Data Engineer" and "Data Engineer" to
# share a core title while later matching layers still enforce confidence rules.
IGNORED_TITLE_WORDS = {
    "senior",
    "sr",
    "junior",
    "jr",
    "lead",
    "principal",
    "manager",
}


# ---------------------------------------------------------------------------
# Shared normalization functions
# ---------------------------------------------------------------------------

def normalize_company(value: object) -> str:
    """Convert an employer name into a stable comparison key."""

    if value is None or pd.isna(value):
        return ""

    words = re.sub(
        r"[^a-z0-9\s]",
        " ",
        str(value).lower(),
    ).split()

    return " ".join(
        word for word in words if word not in LEGAL_SUFFIXES
    )


def normalize_job_title(value: object) -> str:
    """Convert a job title into a lowercase, punctuation-free core title."""

    if value is None or pd.isna(value):
        return ""

    normalized_text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        str(value).lower(),
    )

    return " ".join(
        word
        for word in normalized_text.split()
        if word not in IGNORED_TITLE_WORDS
    )


# ---------------------------------------------------------------------------
# Source-file discovery
# ---------------------------------------------------------------------------

def find_latest_dol_file():
    """Return the most recently modified DOL LCA disclosure workbook."""

    source_files = list(
        RAW_DOL_DIRECTORY.glob("LCA_Disclosure_Data_*.xlsx")
    )
    if not source_files:
        raise FileNotFoundError("No DOL LCA Excel file was found.")

    return max(
        source_files,
        key=lambda file: file.stat().st_mtime,
    )


# ---------------------------------------------------------------------------
# Historical transformation pipeline
# ---------------------------------------------------------------------------

def run_historical_transformation():
    """Create aggregated certified H-1B history from the newest DOL workbook."""

    source_file = find_latest_dol_file()
    print("Reading DOL data from:", source_file)

    # Reading only required columns lowers memory use for the large disclosure
    # workbook and documents the exact raw schema used by this transformation.
    source_columns = [
        "CASE_NUMBER",
        "CASE_STATUS",
        "VISA_CLASS",
        "EMPLOYER_NAME",
        "JOB_TITLE",
        "SOC_CODE",
        "SOC_TITLE",
        "TOTAL_WORKER_POSITIONS",
    ]
    data = pd.read_excel(
        source_file,
        usecols=source_columns,
        engine="openpyxl",
    )

    # Only certified H-1B LCA records constitute positive historical evidence.
    # Other visa classes and non-certified outcomes are excluded.
    certified_h1b = (
        data["VISA_CLASS"].astype(str).str.upper().eq("H-1B")
        & data["CASE_STATUS"].astype(str).str.upper().eq("CERTIFIED")
    )
    data = data[certified_h1b].copy()

    data["company_key"] = data["EMPLOYER_NAME"].apply(
        normalize_company
    )
    data["job_title_key"] = data["JOB_TITLE"].apply(
        normalize_job_title
    )
    data["TOTAL_WORKER_POSITIONS"] = pd.to_numeric(
        data["TOTAL_WORKER_POSITIONS"],
        errors="coerce",
    ).fillna(0)

    # Aggregate identical employer/title/SOC combinations. Case counts and
    # requested worker positions carry different meanings, so both are saved.
    grouped = (
        data.groupby(
            [
                "company_key",
                "job_title_key",
                "EMPLOYER_NAME",
                "JOB_TITLE",
                "SOC_CODE",
                "SOC_TITLE",
            ],
            dropna=False,
        )
        .agg(
            certified_lca_cases=("CASE_NUMBER", "nunique"),
            worker_positions=("TOTAL_WORKER_POSITIONS", "sum"),
        )
        .reset_index()
    )

    grouped = grouped.rename(
        columns={
            "EMPLOYER_NAME": "dol_employer_name",
            "JOB_TITLE": "dol_job_title",
        }
    )

    output_file = PROCESSED_DIRECTORY / "dol_h1b_history_2025.csv"
    grouped.to_csv(output_file, index=False)

    print("Historical data saved to:", output_file)
    return output_file
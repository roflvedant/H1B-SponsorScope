"""Coordinate the four batch-processing stages in their required order.

The runner contains orchestration only. Each stage keeps its implementation in
its own module, making this file an easy-to-read overview of the full pipeline.
"""

from __future__ import annotations

from pathlib import Path

from app.config.settings import PROCESSED_DIRECTORY
from app.enrichment.classification import run_classification
from app.enrichment.historical import run_historical_transformation
from app.enrichment.matching import run_historical_matching
from app.pipeline.transformation import run_transformation


# ---------------------------------------------------------------------------
# Reusable processed datasets
# ---------------------------------------------------------------------------

# DOL transformation is expensive because it reads a large Excel workbook.
# Reuse the processed CSV when it already exists. Delete that CSV intentionally
# when a newly downloaded DOL source must be processed.
DOL_HISTORY_FILE: Path = (
    PROCESSED_DIRECTORY / "dol_h1b_history_2025.csv"
)


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------

def run_pipeline() -> Path:
    """Run transformation and enrichment, returning the final JSON path."""

    print("[1/4] Preparing historical DOL data")
    if not DOL_HISTORY_FILE.exists():
        run_historical_transformation()
    else:
        print("Processed DOL history exists; skipping Excel processing.")

    print("\n[2/4] Normalizing, filtering and deduplicating jobs")
    run_transformation()

    print("\n[3/4] Classifying current sponsorship language")
    run_classification()

    print("\n[4/4] Matching historical H-1B evidence")
    return run_historical_matching()
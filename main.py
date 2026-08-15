"""Command-line entry point for the local batch-processing pipeline.

Run ``fetch_main.py`` first when a new raw JSearch snapshot is required. This
script processes the newest existing snapshot through normalization,
classification, and historical matching. Database loading is handled by
``load_database.py`` as a separate, explicit step.
"""

from app.pipeline.runner import run_pipeline


def main() -> None:
    """Run every batch-processing stage in the required order."""

    run_pipeline()


if __name__ == "__main__":
    main()
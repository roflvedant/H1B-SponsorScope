"""Command-line entry point for fetching raw jobs from JSearch.

This command performs extraction only. It saves a timestamped raw snapshot but
does not normalize, classify, historically match, or load jobs into PostgreSQL.

Examples:
    python fetch_main.py
    python fetch_main.py --query "data engineer jobs in USA" --pages 2
    python fetch_main.py --query "data engineer" --query "ETL engineer"
"""

from __future__ import annotations

import argparse

from app.extraction.jsearch import run_ingestion


# ---------------------------------------------------------------------------
# Command-line argument parsing
# ---------------------------------------------------------------------------

def positive_integer(value: str) -> int:
    """Parse a command-line value that must be a positive integer."""

    parsed_value = int(value)
    if parsed_value < 1:
        raise argparse.ArgumentTypeError(
            "The number of pages must be at least 1."
        )
    return parsed_value


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for JSearch ingestion options."""

    parser = argparse.ArgumentParser(
        description="Fetch raw job postings from JSearch."
    )
    parser.add_argument(
        "--query",
        action="append",
        help=(
            "Search query to fetch. Repeat --query to fetch multiple "
            "searches. The configured default is used when omitted."
        ),
    )
    parser.add_argument(
        "--pages",
        type=positive_integer,
        default=3,
        help="Maximum pages to fetch per query (default: 3).",
    )
    return parser


# ---------------------------------------------------------------------------
# Program entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI arguments and run the extraction stage."""

    arguments = build_parser().parse_args()
    run_ingestion(
        queries=arguments.query,
        max_pages=arguments.pages,
    )


if __name__ == "__main__":
    main()
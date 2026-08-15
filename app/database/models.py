"""SQLAlchemy models for jobs, search lineage, and sponsorship evidence.

The schema separates stable entities (companies and jobs) from versioned
analysis results. A job can therefore be reclassified or rematched by a newer
algorithm without deleting the evidence produced by an earlier version.

PostgreSQL-specific UUID and JSONB types provide compact identifiers and retain
the structured evidence needed for auditing and user-facing explanations.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


# ---------------------------------------------------------------------------
# Shared timestamp behavior
# ---------------------------------------------------------------------------

class TimestampMixin:
    """Add server-generated creation and update timestamps to a model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Search provenance
# ---------------------------------------------------------------------------

class SearchQuery(TimestampMixin, Base):
    """A normalized user query and the time its results were last refreshed."""

    __tablename__ = "search_queries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    raw_query: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
    )
    location_text: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(
        String(2),
        default="US",
        nullable=False,
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Deleting a query also deletes its lineage links, not the underlying jobs.
    results: Mapped[list["SearchResult"]] = relationship(
        back_populates="search_query",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# Canonical companies and aliases
# ---------------------------------------------------------------------------

class Company(TimestampMixin, Base):
    """A canonical employer shared by multiple job postings and aliases."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    canonical_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    normalized_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        unique=True,
        index=True,
    )
    website_domain: Mapped[str | None] = mapped_column(
        String(255),
        index=True,
    )

    aliases: Mapped[list["CompanyAlias"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    jobs: Mapped[list["JobPosting"]] = relationship(
        back_populates="company"
    )


class CompanyAlias(TimestampMixin, Base):
    """A reviewed employer-name variant mapped to a canonical company."""

    __tablename__ = "company_aliases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias_name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[str] = mapped_column(
        String(50),
        default="SAME_ENTITY",
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(100),
        default="MANUAL_REVIEW",
        nullable=False,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    reviewed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    company: Mapped["Company"] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint(
            "normalized_alias",
            "company_id",
            name="uq_company_alias",
        ),
    )


# ---------------------------------------------------------------------------
# Canonical job postings
# ---------------------------------------------------------------------------

class JobPosting(TimestampMixin, Base):
    """A deduplicated job posting identified by provider and provider job ID."""

    __tablename__ = "job_postings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_job_id: Mapped[str] = mapped_column(String(500), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"),
        index=True,
    )
    source_company_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(2))
    employment_type: Mapped[str | None] = mapped_column(String(100))
    apply_url: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )

    # Retaining the provider object supports debugging and future reprocessing.
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    company: Mapped["Company | None"] = relationship(back_populates="jobs")
    search_results: Mapped[list["SearchResult"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )
    classifications: Mapped[
        list["SponsorshipClassification"]
    ] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )
    historical_evidence: Mapped[
        list["HistoricalSponsorshipEvidence"]
    ] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_job_id",
            name="uq_job_source_identifier",
        ),
    )


# ---------------------------------------------------------------------------
# Pipeline observability and query-to-job lineage
# ---------------------------------------------------------------------------

class PipelineRun(Base):
    """Operational metadata for one batch or live pipeline execution."""

    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    run_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default="RUNNING",
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    fetched_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    stored_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    error_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SearchResult(Base):
    """A lineage link showing that a job appeared for a particular query."""

    __tablename__ = "search_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    search_query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search_queries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"),
        index=True,
    )
    source_rank: Mapped[int | None] = mapped_column(Integer)
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    relevance_method: Mapped[str | None] = mapped_column(String(100))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    search_query: Mapped["SearchQuery"] = relationship(
        back_populates="results"
    )
    job: Mapped["JobPosting"] = relationship(
        back_populates="search_results"
    )

    # The same job may appear once per query, never twice for that query.
    __table_args__ = (
        UniqueConstraint(
            "search_query_id",
            "job_id",
            name="uq_search_query_job",
        ),
    )


# ---------------------------------------------------------------------------
# Versioned sponsorship analysis
# ---------------------------------------------------------------------------

class SponsorshipClassification(Base):
    """One versioned current-posting sponsorship decision for a job."""

    __tablename__ = "sponsorship_classifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    policy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    classifier_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    citizenship_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    security_clearance_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    h1b_transfer_supported: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    requires_human_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    job: Mapped["JobPosting"] = relationship(
        back_populates="classifications"
    )

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "classifier_version",
            name="uq_job_classifier_version",
        ),
    )


class HistoricalSponsorshipEvidence(Base):
    """One versioned employer-and-occupation DOL match for a job."""

    __tablename__ = "historical_sponsorship_evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    historical_support: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    employer_match_type: Mapped[str | None] = mapped_column(String(100))
    occupation_match_type: Mapped[str | None] = mapped_column(String(100))
    matched_dol_employer: Mapped[str | None] = mapped_column(String(500))
    matched_dol_job_title: Mapped[str | None] = mapped_column(String(500))
    matched_soc_code: Mapped[str | None] = mapped_column(String(20))
    matched_soc_title: Mapped[str | None] = mapped_column(String(500))
    certified_lca_cases: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    worker_positions: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    requires_human_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    matching_version: Mapped[str] = mapped_column(
        String(50),
        default="historical-v3",
        nullable=False,
    )

    # The payload retains accepted, rejected, and review-candidate explanations.
    evidence_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    job: Mapped["JobPosting"] = relationship(
        back_populates="historical_evidence"
    )

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "matching_version",
            name="uq_job_historical_matching_version",
        ),
    )
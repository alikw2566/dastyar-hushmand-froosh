import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    supervisor = "supervisor"
    seller = "seller"
    agent = "agent"
    viewer = "viewer"


class CallStatus(str, enum.Enum):
    discovered = "discovered"
    waiting_for_file = "waiting_for_file"
    received = "received"
    uploaded = "uploaded"
    queued = "queued"
    preprocessing = "preprocessing"
    diarizing = "diarizing"
    transcribing = "transcribing"
    assigning_roles = "assigning_roles"
    analyzing = "analyzing"
    validating = "validating"
    creating_followups = "creating_followups"
    review_needed = "review_needed"
    completed = "completed"
    retry_scheduled = "retry_scheduled"
    failed = "failed"
    quarantined = "quarantined"


class CallOutcome(str, enum.Enum):
    won = "won"
    lost = "lost"
    follow_up = "follow_up"
    unknown = "unknown"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(180))
    plan: Mapped[str] = mapped_column(String(32), default="free")
    monthly_minute_limit: Mapped[int] = mapped_column(Integer, default=120)
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    automation_mode: Mapped[str] = mapped_column(String(24), default="approval")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False))
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    supervisor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_call_external"),
        Index("ix_calls_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(180), default="در انتظار استخراج")
    seller_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    seller_name: Mapped[str] = mapped_column(String(180), default="در انتظار تشخیص")
    original_file_name: Mapped[str] = mapped_column(String(500))
    object_key: Mapped[str] = mapped_column(String(900), unique=True)
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(24), default="upload")
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus, native_enum=False), default=CallStatus.queued
    )
    outcome: Mapped[CallOutcome] = mapped_column(
        Enum(CallOutcome, native_enum=False), default=CallOutcome.unknown
    )
    outcome_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    analysis_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    call_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    caller_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent_extension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    queue_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    manually_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    latest_transcript_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    latest_analysis_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reviewed_analysis_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    published_analysis_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    extraction: Mapped["CallExtraction | None"] = relationship(
        back_populates="call", cascade="all, delete-orphan", uselist=False
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (Index("ix_segments_call_position", "call_id", "position", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    speaker_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    speaker_label: Mapped[str] = mapped_column(String(80))
    speaker_role: Mapped[str] = mapped_column(String(24), default="unknown")
    speaker_role_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text, default="")
    edited_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    is_manually_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    correction_user_id: Mapped[str | None] = mapped_column(String(320), nullable=True)
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    call: Mapped[Call] = relationship(back_populates="segments")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "call_id", "dedupe_key", name="uq_task_call_dedupe"),
        Index("ix_tasks_followup_due", "tenant_id", "status", "due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL")
    )
    customer_name: Mapped[str] = mapped_column(String(180))
    title: Mapped[str] = mapped_column(String(300))
    assignee_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    priority: Mapped[str] = mapped_column(String(24), default="normal")
    status: Mapped[str] = mapped_column(String(24), default="open")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_suggested: Mapped[bool] = mapped_column(Boolean, default=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    task_type: Mapped[str] = mapped_column(String(40), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageDraft(Base):
    __tablename__ = "message_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(20))
    recipient_masked: Mapped[str | None] = mapped_column(String(160), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending_approval")
    approved_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    actor_email: Mapped[str] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScorecardVersion(Base):
    __tablename__ = "scorecard_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(180))
    criteria_json: Mapped[list] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(200))
    event: Mapped[str] = mapped_column(String(100))
    conditions_json: Mapped[dict] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(24), default="approval")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageLedger(Base):
    __tablename__ = "usage_ledger"
    __table_args__ = (Index("ix_usage_tenant_period", "tenant_id", "period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    period: Mapped[str] = mapped_column(String(7))
    metric: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiSetting(Base):
    __tablename__ = "ai_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    transcription_model: Mapped[str] = mapped_column(
        String(120), default="gpt-4o-transcribe-diarize"
    )
    analysis_model: Mapped[str] = mapped_column(String(120), default="gpt-4o")
    min_confidence: Mapped[float] = mapped_column(Float, default=0.75)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SecuritySetting(Base):
    __tablename__ = "security_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), primary_key=True
    )
    require_consent: Mapped[bool] = mapped_column(Boolean, default=True)
    audio_download_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SourceImport(Base):
    """Immutable provenance for every file seen by the Issabel watcher."""

    __tablename__ = "source_imports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_identifier", name="uq_source_import_identifier"),
        UniqueConstraint("tenant_id", "sha256", name="uq_source_import_hash"),
        Index("ix_source_import_status", "tenant_id", "status", "detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL"), nullable=True
    )
    source_identifier: Mapped[str] = mapped_column(String(1500))
    source_path: Mapped[str] = mapped_column(String(1500))
    file_name: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_size: Mapped[int] = mapped_column(BigInteger, default=0)
    observed_mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    stable_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="discovered")
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"
    __table_args__ = (Index("ix_pipeline_events_call_created", "call_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    from_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_state: Mapped[str] = mapped_column(String(40))
    stage: Mapped[str] = mapped_column(String(40))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessingError(Base):
    __tablename__ = "processing_errors"
    __table_args__ = (Index("ix_processing_errors_call_created", "call_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=True
    )
    stage: Mapped[str] = mapped_column(String(40))
    code: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(40))
    transient: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    message: Mapped[str] = mapped_column(Text)
    exception_type: Mapped[str | None] = mapped_column(String(180), nullable=True)
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatcherHeartbeat(Base):
    __tablename__ = "watcher_heartbeats"

    watcher_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    host: Mapped[str] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="healthy")
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CallExtraction(Base):
    __tablename__ = "call_extractions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "call_id", name="uq_call_extraction"),
        Index("ix_extraction_filters", "tenant_id", "company", "city", "product"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    customer_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    alternate_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    company: Mapped[str | None] = mapped_column(String(240), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    province: Mapped[str | None] = mapped_column(String(120), nullable=True)
    product: Mapped[str | None] = mapped_column(String(240), nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(180), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    exact_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    requested_discount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(24), nullable=True)
    followup_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    followup_required: Mapped[bool] = mapped_column(Boolean, default=False)
    sales_stage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lead_temperature: Mapped[str | None] = mapped_column(String(24), nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(24), nullable=True)
    risk_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    competitor_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    purchase_timeline: Mapped[str | None] = mapped_column(String(240), nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    pain_points_json: Mapped[list] = mapped_column(JSON, default=list)
    objections_json: Mapped[list] = mapped_column(JSON, default=list)
    commitments_json: Mapped[list] = mapped_column(JSON, default=list)
    strengths_json: Mapped[list] = mapped_column(JSON, default=list)
    weaknesses_json: Mapped[list] = mapped_column(JSON, default=list)
    coaching_json: Mapped[list] = mapped_column(JSON, default=list)
    score_breakdown_json: Mapped[list] = mapped_column(JSON, default=list)
    need: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_text: Mapped[str | None] = mapped_column(String(240), nullable=True)
    promise_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_status: Mapped[str] = mapped_column(String(32), default="unvalidated")
    manually_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    manually_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    call: Mapped[Call] = relationship(back_populates="extraction")


class ExtractionEvidence(Base):
    __tablename__ = "extraction_evidence"
    __table_args__ = (Index("ix_extraction_evidence_call_field", "call_id", "field_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_extractions.id", ondelete="CASCADE")
    )
    field_name: Mapped[str] = mapped_column(String(80))
    value_text: Mapped[str] = mapped_column(Text)
    segment_position: Mapped[int] = mapped_column(Integer)
    source_segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_segments.id", ondelete="SET NULL"), nullable=True
    )
    source_segment_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    quote: Mapped[str] = mapped_column(Text)
    timestamp_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    supported: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_method: Mapped[str] = mapped_column(String(32), default="ai")
    validation_status: Mapped[str] = mapped_column(String(32), default="unsupported")


class TranscriptCorrection(Base):
    __tablename__ = "transcript_corrections"
    __table_args__ = (Index("ix_corrections_call_created", "call_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_segments.id", ondelete="CASCADE")
    )
    actor_email: Mapped[str] = mapped_column(String(320))
    old_content: Mapped[str] = mapped_column(Text)
    new_content: Mapped[str] = mapped_column(Text)
    old_role: Mapped[str] = mapped_column(String(24))
    new_role: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"
    __table_args__ = (UniqueConstraint("tenant_id", "normalized_term", name="uq_glossary_term"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    term: Mapped[str] = mapped_column(String(240))
    normalized_term: Mapped[str] = mapped_column(String(240))
    category: Mapped[str] = mapped_column(String(40), default="general")
    aliases_json: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TranscriptVersion(Base):
    __tablename__ = "transcript_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "call_id", "version_number", name="uq_transcript_version"),
        Index("ix_transcript_versions_call_created", "call_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="ai")
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TranscriptVersionSegment(Base):
    __tablename__ = "transcript_version_segments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "transcript_version_id", "position", name="uq_version_segment"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    transcript_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_versions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    speaker_id: Mapped[str] = mapped_column(String(80), default="unknown")
    speaker_label: Mapped[str] = mapped_column(String(80), default="unknown")
    speaker_role: Mapped[str] = mapped_column(String(24), default="unknown")
    role_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text, default="")


class AnalysisVersion(Base):
    __tablename__ = "analysis_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "call_id", "version_number", name="uq_analysis_version"),
        Index("ix_analysis_versions_call_created", "call_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    transcript_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_versions.id", ondelete="RESTRICT")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    provider: Mapped[str] = mapped_column(String(40), default="openai")
    transcription_model: Mapped[str] = mapped_column(String(120))
    analysis_model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(80))
    scorecard_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    pipeline_version: Mapped[str] = mapped_column(String(40), default="a1-v1")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str] = mapped_column(String(32), default="unknown")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisEvidence(Base):
    __tablename__ = "analysis_evidence"
    __table_args__ = (
        Index("ix_analysis_evidence_version_segment", "analysis_version_id", "segment_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    analysis_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_versions.id", ondelete="CASCADE"), index=True
    )
    segment_index: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    timestamp_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    supported: Mapped[bool] = mapped_column(Boolean)
    similarity: Mapped[float] = mapped_column(Float)
    validation_reason: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewCase(Base):
    __tablename__ = "review_cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "analysis_version_id", name="uq_review_analysis_version"),
        Index("ix_review_queue", "tenant_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    analysis_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_versions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(32), default="queued_for_review")
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    assignee_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReviewEvent(Base):
    __tablename__ = "review_events"
    __table_args__ = (Index("ix_review_events_case_created", "review_case_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    review_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_cases.id", ondelete="CASCADE"), index=True
    )
    actor_email: Mapped[str] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublicationEvent(Base):
    __tablename__ = "publication_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    analysis_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_versions.id", ondelete="RESTRICT")
    )
    actor_email: Mapped[str] = mapped_column(String(320))
    publication_type: Mapped[str] = mapped_column(String(32), default="human_approved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "analysis_version_id",
            "format",
            "version_number",
            name="uq_artifact_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE")
    )
    analysis_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_versions.id", ondelete="CASCADE")
    )
    format: Mapped[str] = mapped_column(String(16))
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    object_key: Mapped[str | None] = mapped_column(String(900), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RetentionJob(Base):
    __tablename__ = "retention_jobs"
    __table_args__ = (Index("ix_retention_jobs_tenant_status", "tenant_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    object_key: Mapped[str] = mapped_column(String(900))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CdrMatch(Base):
    __tablename__ = "cdr_matches"
    __table_args__ = (Index("ix_cdr_matches_call_status", "call_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24))
    match_method: Mapped[str] = mapped_column(String(40), default="none")
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    uniqueid: Mapped[str | None] = mapped_column(String(160), nullable=True)
    cdr_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

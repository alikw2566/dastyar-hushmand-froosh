"""add pilot processing, Issabel provenance and structured extraction

Revision ID: 20260801_01
Revises:
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260801_01"
down_revision = None
branch_labels = None
depends_on = None


def _apply_rls() -> None:
    for table_name in (
        "memberships",
        "calls",
        "transcript_segments",
        "tasks",
        "message_drafts",
        "audit_logs",
        "integrations",
        "scorecard_versions",
        "automation_rules",
        "usage_ledger",
        "teams",
        "ai_settings",
        "security_settings",
        "source_imports",
        "pipeline_events",
        "processing_errors",
        "watcher_heartbeats",
        "call_extractions",
        "extraction_evidence",
        "transcript_corrections",
        "glossary_terms",
    ):
        op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(f'DROP POLICY IF EXISTS tenant_isolation_{table_name} ON "{table_name}"')
        )
        op.execute(
            sa.text(
                f'CREATE POLICY tenant_isolation_{table_name} ON "{table_name}" '
                "USING (tenant_id = current_setting('app.tenant_id', true)::uuid) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)"
            )
        )


def upgrade() -> None:
    # Bootstrap a new database from the versioned metadata snapshot. Existing
    # installations take the additive path below and retain every existing row.
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("calls"):
        from app.models import Base

        Base.metadata.create_all(bind=bind)
        _apply_rls()
        return
    call_columns = (
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("source_path", sa.String(1200), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("call_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("caller_number", sa.String(64), nullable=True),
        sa.Column("destination_number", sa.String(64), nullable=True),
        sa.Column("extension", sa.String(32), nullable=True),
        sa.Column("agent_extension", sa.String(32), nullable=True),
        sa.Column("direction", sa.String(16), nullable=True),
        sa.Column("queue_name", sa.String(120), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_stage", sa.String(40), nullable=True),
        sa.Column("manually_corrected", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for column in call_columns:
        op.add_column("calls", column)
    op.add_column("transcript_segments", sa.Column("speaker_id", sa.String(80), nullable=True))
    op.add_column(
        "transcript_segments", sa.Column("speaker_role_confidence", sa.Float(), nullable=True)
    )
    op.add_column(
        "transcript_segments",
        sa.Column("normalized_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "transcript_segments",
        sa.Column("is_manually_corrected", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "transcript_segments", sa.Column("correction_user_id", sa.String(320), nullable=True)
    )
    op.add_column(
        "transcript_segments", sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "transcript_segments",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column(
        "transcript_segments",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column("tasks", sa.Column("dedupe_key", sa.String(160), nullable=True))
    op.add_column(
        "tasks", sa.Column("task_type", sa.String(40), nullable=False, server_default="manual")
    )
    op.create_unique_constraint(
        "uq_task_call_dedupe", "tasks", ["tenant_id", "call_id", "dedupe_key"]
    )
    op.create_index("ix_tasks_followup_due", "tasks", ["tenant_id", "status", "due_at"])

    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "source_imports",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column("call_id", uuid_type, sa.ForeignKey("calls.id", ondelete="SET NULL")),
        sa.Column("source_identifier", sa.String(1500), nullable=False),
        sa.Column("source_path", sa.String(1500), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("observed_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("observed_mtime_ns", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("stable_since", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True)),
        sa.Column("quarantine_path", sa.String(1500)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.UniqueConstraint("tenant_id", "source_identifier", name="uq_source_import_identifier"),
        sa.UniqueConstraint("tenant_id", "sha256", name="uq_source_import_hash"),
    )
    op.create_index(
        "ix_source_import_status", "source_imports", ["tenant_id", "status", "detected_at"]
    )
    op.create_table(
        "pipeline_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column(
            "call_id", uuid_type, sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("from_state", sa.String(40)),
        sa.Column("to_state", sa.String(40), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pipeline_events_call_created", "pipeline_events", ["call_id", "created_at"])
    op.create_table(
        "processing_errors",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column("call_id", uuid_type, sa.ForeignKey("calls.id", ondelete="CASCADE")),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("transient", sa.Boolean(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("exception_type", sa.String(180)),
        sa.Column("context_json", sa.JSON()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_processing_errors_call_created", "processing_errors", ["call_id", "created_at"]
    )
    op.create_table(
        "watcher_heartbeats",
        sa.Column("watcher_id", sa.String(160), primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_scan_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "call_extractions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column(
            "call_id", uuid_type, sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("customer_name", sa.String(180)),
        sa.Column("phone", sa.String(64)),
        sa.Column("alternate_phone", sa.String(64)),
        sa.Column("company", sa.String(240)),
        sa.Column("address", sa.Text()),
        sa.Column("customer_type", sa.String(80)),
        sa.Column("city", sa.String(120)),
        sa.Column("province", sa.String(120)),
        sa.Column("product", sa.String(240)),
        sa.Column("product_category", sa.String(180)),
        sa.Column("quantity", sa.Float()),
        sa.Column("unit", sa.String(40)),
        sa.Column("amount", sa.Float()),
        sa.Column("exact_amount", sa.Float()),
        sa.Column("budget_min", sa.Float()),
        sa.Column("budget_max", sa.Float()),
        sa.Column("requested_discount", sa.Float()),
        sa.Column("currency", sa.String(24)),
        sa.Column("followup_due_at", sa.DateTime(timezone=True)),
        sa.Column("followup_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sales_stage", sa.String(80)),
        sa.Column("lead_temperature", sa.String(24)),
        sa.Column("sentiment", sa.String(24)),
        sa.Column("risk_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("competitor_name", sa.String(240)),
        sa.Column("purchase_timeline", sa.String(240)),
        sa.Column("lost_reason", sa.Text()),
        sa.Column("purchase_probability", sa.Float()),
        sa.Column("pain_points_json", sa.JSON(), nullable=False),
        sa.Column("objections_json", sa.JSON(), nullable=False),
        sa.Column("commitments_json", sa.JSON(), nullable=False),
        sa.Column("strengths_json", sa.JSON(), nullable=False),
        sa.Column("weaknesses_json", sa.JSON(), nullable=False),
        sa.Column("coaching_json", sa.JSON(), nullable=False),
        sa.Column("score_breakdown_json", sa.JSON(), nullable=False),
        sa.Column("need", sa.Text()),
        sa.Column("budget_text", sa.String(240)),
        sa.Column("promise_text", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("validated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("validation_status", sa.String(32), nullable=False, server_default="unvalidated"),
        sa.Column("manually_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("manually_corrected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "call_id", name="uq_call_extraction"),
    )
    op.create_index(
        "ix_extraction_filters", "call_extractions", ["tenant_id", "company", "city", "product"]
    )
    op.create_table(
        "extraction_evidence",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column(
            "call_id", uuid_type, sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "extraction_id",
            uuid_type,
            sa.ForeignKey("call_extractions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column("segment_position", sa.Integer(), nullable=False),
        sa.Column(
            "source_segment_id",
            uuid_type,
            sa.ForeignKey("transcript_segments.id", ondelete="SET NULL"),
        ),
        sa.Column("source_segment_ids_json", sa.JSON(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("timestamp_seconds", sa.Float()),
        sa.Column("end_time_seconds", sa.Float()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column("extraction_method", sa.String(32), nullable=False),
        sa.Column("validation_status", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_extraction_evidence_call_field", "extraction_evidence", ["call_id", "field_name"]
    )
    op.create_table(
        "transcript_corrections",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column(
            "call_id", uuid_type, sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "segment_id",
            uuid_type,
            sa.ForeignKey("transcript_segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_email", sa.String(320), nullable=False),
        sa.Column("old_content", sa.Text(), nullable=False),
        sa.Column("new_content", sa.Text(), nullable=False),
        sa.Column("old_role", sa.String(24), nullable=False),
        sa.Column("new_role", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_corrections_call_created", "transcript_corrections", ["call_id", "created_at"]
    )
    op.create_table(
        "glossary_terms",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column("term", sa.String(240), nullable=False),
        sa.Column("normalized_term", sa.String(240), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "normalized_term", name="uq_glossary_term"),
    )
    _apply_rls()


def downgrade() -> None:
    for table in (
        "glossary_terms",
        "transcript_corrections",
        "extraction_evidence",
        "call_extractions",
        "watcher_heartbeats",
        "processing_errors",
        "pipeline_events",
        "source_imports",
    ):
        op.drop_table(table)
    op.drop_index("ix_tasks_followup_due", table_name="tasks")
    op.drop_constraint("uq_task_call_dedupe", "tasks", type_="unique")
    for column in ("task_type", "dedupe_key"):
        op.drop_column("tasks", column)
    for column in (
        "updated_at",
        "created_at",
        "corrected_at",
        "correction_user_id",
        "is_manually_corrected",
        "normalized_text",
        "speaker_role_confidence",
        "speaker_id",
    ):
        op.drop_column("transcript_segments", column)
    for column in (
        "manually_corrected",
        "last_successful_stage",
        "next_retry_at",
        "retry_count",
        "queue_name",
        "direction",
        "agent_extension",
        "extension",
        "destination_number",
        "caller_number",
        "call_started_at",
        "imported_at",
        "detected_at",
        "source_hash",
        "source_path",
        "error_code",
    ):
        op.drop_column("calls", column)

"""add immutable AI versions and human review workflow

Revision ID: 20260802_02
Revises: 20260801_01
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_02"
down_revision = "20260801_01"
branch_labels = None
depends_on = None

VERSION_TABLES = (
    "transcript_versions",
    "transcript_version_segments",
    "analysis_versions",
    "analysis_evidence",
    "review_cases",
    "review_events",
    "publication_events",
    "artifact_versions",
    "retention_jobs",
    "cdr_matches",
)


def upgrade() -> None:
    from app.models import Base

    bind = op.get_bind()
    for name in VERSION_TABLES:
        Base.metadata.tables[name].create(bind=bind, checkfirst=True)
    for name in (
        "latest_transcript_version_id",
        "latest_analysis_version_id",
        "reviewed_analysis_version_id",
        "published_analysis_version_id",
    ):
        op.add_column("calls", sa.Column(name, sa.UUID(), nullable=True))

    # Existing mutable output becomes immutable version 1. New processing uses
    # the application service, so this migration is safe to run before workers.
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    op.execute(
        sa.text("""
        INSERT INTO transcript_versions
          (id, tenant_id, call_id, version_number, source, change_reason)
        SELECT gen_random_uuid(), tenant_id, id, 1, 'migration', 'initial version from legacy rows'
        FROM calls
        """)
    )
    op.execute(
        sa.text("""
        INSERT INTO transcript_version_segments
          (id, tenant_id, transcript_version_id, position, speaker_id, speaker_label,
           speaker_role, role_confidence, start_seconds, end_seconds, content, normalized_text)
        SELECT gen_random_uuid(), s.tenant_id, v.id, s.position,
               COALESCE(s.speaker_id, s.speaker_label, 'unknown'), s.speaker_label,
               s.speaker_role, s.speaker_role_confidence, s.start_seconds, s.end_seconds,
               s.content, s.normalized_text
        FROM transcript_segments s
        JOIN transcript_versions v ON v.call_id = s.call_id AND v.version_number = 1
        """)
    )
    op.execute(
        sa.text("""
        INSERT INTO analysis_versions
          (id, tenant_id, call_id, transcript_version_id, version_number, status, provider,
           transcription_model, analysis_model, prompt_version, pipeline_version, confidence,
           evidence_validated, outcome, score, analysis_json, created_by)
        SELECT gen_random_uuid(), c.tenant_id, c.id, v.id, 1, 'draft', 'openai',
               'legacy', 'legacy', COALESCE(c.analysis_version, 'legacy'), 'legacy-v1',
               x.confidence, COALESCE(x.validated, false), c.outcome, c.score,
               COALESCE(c.analysis_json, '{}'::json), 'migration'
        FROM calls c
        JOIN transcript_versions v ON v.call_id = c.id AND v.version_number = 1
        LEFT JOIN call_extractions x ON x.call_id = c.id
        WHERE c.analysis_json IS NOT NULL
        """)
    )
    op.execute(
        sa.text("""
        UPDATE calls c SET
          latest_transcript_version_id = tv.id,
          latest_analysis_version_id = av.id
        FROM transcript_versions tv
        LEFT JOIN analysis_versions av ON av.call_id = tv.call_id AND av.version_number = 1
        WHERE tv.call_id = c.id AND tv.version_number = 1
        """)
    )
    op.execute(
        sa.text("""
        INSERT INTO review_cases
          (id, tenant_id, call_id, analysis_version_id, status, reasons_json, review_required)
        SELECT gen_random_uuid(), tenant_id, call_id, id, 'queued_for_review',
               '["legacy_unreviewed"]'::json, true
        FROM analysis_versions
        """)
    )

    # A migration connection has no request tenant context. Enabling FORCE RLS
    # before the backfill would therefore hide all legacy rows from the SQL
    # above. Isolation is enabled after the one-time migration completes.
    for name in VERSION_TABLES:
        op.execute(sa.text(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE POLICY tenant_isolation_{name} ON "{name}" '
                "USING (tenant_id = current_setting('app.tenant_id', true)::uuid) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)"
            )
        )


def downgrade() -> None:
    for name in (
        "published_analysis_version_id",
        "reviewed_analysis_version_id",
        "latest_analysis_version_id",
        "latest_transcript_version_id",
    ):
        op.drop_column("calls", name)
    for name in reversed(VERSION_TABLES):
        op.drop_table(name)

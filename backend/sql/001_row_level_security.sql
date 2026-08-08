-- The API sets app.tenant_id for every transaction. FORCE ensures even the
-- table owner cannot accidentally bypass tenant isolation in normal queries.
DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'memberships', 'calls', 'transcript_segments', 'tasks', 'message_drafts', 'audit_logs',
    'scorecard_versions', 'automation_rules', 'usage_ledger',
    'teams', 'ai_settings', 'security_settings', 'source_imports', 'pipeline_events',
    'processing_errors', 'watcher_heartbeats', 'call_extractions', 'extraction_evidence',
    'transcript_corrections', 'glossary_terms', 'transcript_versions',
    'transcript_version_segments', 'analysis_versions', 'analysis_evidence', 'review_cases',
    'review_events', 'publication_events', 'artifact_versions', 'retention_jobs', 'cdr_matches'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_%I ON %I', table_name, table_name);
    EXECUTE format(
      'CREATE POLICY tenant_isolation_%I ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid)',
      table_name,
      table_name
    );
  END LOOP;
END $$;

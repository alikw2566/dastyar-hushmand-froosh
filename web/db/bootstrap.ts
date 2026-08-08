export async function ensureCoreSchema(db: D1Database) {
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS organizations (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      plan TEXT NOT NULL DEFAULT 'free',
      monthly_minute_limit INTEGER NOT NULL DEFAULT 120,
      retention_days INTEGER NOT NULL DEFAULT 30,
      automation_mode TEXT NOT NULL DEFAULT 'approval',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS calls (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      external_id TEXT,
      customer_name TEXT NOT NULL DEFAULT 'در انتظار استخراج',
      company_name TEXT,
      phone_number TEXT,
      city TEXT,
      province TEXT,
      seller_name TEXT NOT NULL DEFAULT 'در انتظار تشخیص',
      seller_email TEXT,
      product_name TEXT,
      product_category TEXT,
      sales_stage TEXT,
      lead_temperature TEXT,
      original_file_name TEXT NOT NULL,
      object_key TEXT NOT NULL,
      mime_type TEXT NOT NULL,
      size_bytes INTEGER NOT NULL,
      source TEXT NOT NULL DEFAULT 'upload',
      status TEXT NOT NULL DEFAULT 'queued',
      outcome TEXT NOT NULL DEFAULT 'unknown',
      outcome_confirmed INTEGER NOT NULL DEFAULT 0,
      duration_seconds REAL,
      direction TEXT,
      score REAL,
      sentiment TEXT,
      risk_flags_json TEXT,
      followup_required INTEGER NOT NULL DEFAULT 0,
      followup_at TEXT,
      has_manual_correction INTEGER NOT NULL DEFAULT 0,
      analysis_version TEXT,
      analysis_json TEXT,
      error_message TEXT,
      error_type TEXT,
      failed_stage TEXT,
      retry_count INTEGER NOT NULL DEFAULT 0,
      last_retry_at TEXT,
      next_retry_at TEXT,
      worker TEXT,
      correlation_id TEXT,
      source_path TEXT,
      file_hash TEXT,
      detected_at TEXT,
      imported_at TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (organization_id) REFERENCES organizations(id)
    )`),
    db.prepare("CREATE UNIQUE INDEX IF NOT EXISTS calls_org_external_idx ON calls (organization_id, external_id)"),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_calls_org_created ON calls (organization_id, created_at)"),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_calls_org_status_created ON calls (organization_id, status, created_at)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS transcript_segments (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      call_id TEXT NOT NULL,
      position INTEGER NOT NULL,
      speaker_label TEXT NOT NULL,
      speaker_role TEXT NOT NULL DEFAULT 'unknown',
      speaker_role_confidence REAL,
      start_seconds REAL,
      end_seconds REAL,
      content TEXT NOT NULL,
      normalized_text TEXT,
      is_manually_corrected INTEGER NOT NULL DEFAULT 0,
      correction_user_id TEXT,
      edited_by TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE CASCADE
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_segments_org_call_position ON transcript_segments (organization_id, call_id, position)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS local_users (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE,
      full_name TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      password_salt TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'admin',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (organization_id) REFERENCES organizations(id)
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS local_sessions (
      token_hash TEXT PRIMARY KEY,
      user_id TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (user_id) REFERENCES local_users(id) ON DELETE CASCADE
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS local_sessions_user_idx ON local_sessions (user_id)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS tasks (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      call_id TEXT,
      customer_name TEXT NOT NULL DEFAULT '',
      company_name TEXT,
      title TEXT NOT NULL,
      assignee_email TEXT,
      priority TEXT NOT NULL DEFAULT 'normal',
      status TEXT NOT NULL DEFAULT 'open',
      due_at TEXT,
      reason TEXT,
      completion_note TEXT,
      completed_at TEXT,
      creation_method TEXT NOT NULL DEFAULT 'manual',
      evidence_json TEXT,
      ai_suggested INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_tasks_org_status_due ON tasks (organization_id, status, due_at)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS message_drafts (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      call_id TEXT,
      channel TEXT NOT NULL,
      subject TEXT,
      content TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending_approval',
      approved_by TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS teams (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      supervisor_email TEXT,
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (organization_id) REFERENCES organizations(id)
    )`),
    db.prepare("CREATE UNIQUE INDEX IF NOT EXISTS teams_org_name_idx ON teams (organization_id, name)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS member_profiles (
      user_id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      team_id TEXT,
      active INTEGER NOT NULL DEFAULT 1,
      last_login_at TEXT,
      FOREIGN KEY (user_id) REFERENCES local_users(id) ON DELETE CASCADE,
      FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS scorecards (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      name TEXT NOT NULL,
      criteria_json TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS automation_rules (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      name TEXT NOT NULL,
      event TEXT NOT NULL,
      action TEXT NOT NULL,
      mode TEXT NOT NULL DEFAULT 'approval',
      enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS ai_settings (
      organization_id TEXT PRIMARY KEY,
      provider TEXT NOT NULL DEFAULT 'openai',
      transcription_model TEXT NOT NULL DEFAULT 'gpt-4o-transcribe-diarize',
      analysis_model TEXT NOT NULL DEFAULT 'gpt-4o',
      min_confidence REAL NOT NULL DEFAULT 0.75,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS security_settings (
      organization_id TEXT PRIMARY KEY,
      require_consent INTEGER NOT NULL DEFAULT 1,
      audio_download_enabled INTEGER NOT NULL DEFAULT 1,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS audit_logs (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      actor_email TEXT NOT NULL,
      action TEXT NOT NULL,
      entity_type TEXT NOT NULL,
      entity_id TEXT,
      details_json TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS audit_org_created_idx ON audit_logs (organization_id, created_at)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS processing_events (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      call_id TEXT NOT NULL,
      stage TEXT NOT NULL,
      status TEXT NOT NULL,
      error_type TEXT,
      safe_message TEXT,
      stack_trace TEXT,
      retry_count INTEGER NOT NULL DEFAULT 0,
      worker TEXT,
      correlation_id TEXT,
      started_at TEXT,
      finished_at TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE CASCADE
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_processing_org_status_created ON processing_events (organization_id, status, created_at)"),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_processing_org_call_created ON processing_events (organization_id, call_id, created_at)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS extraction_evidence (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      call_id TEXT NOT NULL,
      field_name TEXT NOT NULL,
      extracted_value TEXT,
      confidence REAL,
      source_segment_ids_json TEXT,
      exact_quote TEXT,
      start_seconds REAL,
      end_seconds REAL,
      extraction_method TEXT,
      validation_status TEXT NOT NULL DEFAULT 'unsupported',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE CASCADE
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_evidence_org_call ON extraction_evidence (organization_id, call_id)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS glossary_entries (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      term TEXT NOT NULL,
      normalized_term TEXT NOT NULL,
      category TEXT NOT NULL,
      aliases_json TEXT NOT NULL DEFAULT '[]',
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_glossary_org_normalized ON glossary_entries (organization_id, normalized_term, category)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS issabel_settings (
      organization_id TEXT PRIMARY KEY,
      import_mode TEXT NOT NULL DEFAULT 'disabled',
      recordings_path TEXT,
      sftp_host TEXT,
      sftp_port INTEGER NOT NULL DEFAULT 22,
      sftp_username TEXT,
      sftp_remote_path TEXT,
      poll_interval INTEGER NOT NULL DEFAULT 60,
      file_stability_seconds INTEGER NOT NULL DEFAULT 15,
      allowed_extensions TEXT NOT NULL DEFAULT 'wav,mp3,gsm',
      quarantine_path TEXT,
      filename_pattern TEXT,
      enabled INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
  ]);

  // Local Sites/D1 can already contain the prerelease schema. Additive upgrades keep
  // existing tenant data intact while bringing that database to the pilot shape.
  await ensureColumns(db, "calls", {
    company_name: "TEXT", phone_number: "TEXT", city: "TEXT", province: "TEXT", seller_email: "TEXT",
    product_name: "TEXT", product_category: "TEXT", sales_stage: "TEXT", lead_temperature: "TEXT",
    direction: "TEXT", sentiment: "TEXT", risk_flags_json: "TEXT", followup_required: "INTEGER NOT NULL DEFAULT 0",
    followup_at: "TEXT", has_manual_correction: "INTEGER NOT NULL DEFAULT 0", error_type: "TEXT", failed_stage: "TEXT",
    retry_count: "INTEGER NOT NULL DEFAULT 0", last_retry_at: "TEXT", next_retry_at: "TEXT", worker: "TEXT",
    correlation_id: "TEXT", source_path: "TEXT", file_hash: "TEXT", detected_at: "TEXT", imported_at: "TEXT",
  });
  await ensureColumns(db, "tasks", {
    company_name: "TEXT", reason: "TEXT", completion_note: "TEXT", completed_at: "TEXT",
    creation_method: "TEXT NOT NULL DEFAULT 'manual'", evidence_json: "TEXT",
  });
  await ensureColumns(db, "transcript_segments", {
    speaker_role_confidence: "REAL", normalized_text: "TEXT", is_manually_corrected: "INTEGER NOT NULL DEFAULT 0",
    correction_user_id: "TEXT", updated_at: "TEXT",
  });
  // These indexes reference columns introduced by the additive upgrade above.
  // Creating them in the initial table batch breaks existing prerelease D1 databases.
  await db.batch([
    db.prepare("CREATE INDEX IF NOT EXISTS idx_calls_org_seller_created ON calls (organization_id, seller_email, created_at)"),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_calls_org_followup ON calls (organization_id, followup_required, followup_at)"),
  ]);
  await db.prepare("PRAGMA optimize").run();
}

async function ensureColumns(db: D1Database, table: string, columns: Record<string, string>) {
  const info = await db.prepare(`PRAGMA table_info(${table})`).all<{ name: string }>();
  const present = new Set(info.results.map((row) => row.name));
  for (const [name, definition] of Object.entries(columns)) {
    if (!present.has(name)) await db.prepare(`ALTER TABLE ${table} ADD COLUMN ${name} ${definition}`).run();
  }
}

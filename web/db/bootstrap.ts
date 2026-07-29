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
      seller_name TEXT NOT NULL DEFAULT 'در انتظار تشخیص',
      original_file_name TEXT NOT NULL,
      object_key TEXT NOT NULL,
      mime_type TEXT NOT NULL,
      size_bytes INTEGER NOT NULL,
      source TEXT NOT NULL DEFAULT 'upload',
      status TEXT NOT NULL DEFAULT 'queued',
      outcome TEXT NOT NULL DEFAULT 'unknown',
      outcome_confirmed INTEGER NOT NULL DEFAULT 0,
      duration_seconds REAL,
      score REAL,
      analysis_version TEXT,
      analysis_json TEXT,
      error_message TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (organization_id) REFERENCES organizations(id)
    )`),
    db.prepare("CREATE UNIQUE INDEX IF NOT EXISTS calls_org_external_idx ON calls (organization_id, external_id)"),
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
      title TEXT NOT NULL,
      assignee_email TEXT,
      priority TEXT NOT NULL DEFAULT 'normal',
      status TEXT NOT NULL DEFAULT 'open',
      due_at TEXT,
      ai_suggested INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
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
    db.prepare(`CREATE TABLE IF NOT EXISTS integrations (
      id TEXT PRIMARY KEY,
      organization_id TEXT NOT NULL,
      name TEXT NOT NULL,
      kind TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'inactive',
      config_json TEXT NOT NULL DEFAULT '{}',
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
  ]);
}

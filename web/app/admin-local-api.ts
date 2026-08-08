import { createManagedLocalUser, type LocalUser } from "./local-auth";

const reply = (value: unknown, status = 200) => Response.json(value, { status });
const allowedRoles = ["admin", "manager", "supervisor", "agent", "viewer", "seller"];
const allowedModes = ["draft", "approval", "automatic"];
const allowedAutomationActions = ["task.create", "message.create", "manager.notify"];

async function bodyOf(request: Request) {
  try { return await request.json() as Record<string, unknown>; } catch { return {}; }
}

async function audit(db: D1Database, user: LocalUser, action: string, entityType: string, entityId?: string, details?: unknown) {
  await db.prepare("INSERT INTO audit_logs (id, organization_id, actor_email, action, entity_type, entity_id, details_json) VALUES (?, ?, ?, ?, ?, ?, ?)")
    .bind(`audit_${crypto.randomUUID()}`, user.organizationId, user.email, action, entityType, entityId ?? null, details ? JSON.stringify(details) : null).run();
}

export async function handleLocalAdminApi(request: Request, path: string[], user: LocalUser, db: D1Database): Promise<Response> {
  const resource = path[1] ?? "overview"; const id = path[2]; const action = path[3]; const method = request.method.toUpperCase();
  const admin = user.role === "مدیر"; const manager = user.role === "مدیر فروش" || user.role === "سرپرست";
  if (!admin && !manager) return reply({ error: "insufficient_role" }, 403);
  if (!admin && ["members", "security"].includes(resource)) return reply({ error: "insufficient_role" }, 403);

  if (resource === "overview" && method === "GET") {
    const [members, teams, calls, pending, rules] = await Promise.all([
      db.prepare("SELECT COUNT(*) AS value FROM local_users u LEFT JOIN member_profiles p ON p.user_id=u.id WHERE u.organization_id=? AND COALESCE(p.active,1)=1").bind(user.organizationId).first<{ value: number }>(),
      db.prepare("SELECT COUNT(*) AS value FROM teams WHERE organization_id=? AND active=1").bind(user.organizationId).first<{ value: number }>(),
      db.prepare("SELECT COUNT(*) AS value, COALESCE(SUM(duration_seconds),0) AS seconds, COALESCE(SUM(size_bytes),0) AS bytes FROM calls WHERE organization_id=?").bind(user.organizationId).first<{ value: number; seconds: number; bytes: number }>(),
      db.prepare("SELECT COUNT(*) AS value FROM tasks WHERE organization_id=? AND status NOT IN ('done','cancelled')").bind(user.organizationId).first<{ value: number }>(),
      db.prepare("SELECT COUNT(*) AS value FROM automation_rules WHERE organization_id=? AND enabled=1").bind(user.organizationId).first<{ value: number }>(),
    ]);
    return reply({ members: Number(members?.value ?? 0), teams: Number(teams?.value ?? 0), calls: Number(calls?.value ?? 0), used_minutes: Math.round(Number(calls?.seconds ?? 0) / 6) / 10, storage_bytes: Number(calls?.bytes ?? 0), pending_tasks: Number(pending?.value ?? 0), active_rules: Number(rules?.value ?? 0) });
  }

  if (resource === "members" && !id && method === "GET") {
    const rows = await db.prepare(`SELECT u.id,u.email,u.full_name,u.role,u.created_at,COALESCE(p.active,1) AS active,p.team_id,p.last_login_at,t.name AS team_name
      FROM local_users u LEFT JOIN member_profiles p ON p.user_id=u.id LEFT JOIN teams t ON t.id=p.team_id
      WHERE u.organization_id=? ORDER BY u.created_at`).bind(user.organizationId).all();
    return reply({ items: rows.results });
  }
  if (resource === "members" && !id && method === "POST") {
    const body = await bodyOf(request);
    try { return reply({ member: await createManagedLocalUser(user, { fullName: String(body.full_name ?? ""), email: String(body.email ?? ""), password: String(body.password ?? ""), role: String(body.role ?? "seller"), teamId: body.team_id ? String(body.team_id) : null }) }, 201); }
    catch (cause) { const code = cause instanceof Error ? cause.message : "member_create_failed"; return reply({ error: code }, code === "email_exists" ? 409 : 422); }
  }
  if (resource === "members" && id && method === "PATCH") {
    const target = await db.prepare(`SELECT u.id,u.role,COALESCE(p.active,1) AS active FROM local_users u LEFT JOIN member_profiles p ON p.user_id=u.id WHERE u.id=? AND u.organization_id=?`).bind(id, user.organizationId).first<{ id: string; role: string; active: number }>();
    if (!target) return reply({ error: "member_not_found" }, 404);
    const body = await bodyOf(request); const role = body.role == null ? target.role : String(body.role); const active = body.active == null ? target.active : body.active ? 1 : 0; const teamId = body.team_id == null || body.team_id === "" ? null : String(body.team_id);
    if (!allowedRoles.includes(role)) return reply({ error: "invalid_role" }, 422);
    if (teamId && !await db.prepare("SELECT id FROM teams WHERE id=? AND organization_id=?").bind(teamId, user.organizationId).first()) return reply({ error: "team_not_found" }, 404);
    if (target.role === "admin" && (role !== "admin" || !active)) {
      const admins = await db.prepare(`SELECT COUNT(*) AS value FROM local_users u LEFT JOIN member_profiles p ON p.user_id=u.id WHERE u.organization_id=? AND u.role='admin' AND COALESCE(p.active,1)=1`).bind(user.organizationId).first<{ value: number }>();
      if (Number(admins?.value ?? 0) <= 1) return reply({ error: "last_admin_protected" }, 409);
    }
    await db.batch([
      db.prepare("UPDATE local_users SET role=? WHERE id=? AND organization_id=?").bind(role, id, user.organizationId),
      db.prepare(`INSERT INTO member_profiles (user_id,organization_id,team_id,active) VALUES (?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET team_id=excluded.team_id,active=excluded.active`).bind(id, user.organizationId, teamId, active),
    ]);
    if (!active) await db.prepare("DELETE FROM local_sessions WHERE user_id=?").bind(id).run();
    await audit(db, user, "member.updated", "member", id, { role, active, team_id: teamId }); return reply({ status: "updated" });
  }

  if (resource === "teams" && !id && method === "GET") {
    const rows = await db.prepare(`SELECT t.*,COUNT(p.user_id) AS member_count FROM teams t LEFT JOIN member_profiles p ON p.team_id=t.id
      WHERE t.organization_id=? GROUP BY t.id ORDER BY t.created_at DESC`).bind(user.organizationId).all(); return reply({ items: rows.results });
  }
  if (resource === "teams" && !id && method === "POST") {
    const body = await bodyOf(request); const name = String(body.name ?? "").trim(); if (name.length < 2) return reply({ error: "invalid_team_name" }, 422);
    if (await db.prepare("SELECT id FROM teams WHERE organization_id=? AND name=?").bind(user.organizationId, name).first()) return reply({ error: "team_exists" }, 409);
    const teamId = `team_${crypto.randomUUID()}`; await db.prepare("INSERT INTO teams (id,organization_id,name,description,supervisor_email) VALUES (?,?,?,?,?)").bind(teamId, user.organizationId, name, String(body.description ?? "").trim(), body.supervisor_email ? String(body.supervisor_email) : null).run();
    await audit(db, user, "team.created", "team", teamId, { name }); return reply({ id: teamId }, 201);
  }
  if (resource === "teams" && id && method === "PATCH") {
    const body = await bodyOf(request); const current = await db.prepare("SELECT * FROM teams WHERE id=? AND organization_id=?").bind(id, user.organizationId).first<Record<string, unknown>>(); if (!current) return reply({ error: "team_not_found" }, 404);
    const name = String(body.name ?? current.name).trim(); const active = body.active == null ? Number(current.active) : body.active ? 1 : 0; if (name.length < 2) return reply({ error: "invalid_team_name" }, 422);
    await db.prepare("UPDATE teams SET name=?,description=?,supervisor_email=?,active=? WHERE id=? AND organization_id=?").bind(name, String(body.description ?? current.description ?? ""), body.supervisor_email ?? current.supervisor_email ?? null, active, id, user.organizationId).run();
    await audit(db, user, "team.updated", "team", id, { name, active }); return reply({ status: "updated" });
  }

  if (resource === "scorecards" && !id && method === "GET") {
    const rows = await db.prepare("SELECT * FROM scorecards WHERE organization_id=? ORDER BY created_at DESC").bind(user.organizationId).all<Record<string, unknown>>();
    return reply({ items: rows.results.map((row) => ({ ...row, criteria: JSON.parse(String(row.criteria_json)) })) });
  }
  if (resource === "scorecards" && !id && method === "POST") {
    const body = await bodyOf(request); const name = String(body.name ?? "").trim(); const criteria = Array.isArray(body.criteria) ? body.criteria as Array<Record<string, unknown>> : [];
    const valid = name.length >= 2 && criteria.length > 0 && criteria.every((item) => String(item.label ?? "").trim().length >= 2 && Number(item.weight) > 0) && Math.abs(criteria.reduce((sum, item) => sum + Number(item.weight), 0) - 100) < .01;
    if (!valid) return reply({ error: "invalid_scorecard" }, 422); const scorecardId = `score_${crypto.randomUUID()}`;
    await db.prepare("INSERT INTO scorecards (id,organization_id,name,criteria_json) VALUES (?,?,?,?)").bind(scorecardId, user.organizationId, name, JSON.stringify(criteria)).run(); await audit(db, user, "scorecard.created", "scorecard", scorecardId, { name }); return reply({ id: scorecardId }, 201);
  }
  if (resource === "scorecards" && id && action === "activate" && method === "POST") {
    if (!await db.prepare("SELECT id FROM scorecards WHERE id=? AND organization_id=?").bind(id, user.organizationId).first()) return reply({ error: "scorecard_not_found" }, 404);
    await db.batch([db.prepare("UPDATE scorecards SET active=0 WHERE organization_id=?").bind(user.organizationId), db.prepare("UPDATE scorecards SET active=1 WHERE id=? AND organization_id=?").bind(id, user.organizationId)]); await audit(db, user, "scorecard.activated", "scorecard", id); return reply({ status: "activated" });
  }

  if (resource === "automations" && !id && method === "GET") { const rows = await db.prepare("SELECT * FROM automation_rules WHERE organization_id=? ORDER BY created_at DESC").bind(user.organizationId).all(); return reply({ items: rows.results }); }
  if (resource === "automations" && !id && method === "POST") {
    const body = await bodyOf(request); const name = String(body.name ?? "").trim(); const event = String(body.event ?? ""); const ruleAction = String(body.action ?? ""); const mode = String(body.mode ?? "approval"); if (name.length < 2 || !event || !allowedAutomationActions.includes(ruleAction) || !allowedModes.includes(mode)) return reply({ error: "invalid_automation" }, 422);
    const ruleId = `rule_${crypto.randomUUID()}`; await db.prepare("INSERT INTO automation_rules (id,organization_id,name,event,action,mode) VALUES (?,?,?,?,?,?)").bind(ruleId, user.organizationId, name, event, ruleAction, mode).run(); await audit(db, user, "automation.created", "automation", ruleId, { name }); return reply({ id: ruleId }, 201);
  }
  if (resource === "automations" && id && method === "PATCH") {
    const body = await bodyOf(request); const enabled = body.enabled ? 1 : 0; const result = await db.prepare("UPDATE automation_rules SET enabled=? WHERE id=? AND organization_id=?").bind(enabled, id, user.organizationId).run(); if (!result.meta.changes) return reply({ error: "automation_not_found" }, 404); await audit(db, user, "automation.toggled", "automation", id, { enabled }); return reply({ status: "updated" });
  }

  if (resource === "accuracy" && method === "GET") {
    return reply({ measured: false, wer: null, cer: null, sample_count: 0, evaluated_at: null, dataset: null, message: "دقت هنوز با دیتاست تماس‌های واقعی فارسی اندازه‌گیری نشده است." });
  }

  if (resource === "glossary" && !id && method === "GET") {
    const rows = await db.prepare("SELECT id,term,category,aliases_json,active,created_at FROM glossary_entries WHERE organization_id=? ORDER BY active DESC,category,term").bind(user.organizationId).all<Record<string, unknown>>();
    return reply({ items: rows.results.map((row) => ({ ...row, aliases: parseArray(row.aliases_json) })) });
  }
  if (resource === "glossary" && !id && method === "POST") {
    const body = await bodyOf(request); const term = String(body.term ?? "").trim(); const category = String(body.category ?? "sales").trim();
    if (term.length < 2 || !["product","brand","company","medical","sales","city","employee","other"].includes(category)) return reply({ error: "invalid_glossary_entry" }, 422);
    const aliases = Array.isArray(body.aliases) ? body.aliases.map(String).map((value) => value.trim()).filter(Boolean) : String(body.aliases ?? "").split(",").map((value) => value.trim()).filter(Boolean);
    const entryId = `gls_${crypto.randomUUID()}`;
    try { await db.prepare("INSERT INTO glossary_entries (id,organization_id,term,normalized_term,category,aliases_json) VALUES (?,?,?,?,?,?)").bind(entryId, user.organizationId, term, normalizePersian(term), category, JSON.stringify(aliases)).run(); }
    catch { return reply({ error: "glossary_entry_exists" }, 409); }
    await audit(db, user, "glossary.created", "glossary", entryId, { term, category }); return reply({ id: entryId }, 201);
  }
  if (resource === "glossary" && id && method === "PATCH") {
    const body = await bodyOf(request); const active = body.active ? 1 : 0; const result = await db.prepare("UPDATE glossary_entries SET active=? WHERE id=? AND organization_id=?").bind(active, id, user.organizationId).run();
    if (!result.meta.changes) return reply({ error: "glossary_entry_not_found" }, 404); await audit(db, user, "glossary.updated", "glossary", id, { active }); return reply({ status: "updated" });
  }
  if (resource === "glossary" && id && method === "DELETE") {
    const result = await db.prepare("DELETE FROM glossary_entries WHERE id=? AND organization_id=?").bind(id, user.organizationId).run(); if (!result.meta.changes) return reply({ error: "glossary_entry_not_found" }, 404); await audit(db, user, "glossary.deleted", "glossary", id); return reply({ status: "deleted" });
  }

  if (resource === "issabel-settings" && !id && method === "GET") {
    const row = await db.prepare("SELECT * FROM issabel_settings WHERE organization_id=?").bind(user.organizationId).first<Record<string, unknown>>();
    const limitation = "Watcher فقط با Backend/Docker قابل اجرا است؛ تنظیمات در D1 ذخیره می‌شود اما این محیط فایل Issabel را نمی‌خواند.";
    return reply(row ? { ...row, editable: true, watcher_available: false, watcher_health: "not_connected", limitation } : { organization_id: user.organizationId, import_mode: "disabled", recordings_path: "", sftp_host: "", sftp_port: 22, sftp_username: "", sftp_remote_path: "", poll_interval: 60, file_stability_seconds: 15, allowed_extensions: "wav,mp3,gsm", quarantine_path: "", filename_pattern: "", enabled: 0, editable: true, watcher_available: false, watcher_health: "not_connected", limitation });
  }
  if (resource === "issabel-settings" && !id && method === "PATCH") {
    const body = await bodyOf(request); const mode = ["disabled","folder","sftp"].includes(String(body.import_mode)) ? String(body.import_mode) : "disabled";
    const poll = Math.min(3600, Math.max(10, Number(body.poll_interval) || 60)); const stability = Math.min(600, Math.max(5, Number(body.file_stability_seconds) || 15));
    await db.prepare(`INSERT INTO issabel_settings (organization_id,import_mode,recordings_path,sftp_host,sftp_port,sftp_username,sftp_remote_path,poll_interval,file_stability_seconds,allowed_extensions,quarantine_path,filename_pattern,enabled,updated_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id) DO UPDATE SET import_mode=excluded.import_mode,recordings_path=excluded.recordings_path,sftp_host=excluded.sftp_host,sftp_port=excluded.sftp_port,sftp_username=excluded.sftp_username,sftp_remote_path=excluded.sftp_remote_path,poll_interval=excluded.poll_interval,file_stability_seconds=excluded.file_stability_seconds,allowed_extensions=excluded.allowed_extensions,quarantine_path=excluded.quarantine_path,filename_pattern=excluded.filename_pattern,enabled=excluded.enabled,updated_at=excluded.updated_at`)
      .bind(user.organizationId, mode, String(body.recordings_path ?? ""), String(body.sftp_host ?? ""), Number(body.sftp_port) || 22, String(body.sftp_username ?? ""), String(body.sftp_remote_path ?? ""), poll, stability, String(body.allowed_extensions ?? "wav,mp3,gsm"), String(body.quarantine_path ?? ""), String(body.filename_pattern ?? ""), 0, new Date().toISOString()).run();
    await audit(db, user, "issabel.settings.updated", "issabel", user.organizationId, { import_mode: mode, poll_interval: poll });
    return reply({ status: "saved", enabled: false, warning: "تنظیمات ذخیره شد؛ فعال‌سازی Watcher به Backend نیاز دارد." });
  }
  if (resource === "issabel-settings" && id === "test" && method === "POST") return reply({ error: "watcher_backend_required", detail: "تست اتصال Issabel در حالت محلی در دسترس نیست؛ Backend/Docker را اجرا کنید." }, 501);

  if (resource === "processing-operations" && !id && method === "GET") {
    const rows = await db.prepare(`SELECT id,original_file_name AS source_file,status,failed_stage,error_type,error_message AS safe_message,retry_count,last_retry_at,next_retry_at,duration_seconds,created_at,worker,correlation_id
      FROM calls WHERE organization_id=? AND (status IN ('failed','retry_scheduled','quarantined') OR error_message IS NOT NULL) ORDER BY created_at DESC LIMIT 200`).bind(user.organizationId).all<Record<string, unknown>>();
    return reply({ items: rows.results.map((row) => ({ ...row, can_retry: false, can_quarantine: row.status !== "quarantined", can_restore: row.status === "quarantined", can_download_diagnostics: false })), capabilities: { retry: false, diagnostics: false, quarantine: true }, limitation: "Retry و بسته تشخیصی به Worker پردازش نیاز دارند؛ قرنطینه در D1 فعال است." });
  }
  if (resource === "processing-operations" && id && action && method === "POST") {
    const body = await bodyOf(request); const requested = action === "actions" ? String(body.action ?? "") : action;
    if (["retry","reanalyze","full_reprocess","cancel","diagnostics"].includes(requested)) return reply({ error: "processing_backend_required", detail: "این اقدام به Worker پردازش متصل نیاز دارد." }, 501);
    const status = requested === "quarantine" ? "quarantined" : requested === "restore" ? "failed" : requested === "resolve_error" ? "ignored" : null;
    if (!status) return reply({ error: "unknown_processing_action" }, 404);
    const result = await db.prepare("UPDATE calls SET status=?,updated_at=? WHERE id=? AND organization_id=?").bind(status, new Date().toISOString(), id, user.organizationId).run(); if (!result.meta.changes) return reply({ error: "call_not_found" }, 404);
    await audit(db, user, `processing.${requested}`, "call", id); return reply({ status });
  }

  if (resource === "ai-settings" && method === "GET") { const row = await db.prepare("SELECT * FROM ai_settings WHERE organization_id=?").bind(user.organizationId).first(); return reply(row ?? { organization_id: user.organizationId, provider: "openai", transcription_model: "gpt-4o-transcribe-diarize", analysis_model: "gpt-4o", min_confidence: .75 }); }
  if (resource === "ai-settings" && method === "PATCH") {
    const body = await bodyOf(request); const provider = String(body.provider ?? "openai"); const transcription = String(body.transcription_model ?? "").trim(); const analysis = String(body.analysis_model ?? "").trim(); const confidence = Number(body.min_confidence); if (!["openai","avalai"].includes(provider) || !transcription || !analysis || confidence < .5 || confidence > .99) return reply({ error: "invalid_ai_settings" }, 422);
    await db.prepare(`INSERT INTO ai_settings (organization_id,provider,transcription_model,analysis_model,min_confidence,updated_at) VALUES (?,?,?,?,?,?)
      ON CONFLICT(organization_id) DO UPDATE SET provider=excluded.provider,transcription_model=excluded.transcription_model,analysis_model=excluded.analysis_model,min_confidence=excluded.min_confidence,updated_at=excluded.updated_at`).bind(user.organizationId, provider, transcription, analysis, confidence, new Date().toISOString()).run(); await audit(db, user, "ai_settings.updated", "ai_settings", user.organizationId, { provider, transcription, analysis, confidence }); return reply({ status: "updated" });
  }

  if (resource === "security" && method === "GET") { const row = await db.prepare("SELECT * FROM security_settings WHERE organization_id=?").bind(user.organizationId).first(); return reply(row ?? { organization_id: user.organizationId, require_consent: 1, audio_download_enabled: 1 }); }
  if (resource === "security" && method === "PATCH") {
    const body = await bodyOf(request); const consent = body.require_consent ? 1 : 0; const audio = body.audio_download_enabled ? 1 : 0;
    await db.prepare(`INSERT INTO security_settings (organization_id,require_consent,audio_download_enabled,updated_at) VALUES (?,?,?,?)
      ON CONFLICT(organization_id) DO UPDATE SET require_consent=excluded.require_consent,audio_download_enabled=excluded.audio_download_enabled,updated_at=excluded.updated_at`).bind(user.organizationId, consent, audio, new Date().toISOString()).run(); await audit(db, user, "security.updated", "security", user.organizationId, { require_consent: consent, audio_download_enabled: audio }); return reply({ status: "updated" });
  }

  if (resource === "audit-logs" && method === "GET") { const rows = await db.prepare("SELECT id,actor_email,action,entity_type,entity_id,created_at FROM audit_logs WHERE organization_id=? ORDER BY created_at DESC LIMIT 100").bind(user.organizationId).all(); return reply({ items: rows.results }); }
  return reply({ error: "not_found" }, 404);
}

function normalizePersian(value: string) { return value.replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/[\u200c\s]+/g, " ").trim().toLocaleLowerCase("fa-IR"); }
function parseArray(value: unknown): string[] { if (typeof value !== "string") return []; try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed.map(String) : []; } catch { return []; } }

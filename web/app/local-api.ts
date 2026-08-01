import { env } from "cloudflare:workers";
import { ensureCoreSchema } from "../db/bootstrap";
import { getLocalUser, localAuthAvailable } from "./local-auth";
import { handleLocalAdminApi } from "./admin-local-api";

type Bindings = { DB: D1Database; AUDIO: R2Bucket };
const bindings = () => env as unknown as Bindings;

function json(value: unknown, status = 200) { return Response.json(value, { status }); }

export async function handleLocalApi(request: Request, path: string[]): Promise<Response> {
  if (!localAuthAvailable()) return json({ error: "processing_backend_not_configured" }, 503);
  const user = await getLocalUser();
  if (!user) return json({ error: "authentication_required" }, 401);
  const { DB, AUDIO } = bindings(); await ensureCoreSchema(DB);
  const method = request.method.toUpperCase();
  const readOnly = user.role === "مشاهده‌گر";
  const ownOnly = user.role === "کارشناس" || user.role === "فروشنده";

  if (path[0] === "admin" && path[1] !== "organization") return handleLocalAdminApi(request, path, user, DB);

  if (method === "GET" && path.join("/") === "overview") {
    const row = await DB.prepare(`SELECT COUNT(*) AS total_calls,
      SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_calls,
      AVG(score) AS average_score,
      SUM(CASE WHEN outcome = 'won' AND outcome_confirmed = 1 THEN 1 ELSE 0 END) AS won_calls
      FROM calls WHERE organization_id = ?${ownOnly ? " AND seller_email = ?" : ""}`).bind(...(ownOnly ? [user.organizationId, user.email] : [user.organizationId])).first<{ total_calls: number; completed_calls: number; average_score: number | null; won_calls: number }>();
    const total = Number(row?.total_calls ?? 0);
    return json({ total_calls: total, completed_calls: Number(row?.completed_calls ?? 0), average_score: row?.average_score == null ? null : Math.round(row.average_score * 10) / 10, confirmed_conversion_rate: total ? Math.round(Number(row?.won_calls ?? 0) / total * 1000) / 10 : null });
  }

  if (path[0] === "calls" && path[1] && method === "GET") {
    const call = await DB.prepare("SELECT * FROM calls WHERE id = ? AND organization_id = ?").bind(path[1], user.organizationId).first<Record<string, unknown>>();
    if (!call) return json({ error: "call_not_found" }, 404);
    if (ownOnly && String(call.seller_email ?? "").toLowerCase() !== user.email.toLowerCase()) return json({ error: "call_not_found" }, 404);
    if (path[2] === "audio") {
      const security = await DB.prepare("SELECT audio_download_enabled FROM security_settings WHERE organization_id = ?").bind(user.organizationId).first<{ audio_download_enabled: number }>();
      if (security && !security.audio_download_enabled) return json({ error: "audio_download_disabled" }, 403);
      const object = await AUDIO.get(String(call.object_key));
      if (!object) return json({ error: "audio_not_found" }, 404);
      const headers = new Headers({ "content-type": String(call.mime_type), "cache-control": "private, max-age=60", "content-disposition": `inline; filename="${encodeURIComponent(String(call.original_file_name))}"` });
      return new Response(object.body, { headers });
    }
    if (path[2] === "export.pdf") return json({ error: "pdf_export_requires_processing_backend", detail: "خروجی PDF فقط پس از اتصال سرویس پردازش فعال می‌شود." }, 501);
    if (path[2] === "export.xlsx") return json({ error: "excel_export_requires_processing_backend", detail: "خروجی Excel تماس فقط پس از اتصال سرویس پردازش فعال می‌شود." }, 501);
    let analysis = call.analysis_json ?? null;
    if (typeof analysis === "string") { try { analysis = JSON.parse(analysis); } catch { analysis = null; } }
    const [segments, timeline, evidence, followups] = await Promise.all([
      DB.prepare(`SELECT id,speaker_label AS speaker,speaker_label AS speaker_id,speaker_role AS role,speaker_role_confidence,
        start_seconds AS start,end_seconds AS end,content AS text,content,normalized_text,is_manually_corrected,correction_user_id,updated_at
        FROM transcript_segments WHERE organization_id=? AND call_id=? ORDER BY position`).bind(user.organizationId, path[1]).all(),
      DB.prepare("SELECT * FROM processing_events WHERE organization_id=? AND call_id=? ORDER BY created_at").bind(user.organizationId, path[1]).all(),
      DB.prepare("SELECT * FROM extraction_evidence WHERE organization_id=? AND call_id=? ORDER BY created_at").bind(user.organizationId, path[1]).all<Record<string, unknown>>(),
      DB.prepare("SELECT * FROM tasks WHERE organization_id=? AND call_id=? ORDER BY created_at DESC").bind(user.organizationId, path[1]).all(),
    ]);
    return json({
      call, analysis, segments: segments.results, processing_timeline: timeline.results,
      evidence: evidence.results.map((row) => ({ ...row, source_segment_ids: parseJson(row.source_segment_ids_json, []) })),
      followups: followups.results, audio_url: `/api/v1/calls/${path[1]}/audio`,
      capabilities: { pdf_export: false, excel_export: false, reanalysis: false, retry: false, role_correction: true, transcript_correction: true, audio_download: true },
    });
  }

  if (path[0] === "transcript-segments" && path[1] && method === "PATCH") {
    if (readOnly) return json({ error: "read_only_role" }, 403);
    const body = await request.json() as { speaker_role?: string; role?: string; content?: string; text?: string };
    const role = body.speaker_role ?? body.role;
    if (role && !["agent", "seller", "customer", "unknown", "other"].includes(role)) return json({ error: "invalid_speaker_role" }, 422);
    const existing = await DB.prepare("SELECT id,call_id,speaker_role,content FROM transcript_segments WHERE id=? AND organization_id=?").bind(path[1], user.organizationId).first<{ id: string; call_id: string; speaker_role: string; content: string }>();
    if (!existing) return json({ error: "segment_not_found" }, 404);
    if (ownOnly && !await DB.prepare("SELECT id FROM calls WHERE id=? AND organization_id=? AND seller_email=?").bind(existing.call_id, user.organizationId, user.email).first()) return json({ error: "segment_not_found" }, 404);
    const content = (body.content ?? body.text ?? existing.content).trim();
    if (!content) return json({ error: "segment_text_required" }, 422);
    const now = new Date().toISOString();
    await DB.batch([
      DB.prepare("UPDATE transcript_segments SET speaker_role=?,content=?,normalized_text=?,is_manually_corrected=1,correction_user_id=?,edited_by=?,updated_at=? WHERE id=? AND organization_id=?")
        .bind(role ?? existing.speaker_role, content, normalizePersian(content), user.email, user.email, now, path[1], user.organizationId),
      DB.prepare("UPDATE calls SET has_manual_correction=1,updated_at=? WHERE id=? AND organization_id=?").bind(now, existing.call_id, user.organizationId),
      DB.prepare("INSERT INTO audit_logs (id,organization_id,actor_email,action,entity_type,entity_id,details_json) VALUES (?,?,?,?,?,?,?)")
        .bind(`audit_${crypto.randomUUID()}`, user.organizationId, user.email, "transcript.corrected", "transcript_segment", path[1], JSON.stringify({ role: role ?? existing.speaker_role })),
    ]);
    return json({ status: "updated" });
  }

  if (path[0] === "calls" && path[1] && path[2] === "speaker-roles" && method === "PATCH") {
    if (readOnly) return json({ error: "read_only_role" }, 403);
    if (ownOnly && !await DB.prepare("SELECT id FROM calls WHERE id=? AND organization_id=? AND seller_email=?").bind(path[1], user.organizationId, user.email).first()) return json({ error: "call_not_found" }, 404);
    const body = await request.json() as { speaker_id?: string; role?: string; action?: string; assignments?: Array<{ speaker_id?: string; role?: string }> };
    if (body.action === "swap") {
      const now = new Date().toISOString();
      await DB.batch([
        DB.prepare("UPDATE transcript_segments SET speaker_role=CASE WHEN speaker_role IN ('agent','seller') THEN 'customer' WHEN speaker_role='customer' THEN 'agent' ELSE speaker_role END,is_manually_corrected=1,correction_user_id=?,updated_at=? WHERE organization_id=? AND call_id=?")
          .bind(user.email, now, user.organizationId, path[1]),
        DB.prepare("UPDATE calls SET has_manual_correction=1,updated_at=? WHERE id=? AND organization_id=?").bind(now, path[1], user.organizationId),
      ]);
      return json({ status: "updated" });
    }
    const assignments = body.assignments?.length ? body.assignments : [{ speaker_id: body.speaker_id, role: body.role }];
    if (assignments.some((item) => !item.speaker_id || !["agent", "seller", "customer", "unknown", "other"].includes(item.role ?? ""))) return json({ error: "invalid_speaker_correction" }, 422);
    const now = new Date().toISOString();
    const results = await DB.batch(assignments.map((item) => DB.prepare("UPDATE transcript_segments SET speaker_role=?,is_manually_corrected=1,correction_user_id=?,updated_at=? WHERE organization_id=? AND call_id=? AND speaker_label=?")
      .bind(item.role, user.email, now, user.organizationId, path[1], item.speaker_id)));
    const changed = results.reduce((sum, result) => sum + Number(result.meta.changes ?? 0), 0);
    if (!changed) return json({ error: "speaker_not_found" }, 404);
    await DB.prepare("UPDATE calls SET has_manual_correction=1,updated_at=? WHERE id=? AND organization_id=?").bind(now, path[1], user.organizationId).run();
    return json({ status: "updated", changed_segments: changed });
  }

  if (path[0] === "calls" && path[1] && ["reanalyze", "reprocess", "retry"].includes(path[2] ?? "") && method === "POST") {
    if (readOnly) return json({ error: "read_only_role" }, 403);
    return json({ error: "processing_backend_required", detail: "پردازش مجدد در حالت D1 محلی غیرفعال است؛ سرویس Worker را متصل کنید." }, 501);
  }

  if (path[0] === "search" && path.length === 1 && method === "GET") {
    const query = normalizePersian(new URL(request.url).searchParams.get("q") ?? "");
    if (query.length < 2 || query.length > 300) return json({ error: "invalid_search_query" }, 422);
    const where = ["s.organization_id = ?", "(s.normalized_text LIKE ? OR s.content LIKE ?)"];
    const values: unknown[] = [user.organizationId, `%${query}%`, `%${query}%`];
    if (ownOnly) { where.push("c.seller_email = ?"); values.push(user.email); }
    const rows = await DB.prepare(`SELECT s.call_id,s.position,s.start_seconds,s.speaker_label,s.content
      FROM transcript_segments s JOIN calls c ON c.id=s.call_id
      WHERE ${where.join(" AND ")} ORDER BY s.call_id,s.position LIMIT 50`).bind(...values).all();
    return json({ query, mode: "text", evidence: rows.results });
  }

  if (path[0] === "tasks" && path.length === 1 && method === "GET") {
    const url = new URL(request.url); const bucket = url.searchParams.get("bucket") ?? "all"; const where = ["organization_id = ?"]; const values: unknown[] = [user.organizationId];
    if (ownOnly) { where.push("assignee_email = ?"); values.push(user.email); }
    if (bucket === "today") where.push("status NOT IN ('done','cancelled') AND due_at >= date('now') AND due_at < date('now','+1 day')");
    else if (bucket === "overdue") where.push("status NOT IN ('done','cancelled') AND due_at IS NOT NULL AND due_at < date('now')");
    else if (bucket === "unscheduled") where.push("status='needs_scheduling' OR (status NOT IN ('done','cancelled') AND due_at IS NULL)");
    else if (bucket === "done") where.push("status='done'");
    else if (bucket === "cancelled") where.push("status='cancelled'");
    const seller = url.searchParams.get("seller"); const customer = url.searchParams.get("customer");
    if (seller) { where.push("assignee_email LIKE ?"); values.push(`%${seller}%`); }
    if (customer) { where.push("customer_name LIKE ?"); values.push(`%${customer}%`); }
    const rows = await DB.prepare(`SELECT id,call_id,title,customer_name AS customer,company_name AS company,assignee_email AS assigned_agent,priority,status,due_at,reason,completion_note,completed_at,creation_method,evidence_json FROM tasks WHERE ${where.join(" AND ")} ORDER BY CASE WHEN due_at IS NULL THEN 1 ELSE 0 END,due_at,created_at DESC LIMIT 200`).bind(...values).all();
    return json({ items: rows.results, bucket });
  }
  if (path[0] === "tasks" && path.length === 1 && method === "POST") {
    if (readOnly) return json({ error: "read_only_role" }, 403);
    const body = await request.json() as { title?: string; customer_name?: string; priority?: string; due_at?: string | null };
    const title = body.title?.trim() ?? "";
    if (title.length < 2 || title.length > 300) return json({ error: "invalid_task_title" }, 422);
    const priority = ["low", "normal", "high", "critical"].includes(body.priority ?? "") ? body.priority! : "normal";
    const id = crypto.randomUUID();
    await DB.prepare("INSERT INTO tasks (id, organization_id, customer_name, title, assignee_email, priority, status, due_at) VALUES (?, ?, ?, ?, ?, ?, 'open', ?)").bind(id, user.organizationId, body.customer_name?.trim() ?? "", title, user.email, priority, body.due_at ?? null).run();
    return json({ id, title, status: "open" }, 201);
  }
  if (path[0] === "tasks" && path[1] && method === "PATCH") {
    if (readOnly) return json({ error: "read_only_role" }, 403);
    const body = await request.json() as { status?: string; completion_note?: string; due_at?: string | null };
    if (!["open", "in_progress", "needs_scheduling", "done", "cancelled"].includes(body.status ?? "")) return json({ error: "invalid_task_status" }, 422);
    const completedAt = body.status === "done" ? new Date().toISOString() : null;
    const result = ownOnly
      ? await DB.prepare("UPDATE tasks SET status=?,completion_note=COALESCE(?,completion_note),due_at=COALESCE(?,due_at),completed_at=? WHERE id=? AND organization_id=? AND assignee_email=?").bind(body.status, body.completion_note?.trim() || null, body.due_at ?? null, completedAt, path[1], user.organizationId, user.email).run()
      : await DB.prepare("UPDATE tasks SET status=?,completion_note=COALESCE(?,completion_note),due_at=COALESCE(?,due_at),completed_at=? WHERE id=? AND organization_id=?").bind(body.status, body.completion_note?.trim() || null, body.due_at ?? null, completedAt, path[1], user.organizationId).run();
    if (!result.meta.changes) return json({ error: "task_not_found" }, 404);
    return json({ id: path[1], status: body.status });
  }

  if (path[0] === "messages" && path.length === 1 && method === "GET") {
    if (!["مدیر", "مدیر فروش", "سرپرست"].includes(user.role)) return json({ error: "insufficient_role" }, 403);
    const rows = await DB.prepare("SELECT id, channel, subject, content, status FROM message_drafts WHERE organization_id = ? ORDER BY created_at DESC LIMIT 100").bind(user.organizationId).all();
    return json({ items: rows.results });
  }
  if (path[0] === "messages" && path[1] && path[2] === "approve" && method === "POST") {
    if (!["مدیر", "مدیر فروش", "سرپرست"].includes(user.role)) return json({ error: "insufficient_role" }, 403);
    const result = await DB.prepare("UPDATE message_drafts SET status = 'approved', approved_by = ? WHERE id = ? AND organization_id = ? AND status = 'pending_approval'").bind(user.email, path[1], user.organizationId).run();
    if (!result.meta.changes) return json({ error: "message_not_pending" }, 409);
    return json({ status: "approved" });
  }

  if (path.join("/") === "exports/calls.xlsx" && method === "GET") {
    return json({ error: "excel_export_requires_processing_backend", detail: "خروجی Excel چندبرگی فقط پس از اتصال سرویس پردازش فعال می‌شود." }, 501);
  }

  if (path.join("/") === "admin/organization" && method === "GET") {
    const organization = await DB.prepare("SELECT id, name, plan, monthly_minute_limit, retention_days, automation_mode FROM organizations WHERE id = ?").bind(user.organizationId).first<Record<string, unknown>>();
    return organization ? json({ ...organization, used_minutes: 0 }) : json({ error: "organization_not_found" }, 404);
  }
  if (path.join("/") === "admin/organization" && method === "PATCH") {
    if (user.role !== "مدیر") return json({ error: "insufficient_role" }, 403);
    const body = await request.json() as { name?: string; retention_days?: number; automation_mode?: string };
    const current = await DB.prepare("SELECT name, retention_days, automation_mode FROM organizations WHERE id = ?").bind(user.organizationId).first<{ name: string; retention_days: number; automation_mode: string }>();
    if (!current) return json({ error: "organization_not_found" }, 404);
    const name = body.name?.trim() || current.name;
    const retention = [30, 90, 365].includes(Number(body.retention_days)) ? Number(body.retention_days) : current.retention_days;
    const mode = ["draft", "approval", "automatic"].includes(body.automation_mode ?? "") ? body.automation_mode! : current.automation_mode;
    await DB.prepare("UPDATE organizations SET name = ?, retention_days = ?, automation_mode = ? WHERE id = ?").bind(name, retention, mode, user.organizationId).run();
    await DB.prepare("INSERT INTO audit_logs (id, organization_id, actor_email, action, entity_type, entity_id, details_json) VALUES (?, ?, ?, 'organization.updated', 'organization', ?, ?)").bind(`audit_${crypto.randomUUID()}`, user.organizationId, user.email, user.organizationId, JSON.stringify({ name, retention_days: retention, automation_mode: mode })).run();
    return json({ status: "updated" });
  }

  return json({ error: "not_found" }, 404);
}

function parseJson<T>(value: unknown, fallback: T): T {
  if (typeof value !== "string") return fallback;
  try { return JSON.parse(value) as T; } catch { return fallback; }
}

function normalizePersian(value: string) {
  return value.replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/[\u200c\s]+/g, " ").trim();
}

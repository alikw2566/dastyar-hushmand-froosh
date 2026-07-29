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

  if (path[0] === "admin" && path[1] !== "organization") return handleLocalAdminApi(request, path, user, DB);

  if (method === "GET" && path.join("/") === "overview") {
    const row = await DB.prepare(`SELECT COUNT(*) AS total_calls,
      SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_calls,
      AVG(score) AS average_score,
      SUM(CASE WHEN outcome = 'won' AND outcome_confirmed = 1 THEN 1 ELSE 0 END) AS won_calls
      FROM calls WHERE organization_id = ?`).bind(user.organizationId).first<{ total_calls: number; completed_calls: number; average_score: number | null; won_calls: number }>();
    const total = Number(row?.total_calls ?? 0);
    return json({ total_calls: total, completed_calls: Number(row?.completed_calls ?? 0), average_score: row?.average_score == null ? null : Math.round(row.average_score * 10) / 10, confirmed_conversion_rate: total ? Math.round(Number(row?.won_calls ?? 0) / total * 1000) / 10 : null });
  }

  if (path[0] === "calls" && path[1] && method === "GET") {
    const call = await DB.prepare("SELECT * FROM calls WHERE id = ? AND organization_id = ?").bind(path[1], user.organizationId).first<Record<string, unknown>>();
    if (!call) return json({ error: "call_not_found" }, 404);
    if (path[2] === "audio") {
      const security = await DB.prepare("SELECT audio_download_enabled FROM security_settings WHERE organization_id = ?").bind(user.organizationId).first<{ audio_download_enabled: number }>();
      if (security && !security.audio_download_enabled) return json({ error: "audio_download_disabled" }, 403);
      const object = await AUDIO.get(String(call.object_key));
      if (!object) return json({ error: "audio_not_found" }, 404);
      return new Response(object.body, { headers: { "content-type": String(call.mime_type), "cache-control": "private, max-age=60" } });
    }
    let analysis = call.analysis_json ?? null;
    if (typeof analysis === "string") { try { analysis = JSON.parse(analysis); } catch { analysis = null; } }
    return json({ call, analysis, segments: [], audio_url: `/api/v1/calls/${path[1]}/audio` });
  }

  if (path[0] === "tasks" && path.length === 1 && method === "GET") {
    const rows = await DB.prepare("SELECT id, title, customer_name AS customer, priority, status, due_at FROM tasks WHERE organization_id = ? ORDER BY created_at DESC LIMIT 100").bind(user.organizationId).all();
    return json({ items: rows.results });
  }
  if (path[0] === "tasks" && path.length === 1 && method === "POST") {
    const body = await request.json() as { title?: string; customer_name?: string; priority?: string; due_at?: string | null };
    const title = body.title?.trim() ?? "";
    if (title.length < 2 || title.length > 300) return json({ error: "invalid_task_title" }, 422);
    const priority = ["low", "normal", "high", "critical"].includes(body.priority ?? "") ? body.priority! : "normal";
    const id = crypto.randomUUID();
    await DB.prepare("INSERT INTO tasks (id, organization_id, customer_name, title, assignee_email, priority, status, due_at) VALUES (?, ?, ?, ?, ?, ?, 'open', ?)").bind(id, user.organizationId, body.customer_name?.trim() ?? "", title, user.email, priority, body.due_at ?? null).run();
    return json({ id, title, status: "open" }, 201);
  }
  if (path[0] === "tasks" && path[1] && method === "PATCH") {
    const body = await request.json() as { status?: string };
    if (!["open", "in_progress", "done", "cancelled"].includes(body.status ?? "")) return json({ error: "invalid_task_status" }, 422);
    const result = await DB.prepare("UPDATE tasks SET status = ? WHERE id = ? AND organization_id = ?").bind(body.status, path[1], user.organizationId).run();
    if (!result.meta.changes) return json({ error: "task_not_found" }, 404);
    return json({ id: path[1], status: body.status });
  }

  if (path[0] === "messages" && path.length === 1 && method === "GET") {
    const rows = await DB.prepare("SELECT id, channel, subject, content, status FROM message_drafts WHERE organization_id = ? ORDER BY created_at DESC LIMIT 100").bind(user.organizationId).all();
    return json({ items: rows.results });
  }
  if (path[0] === "messages" && path[1] && path[2] === "approve" && method === "POST") {
    const result = await DB.prepare("UPDATE message_drafts SET status = 'approved', approved_by = ? WHERE id = ? AND organization_id = ? AND status = 'pending_approval'").bind(user.email, path[1], user.organizationId).run();
    if (!result.meta.changes) return json({ error: "message_not_pending" }, 409);
    return json({ status: "approved" });
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

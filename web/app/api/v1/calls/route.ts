import { cookies } from "next/headers";
import { env } from "cloudflare:workers";
import { ensureCoreSchema } from "../../../../db/bootstrap";
import { getLocalUser, localAuthAvailable } from "../../../local-auth";
import { queryCalls } from "../../../call-query";

type Bindings = { DB: D1Database; AUDIO: R2Bucket };

function upstreamUrl() {
  const base = process.env.API_BASE_URL?.replace(/\/$/, "");
  return base ? `${base}/api/v1/calls` : null;
}

async function authHeaders(request: Request) {
  const headers = new Headers();
  const token = (await cookies()).get("mokalemeban_access_token")?.value;
  const authorization = request.headers.get("authorization") ?? (token ? `Bearer ${token}` : null);
  const idempotencyKey = request.headers.get("idempotency-key");
  if (authorization) headers.set("authorization", authorization);
  if (idempotencyKey) headers.set("idempotency-key", idempotencyKey);
  return headers;
}

export async function GET(request: Request) {
  const upstream = upstreamUrl();
  if (!upstream) {
    if (!localAuthAvailable()) return Response.json({ error: "processing_backend_not_configured" }, { status: 503 });
    const user = await getLocalUser(); if (!user) return Response.json({ error: "authentication_required" }, { status: 401 });
    const { DB } = env as unknown as Bindings; await ensureCoreSchema(DB);
    const ownOnly = user.role === "کارشناس" || user.role === "فروشنده";
    return Response.json(await queryCalls(DB, user.organizationId, new URL(request.url), ownOnly ? user.email : undefined));
  }
  const target = new URL(upstream); target.search = new URL(request.url).search;
  const response = await fetch(target, { headers: await authHeaders(request), cache: "no-store" });
  return new Response(response.body, { status: response.status, headers: response.headers });
}

export async function POST(request: Request) {
  const upstream = upstreamUrl();
  if (!upstream) {
    if (!localAuthAvailable()) return Response.json({ error: "processing_backend_not_configured" }, { status: 503 });
    const user = await getLocalUser(); if (!user) return Response.json({ error: "authentication_required" }, { status: 401 });
    if (user.role === "مشاهده‌گر") return Response.json({ error: "read_only_role" }, { status: 403 });
    const form = await request.formData(); const audio = form.get("audio");
    if (!(audio instanceof File)) return Response.json({ error: "audio_file_required" }, { status: 400 });
    if (!audio.type.startsWith("audio/")) return Response.json({ error: "unsupported_file_type" }, { status: 415 });
    if (audio.size > 500 * 1024 * 1024) return Response.json({ error: "file_too_large" }, { status: 413 });
    const { DB, AUDIO } = env as unknown as Bindings; await ensureCoreSchema(DB);
    const security = await DB.prepare("SELECT require_consent FROM security_settings WHERE organization_id = ?").bind(user.organizationId).first<{ require_consent: number }>();
    if ((security?.require_consent ?? 1) === 1 && form.get("consent") !== "true") return Response.json({ error: "recording_consent_required" }, { status: 422 });
    const id = `CL-${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
    const safeName = audio.name.replace(/[^\p{L}\p{N}._-]+/gu, "_");
    const objectKey = `${user.organizationId}/${id}/${safeName}`;
    await AUDIO.put(objectKey, audio.stream(), { httpMetadata: { contentType: audio.type }, customMetadata: { organizationId: user.organizationId, callId: id } });
    const now = new Date().toISOString();
    await DB.prepare(`INSERT INTO calls (id, organization_id, customer_name, seller_name, seller_email, original_file_name, object_key, mime_type, size_bytes, source, status, outcome, created_at, updated_at)
      VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, 'upload', 'uploaded', 'unknown', ?, ?)`).bind(id, user.organizationId, user.displayName, user.email, audio.name, objectKey, audio.type, audio.size, now, now).run();
    const created = await DB.prepare("SELECT * FROM calls WHERE id = ? AND organization_id = ?").bind(id, user.organizationId).first();
    return Response.json({ call: created }, { status: 201 });
  }
  const incoming = await request.formData();
  const audio = incoming.get("audio");
  if (!(audio instanceof File)) return Response.json({ error: "audio_file_required" }, { status: 400 });
  const body = new FormData();
  body.append("audio", audio, audio.name);
  body.append("recording_consent", incoming.get("consent") === "true" ? "true" : "false");
  const seller = incoming.get("seller");
  if (seller) body.append("seller_email", String(seller));
  const response = await fetch(upstream, { method: "POST", headers: await authHeaders(request), body });
  return new Response(response.body, { status: response.status, headers: response.headers });
}

import { cookies } from "next/headers";
import { handleLocalApi } from "../../../local-api";

type RouteContext = { params: Promise<{ path: string[] }> };

async function forward(request: Request, context: RouteContext) {
  const base = process.env.API_BASE_URL?.replace(/\/$/, "");
  const { path } = await context.params;
  if (!base) return handleLocalApi(request, path);
  const incomingUrl = new URL(request.url);
  const upstream = new URL(`${base}/api/v1/${path.map(encodeURIComponent).join("/")}`);
  upstream.search = incomingUrl.search;

  const headers = new Headers();
  const token = (await cookies()).get("mokalemeban_access_token")?.value;
  const authorization = request.headers.get("authorization") ?? (token ? `Bearer ${token}` : null);
  if (authorization) headers.set("authorization", authorization);
  for (const name of ["content-type", "idempotency-key", "x-recording-consent"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  const response = await fetch(upstream, { method, headers, body, cache: "no-store" });
  return new Response(response.body, { status: response.status, headers: response.headers });
}

export function GET(request: Request, context: RouteContext) { return forward(request, context); }
export function POST(request: Request, context: RouteContext) { return forward(request, context); }
export function PATCH(request: Request, context: RouteContext) { return forward(request, context); }
export function DELETE(request: Request, context: RouteContext) { return forward(request, context); }

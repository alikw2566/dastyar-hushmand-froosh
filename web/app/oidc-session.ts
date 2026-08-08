import { cookies } from "next/headers";
import { oidcClientId, oidcInternalIssuer } from "./oidc-config";

export async function hasRefreshToken() {
  return Boolean((await cookies()).get("mokalemeban_refresh_token")?.value);
}

export async function validAccessToken(): Promise<string | null> {
  const token = (await cookies()).get("mokalemeban_access_token")?.value;
  if (token) {
    try {
      const payload = token.split(".")[1]?.replace(/-/g, "+").replace(/_/g, "/");
      const claims = payload ? JSON.parse(atob(payload.padEnd(Math.ceil(payload.length / 4) * 4, "="))) as { exp?: number } : {};
      if (!claims.exp || claims.exp * 1000 > Date.now() + 30_000) return token;
    } catch { /* A malformed token is replaced through the refresh flow. */ }
  }
  return refreshAccessToken();
}

export async function refreshAccessToken(): Promise<string | null> {
  const jar = await cookies();
  const refreshToken = jar.get("mokalemeban_refresh_token")?.value;
  const issuer = oidcInternalIssuer();
  if (!refreshToken || !issuer) return null;
  const response = await fetch(`${issuer.replace(/\/$/, "")}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      client_id: oidcClientId(),
      refresh_token: refreshToken,
    }),
    cache: "no-store",
  });
  if (!response.ok) {
    jar.delete("mokalemeban_access_token"); jar.delete("mokalemeban_refresh_token");
    return null;
  }
  const tokens = await response.json() as { access_token: string; refresh_token?: string; expires_in?: number; refresh_expires_in?: number };
  const appUrl = process.env.APP_URL ?? "";
  const secure = process.env.NODE_ENV === "production" && appUrl.startsWith("https://");
  jar.set("mokalemeban_access_token", tokens.access_token, { httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: tokens.expires_in ?? 300 });
  if (tokens.refresh_token) jar.set("mokalemeban_refresh_token", tokens.refresh_token, { httpOnly: true, sameSite: "strict", secure, path: "/", maxAge: tokens.refresh_expires_in ?? 60 * 60 * 8 });
  return tokens.access_token;
}

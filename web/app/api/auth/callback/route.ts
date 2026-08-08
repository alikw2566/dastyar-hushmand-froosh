import { cookies } from "next/headers";
import { oidcClientId, oidcExternalIssuer, oidcInternalIssuer } from "../../../oidc-config";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const issuer = oidcExternalIssuer();
  const tokenIssuer = oidcInternalIssuer();
  const clientId = oidcClientId();
  const appUrl = process.env.APP_URL ?? url.origin;
  const jar = await cookies();
  const expectedState = jar.get("mokalemeban_oauth_state")?.value;
  const verifier = jar.get("mokalemeban_oauth_verifier")?.value;
  const returnToValue = jar.get("mokalemeban_oauth_return_to")?.value ?? "/";
  const returnTo = returnToValue.startsWith("/") && !returnToValue.startsWith("//") ? returnToValue : "/";
  if (!issuer || !tokenIssuer || !code || !state || state !== expectedState || !verifier) {
    return Response.json({ error: "invalid_oauth_callback" }, { status: 400 });
  }

  const tokenResponse = await fetch(`${tokenIssuer.replace(/\/$/, "")}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: clientId,
      code,
      code_verifier: verifier,
      redirect_uri: `${appUrl}/api/auth/callback`,
    }),
  });
  if (!tokenResponse.ok) return Response.json({ error: "token_exchange_failed" }, { status: 502 });
  const tokens = await tokenResponse.json() as { access_token: string; refresh_token?: string; expires_in?: number };
  const secure = process.env.NODE_ENV === "production" && appUrl.startsWith("https://");
  jar.set("mokalemeban_access_token", tokens.access_token, {
    httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: tokens.expires_in ?? 300,
  });
  if (tokens.refresh_token) {
    jar.set("mokalemeban_refresh_token", tokens.refresh_token, {
      httpOnly: true, sameSite: "strict", secure, path: "/", maxAge: 60 * 60 * 8,
    });
  }
  jar.delete("mokalemeban_oauth_state");
  jar.delete("mokalemeban_oauth_verifier");
  jar.delete("mokalemeban_oauth_return_to");
  return Response.redirect(new URL(returnTo, appUrl));
}

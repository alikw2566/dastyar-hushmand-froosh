import { cookies } from "next/headers";

function base64Url(bytes: Uint8Array) {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const registration = requestUrl.searchParams.get("mode") === "register";
  const requestedReturnTo = requestUrl.searchParams.get("returnTo") ?? "/";
  const returnTo = requestedReturnTo.startsWith("/") && !requestedReturnTo.startsWith("//") ? requestedReturnTo : "/";
  const issuer = process.env.OIDC_ISSUER;
  if (!issuer) return Response.json({ error: "oidc_not_configured" }, { status: 503 });
  const clientId = process.env.OIDC_CLIENT_ID ?? "mokalemeban-web";
  const appUrl = process.env.APP_URL ?? new URL(request.url).origin;
  const state = base64Url(crypto.getRandomValues(new Uint8Array(24)));
  const verifier = base64Url(crypto.getRandomValues(new Uint8Array(48)));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  const challenge = base64Url(new Uint8Array(digest));
  const jar = await cookies();
  const secure = process.env.NODE_ENV === "production" && appUrl.startsWith("https://");
  jar.set("mokalemeban_oauth_state", state, { httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: 600 });
  jar.set("mokalemeban_oauth_verifier", verifier, { httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: 600 });
  jar.set("mokalemeban_oauth_return_to", returnTo, { httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: 600 });

  const endpoint = registration ? "registrations" : "auth";
  const url = new URL(`${issuer.replace(/\/$/, "")}/protocol/openid-connect/${endpoint}`);
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", "openid profile email");
  url.searchParams.set("redirect_uri", `${appUrl}/api/auth/callback`);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  return Response.redirect(url);
}

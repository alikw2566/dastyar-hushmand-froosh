import { refreshAccessToken } from "../../../oidc-session";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const requested = url.searchParams.get("returnTo") ?? "/";
  const returnTo = requested.startsWith("/") && !requested.startsWith("//") ? requested : "/";
  const token = await refreshAccessToken();
  return Response.redirect(new URL(token ? returnTo : "/auth", process.env.APP_URL ?? url.origin));
}

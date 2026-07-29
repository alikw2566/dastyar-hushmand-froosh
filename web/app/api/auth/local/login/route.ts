import { loginLocalAccount } from "../../../../local-auth";

export async function POST(request: Request) {
  try {
    const body = await request.json() as { email?: string; password?: string };
    await loginLocalAccount(body.email ?? "", body.password ?? "");
    return Response.json({ status: "authenticated" });
  } catch (cause) {
    const code = cause instanceof Error ? cause.message : "login_failed";
    return Response.json({ error: code }, { status: code === "local_auth_disabled" ? 404 : 401 });
  }
}

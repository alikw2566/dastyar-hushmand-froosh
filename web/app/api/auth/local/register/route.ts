import { registerLocalAccount } from "../../../../local-auth";

export async function POST(request: Request) {
  try {
    const body = await request.json() as { fullName?: string; email?: string; password?: string; organizationName?: string };
    await registerLocalAccount({ fullName: body.fullName ?? "", email: body.email ?? "", password: body.password ?? "", organizationName: body.organizationName ?? "" });
    return Response.json({ status: "created" }, { status: 201 });
  } catch (cause) {
    const code = cause instanceof Error ? cause.message : "registration_failed";
    const status = code === "email_exists" ? 409 : code === "local_auth_disabled" ? 404 : 422;
    return Response.json({ error: code }, { status });
  }
}

import { cookies } from "next/headers";
import { localAuthAvailable, logoutLocalAccount } from "../../../local-auth";

export async function GET(request: Request) {
  const jar = await cookies();
  jar.delete("mokalemeban_access_token");
  jar.delete("mokalemeban_refresh_token");
  if (localAuthAvailable()) await logoutLocalAccount();
  return Response.redirect(new URL("/auth", request.url));
}

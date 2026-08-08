import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getChatGPTUser, getPrivateOidcUser } from "./chatgpt-auth";
import { hasRefreshToken } from "./oidc-session";
import { getLocalUser } from "./local-auth";
import { SalesDashboard } from "./sales-dashboard";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "مرکز عملیات فروش",
  description: "تحلیل هوشمند تماس‌های فروش، مربیگری تیم و مدیریت پیگیری‌ها",
};

export default async function Home() {
  const user = (await getPrivateOidcUser()) ?? (await getChatGPTUser()) ?? (await getLocalUser());
  if (!user && await hasRefreshToken()) redirect("/api/auth/refresh?returnTo=%2F");
  if (!user) redirect("/auth");

  return (
    <SalesDashboard
      currentUser={{
        name: user.displayName,
        email: user.email,
        role: user.role ?? "مشاهده‌گر",
      }}
    />
  );
}

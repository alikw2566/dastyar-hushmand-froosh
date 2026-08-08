"use client";

import { FormEvent, useState } from "react";
import { ArrowLeft, Building2, KeyRound, Mail, UserRound } from "lucide-react";

const messages: Record<string, string> = {
  invalid_credentials: "ایمیل یا رمز عبور صحیح نیست.", email_exists: "قبلاً با این ایمیل حساب ساخته شده است.",
  invalid_email: "ایمیل معتبر وارد کنید.", invalid_profile: "نام و نام فضای کاری را کامل وارد کنید.",
  weak_password: "رمز عبور باید حداقل ۱۰ کاراکتر و دارای عدد باشد.", request_failed: "ارتباط با سرویس ورود برقرار نشد.",
};

export function LocalAuthForm({ adminIntent = false }: { adminIntent?: boolean }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const response = await fetch(`/api/auth/local/${mode}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(values) });
      const body = await response.json() as { error?: string };
      if (!response.ok) throw new Error(body.error ?? "request_failed");
      window.location.href = adminIntent ? "/?view=admin" : "/";
    } catch (cause) { const code = cause instanceof Error ? cause.message : "request_failed"; setError(messages[code] ?? messages.request_failed); setBusy(false); }
  }

  return <div className="local-auth">
    <div className="local-auth-tabs"><button className={mode === "login" ? "active" : ""} onClick={() => { setMode("login"); setError(""); }}>ورود</button><button className={mode === "register" ? "active" : ""} onClick={() => { setMode("register"); setError(""); }}>ساخت حساب</button></div>
    <form onSubmit={submit}>
      {mode === "register" && <><label><span><UserRound size={15} /> نام و نام خانوادگی</span><input name="fullName" required minLength={2} autoComplete="name" /></label><label><span><Building2 size={15} /> نام شرکت یا تیم</span><input name="organizationName" required minLength={2} autoComplete="organization" /></label></>}
      <label><span><Mail size={15} /> ایمیل</span><input name="email" type="email" required autoComplete="email" dir="ltr" /></label>
      <label><span><KeyRound size={15} /> رمز عبور</span><input name="password" type="password" required minLength={10} autoComplete={mode === "login" ? "current-password" : "new-password"} dir="ltr" /></label>
      {mode === "register" && <small>حداقل ۱۰ کاراکتر و شامل یک عدد</small>}
      {error && <p className="live-form-error">{error}</p>}
      <button disabled={busy}>{busy ? "لطفاً صبر کنید..." : <>{mode === "login" ? adminIntent ? "ورود به پنل مدیریت" : "ورود به مکالمه‌بان" : "ساخت حساب و ورود"}<ArrowLeft size={17} /></>}</button>
    </form>
  </div>;
}

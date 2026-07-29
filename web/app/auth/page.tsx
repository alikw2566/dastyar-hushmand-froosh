import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getChatGPTUser, getPrivateOidcUser } from "../chatgpt-auth";
import { getLocalUser, localAuthAvailable } from "../local-auth";
import { LocalAuthForm } from "./local-auth-form";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "ورود یا ساخت حساب" };

export default async function AuthPage({ searchParams }: { searchParams: Promise<{ admin?: string }> }) {
  const user = (await getPrivateOidcUser()) ?? (await getChatGPTUser()) ?? (await getLocalUser());
  if (user) redirect("/");
  const adminIntent = (await searchParams).admin === "1";
  const oidcReady = Boolean(process.env.OIDC_ISSUER);
  const localReady = localAuthAvailable();

  return <main className="auth-page">
    <section className="auth-visual">
      <div className="auth-logo"><span>م</span><div><strong>مکالمه‌بان</strong><small>دستیار هوشمند فروش</small></div></div>
      <div className="auth-copy"><h1>هر تماس را به یک <em>تصمیم بهتر</em> تبدیل کنید.</h1><p>رونویسی دقیق، تحلیل عملکرد فروشنده، پیگیری مشتری و مربیگری تیم فروش در یک فضای کاری امن.</p></div>
      <div className="auth-points"><span>متن کامل مکالمه</span><span>تحلیل مبتنی بر شاهد</span><span>فضای کاری اختصاصی</span></div>
    </section>
    <section className="auth-panel"><div className="auth-card"><div className="auth-card-kicker"><span>{adminIntent ? "دسترسی مدیریتی" : "شروع کار"}</span><a className="admin-login-icon" href={adminIntent ? "/auth" : "/auth?admin=1"} title={adminIntent ? "بازگشت به ورود عادی" : "ورود مدیر"} aria-label={adminIntent ? "بازگشت به ورود عادی" : "ورود به پنل مدیریت"}>{adminIntent ? "←" : "♜"}</a></div><h2>{adminIntent ? "ورود به پنل مدیریت" : "ورود به حساب کاربری"}</h2><p>{adminIntent ? "با حساب دارای نقش مدیر وارد شوید تا مستقیماً پنل مدیریت باز شود." : "اگر اولین بار است وارد می‌شوید، حساب جدید و فضای کاری خود را بسازید."}</p>
      {oidcReady ? <div className="auth-action"><a className="primary" href={adminIntent ? "/api/auth/login?returnTo=%2F%3Fview%3Dadmin" : "/api/auth/login"}>{adminIntent ? "ورود مدیر" : "ورود به حساب"}</a>{adminIntent ? <a className="secondary" href="/auth">بازگشت به ورود عادی</a> : <a className="secondary" href="/api/auth/login?mode=register">ساخت حساب جدید</a>}</div> : localReady ? <LocalAuthForm adminIntent={adminIntent} /> : <div className="auth-note"><strong>سرویس ورود در دسترس نیست.</strong></div>}
      <div className="auth-note">اطلاعات هر شرکت جدا نگهداری می‌شود و کاربران شرکت‌های دیگر به فضای کاری شما دسترسی ندارند.</div>
    </div></section>
  </main>;
}

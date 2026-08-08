import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ArrowRight, AudioLines, BadgeCheck, FileAudio2, Settings2, ShieldCheck } from "lucide-react";
import { getChatGPTUser, getPrivateOidcUser } from "../chatgpt-auth";
import { ConversationField } from "../conversation-field";
import { getLocalUser, localAuthAvailable } from "../local-auth";
import { oidcExternalIssuer } from "../oidc-config";
import { LocalAuthForm } from "./local-auth-form";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "ورود یا ساخت حساب" };

export default async function AuthPage({ searchParams }: { searchParams: Promise<{ admin?: string; error?: string }> }) {
  const user = (await getPrivateOidcUser()) ?? (await getChatGPTUser()) ?? (await getLocalUser());
  if (user) redirect("/");
  const params = await searchParams;
  const adminIntent = params.admin === "1";
  const oidcReady = Boolean(oidcExternalIssuer());
  const localReady = localAuthAvailable();
  const identityUnavailable = params.error === "identity_service_unavailable";

  return <main className="auth-page">
    <section className="auth-visual">
      <ConversationField variant="auth" />
      <div className="auth-logo"><span><AudioLines size={25} /></span><div><strong>مکالمه‌بان</strong><small>دستیار هوشمند فروش</small></div></div>
      <div className="auth-copy"><h1>هر تماس را به یک <em>تصمیم بهتر</em> تبدیل کنید.</h1><p>رونویسی دقیق، تحلیل عملکرد فروشنده، پیگیری مشتری و مربیگری تیم فروش در یک فضای کاری امن.</p></div>
      <div className="auth-points"><span><FileAudio2 size={16} /> متن کامل مکالمه</span><span><BadgeCheck size={16} /> تحلیل مبتنی بر شاهد</span><span><ShieldCheck size={16} /> فضای کاری اختصاصی</span></div>
    </section>
    <section className="auth-panel"><div className="auth-card"><div className="auth-card-kicker"><span>{adminIntent ? "دسترسی مدیریتی" : "شروع کار"}</span><a className="admin-login-icon" href={adminIntent ? "/auth" : "/auth?admin=1"} title={adminIntent ? "بازگشت به ورود عادی" : "ورود مدیر"} aria-label={adminIntent ? "بازگشت به ورود عادی" : "ورود به پنل مدیریت"}>{adminIntent ? <ArrowRight size={19} /> : <Settings2 size={19} />}</a></div><h2>{adminIntent ? "ورود به پنل مدیریت" : "ورود به حساب کاربری"}</h2><p>{adminIntent ? "با حساب دارای نقش مدیر وارد شوید تا مستقیماً پنل مدیریت باز شود." : localReady ? "وارد حساب خود شوید یا در چند مرحله کوتاه حساب و فضای کاری جدید بسازید." : "با حساب سازمانی وارد شوید. حساب کاربران پایلوت توسط مدیر شرکت ساخته یا دعوت می‌شود."}</p>
      {identityUnavailable && oidcReady && <div className="auth-error" role="alert"><strong>سرویس ورود در دسترس نیست.</strong><span>برای ورود، سرویس‌های پروژه را با Docker Compose اجرا کنید و دوباره تلاش کنید.</span></div>}
      {oidcReady ? <div className="auth-action"><a className="primary" href={adminIntent ? "/api/auth/login?returnTo=%2F%3Fview%3Dadmin" : "/api/auth/login"}>{adminIntent ? "ورود مدیر" : "ورود به حساب"}</a>{adminIntent ? <a className="secondary" href="/auth">بازگشت به ورود عادی</a> : <span className="secondary disabled" title="حساب پایلوت توسط مدیر شرکت ساخته می‌شود">ساخت حساب با دعوت مدیر</span>}</div> : localReady ? <LocalAuthForm adminIntent={adminIntent} /> : <div className="auth-error" role="alert"><strong>سرویس ورود سازمانی پیکربندی نشده است.</strong><span>متغیر OIDC_ISSUER باید در محیط سرور تنظیم شود.</span></div>}
      <div className="auth-note">اطلاعات هر شرکت جدا نگهداری می‌شود و کاربران شرکت‌های دیگر به فضای کاری شما دسترسی ندارند.</div>
    </div></section>
  </main>;
}

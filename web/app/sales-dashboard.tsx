"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AdminPanel } from "./admin-panel";
import { CallDetailView, CallsExplorer, CallItem, CallTable, FollowupsView, TaskItem, fa, requestJson } from "./pilot-views";

type View = "overview" | "calls" | "tasks" | "messages" | "settings";
type CurrentUser = { name: string; email: string; role: string };
type OverviewData = { total_calls: number; completed_calls: number; average_score: number | null; confirmed_conversion_rate: number | null };
type MessageItem = { id: string; channel: string; subject?: string | null; content: string; status: string };
type Organization = { id: string; name: string; plan: string; monthly_minute_limit: number; retention_days: number; automation_mode: string; used_minutes: number };

const nav: Array<{ id: View; label: string; icon: string }> = [
  { id: "overview", label: "نمای کلی", icon: "⌂" },
  { id: "calls", label: "تماس‌ها", icon: "☎" },
  { id: "tasks", label: "پیگیری‌ها", icon: "✓" },
  { id: "messages", label: "پیام‌ها", icon: "✉" },
  { id: "settings", label: "پنل مدیریت", icon: "♜" },
];
const statusLabel: Record<string, string> = { pending_approval: "منتظر تأیید", approved: "تأییدشده", scheduled: "زمان‌بندی‌شده", sent: "ارسال‌شده", failed: "ناموفق" };
const channelLabel: Record<string, string> = { sms: "پیامک", whatsapp: "واتساپ", email: "ایمیل" };

function initialView(role: string): View {
  if (typeof window === "undefined") return "overview";
  const value = new URLSearchParams(window.location.search).get("view");
  if (value === "settings" || value === "admin") return ["مدیر", "مدیر فروش", "سرپرست"].includes(role) ? "settings" : "overview";
  return ["overview", "calls", "tasks", "messages"].includes(value ?? "") ? value as View : "overview";
}

export function SalesDashboard({ currentUser }: { currentUser: CurrentUser }) {
  const [view, setView] = useState<View>(() => initialView(currentUser.role));
  const [selectedCallId, setSelectedCallId] = useState<string | null>(() => typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("call"));
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [menuOpen, setMenuOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [overview, setOverview] = useState<OverviewData>({ total_calls: 0, completed_calls: 0, average_score: null, confirmed_conversion_rate: null });
  const [recentCalls, setRecentCalls] = useState<CallItem[]>([]);
  const [pendingTasks, setPendingTasks] = useState(0);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);

  const loadShell = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [overviewData, callData, taskData, orgData] = await Promise.all([
        requestJson<OverviewData>("/api/v1/overview"),
        requestJson<{ items?: CallItem[]; calls?: CallItem[] }>("/api/v1/calls?page=1&page_size=5&sort=created_at&order=desc"),
        requestJson<{ items: TaskItem[] }>("/api/v1/tasks?bucket=all"),
        requestJson<Organization>("/api/v1/admin/organization"),
      ]);
      const canReviewMessages = ["مدیر", "مدیر فروش", "سرپرست"].includes(currentUser.role);
      const messageData = canReviewMessages ? await requestJson<{ items: MessageItem[] }>("/api/v1/messages") : { items: [] };
      setOverview(overviewData); setRecentCalls(callData.items ?? callData.calls ?? []);
      setPendingTasks((taskData.items ?? []).filter((item) => !["done", "cancelled"].includes(item.status)).length);
      setMessages(messageData.items ?? []); setOrganization(orgData);
    } catch (cause) {
      setError(cause instanceof Error && cause.message === "processing_backend_not_configured"
        ? "سرویس پردازش اجرا نشده است. سامانه را با Docker Compose اجرا کنید."
        : cause instanceof Error ? cause.message : "دریافت اطلاعات انجام نشد.");
    } finally { setLoading(false); }
  }, [currentUser.role]);
  useEffect(() => { const timer = window.setTimeout(() => void loadShell(), 0); return () => window.clearTimeout(timer); }, [loadShell]);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(""), 4200); return () => window.clearTimeout(timer); }, [toast]);

  const waitingMessages = useMemo(() => messages.filter((item) => item.status === "pending_approval").length, [messages]);
  const readOnly = currentUser.role === "مشاهده‌گر";
  const canExportCalls = ["مدیر", "مدیر فروش", "سرپرست"].includes(currentUser.role);
  const visibleNav = useMemo(() => nav.filter((item) => {
    if (["مدیر", "مدیر فروش", "سرپرست"].includes(currentUser.role)) return true;
    if (currentUser.role === "مشاهده‌گر") return item.id === "overview" || item.id === "calls";
    return item.id !== "messages" && item.id !== "settings";
  }), [currentUser.role]);
  function chooseView(next: View) {
    setView(next); setSelectedCallId(null); setMenuOpen(false);
    const url = new URL(window.location.href); url.searchParams.set("view", next); url.searchParams.delete("call");
    if (next !== "calls") for (const key of [...url.searchParams.keys()]) if (!["view", "task_bucket"].includes(key)) url.searchParams.delete(key);
    window.history.replaceState({}, "", url.pathname + "?" + url.searchParams.toString());
  }
  function openCall(id: string) {
    setSelectedCallId(id); setMenuOpen(false);
    const url = new URL(window.location.href); url.searchParams.set("call", id); window.history.replaceState({}, "", url.pathname + "?" + url.searchParams.toString());
  }
  function closeCall() {
    setSelectedCallId(null); const url = new URL(window.location.href); url.searchParams.delete("call"); window.history.replaceState({}, "", url.pathname + "?" + url.searchParams.toString());
  }

  return <div className="live-shell">
    <aside className={"live-sidebar " + (menuOpen ? "open" : "")}>
      <div className="live-brand"><span>م</span><div><strong>مکالمه‌بان</strong><small>دستیار هوشمند فروش</small></div></div>
      <div className="live-workspace"><small>فضای کاری</small><strong>{organization?.name ?? "در حال دریافت..."}</strong><span>{organization ? "پلن " + organization.plan : ""}</span></div>
      <nav>{visibleNav.map((item) => <button key={item.id} className={(view === item.id && !selectedCallId ? "active " : "") + (item.id === "settings" ? "admin-entry" : "")} onClick={() => chooseView(item.id)}><i>{item.icon}</i>{item.label}{item.id === "settings" && <small>فقط مدیر</small>}{item.id === "tasks" && pendingTasks > 0 && <b>{fa(pendingTasks)}</b>}{item.id === "messages" && waitingMessages > 0 && <b>{fa(waitingMessages)}</b>}</button>)}</nav>
      <div className="live-account"><span>{currentUser.name.slice(0, 1)}</span><div><strong>{currentUser.name}</strong><small>{currentUser.email}</small></div><a href="/api/auth/logout" title="خروج">↪</a></div>
    </aside>
    {menuOpen && <button className="live-scrim" onClick={() => setMenuOpen(false)} aria-label="بستن منو" />}
    <main className="live-main">
      <header className="live-top"><button className="live-menu" onClick={() => setMenuOpen(true)}>☰</button><div><strong>{selectedCallId ? "جزئیات تماس" : visibleNav.find((item) => item.id === view)?.label}</strong><small>اطلاعات واقعی فضای کاری شما</small></div><button className="live-theme" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>{theme === "light" ? "☾" : "☀"}</button></header>
      <div className="live-content">
        {loading && !selectedCallId && <StateCard title="در حال دریافت اطلاعات" description="چند لحظه صبر کنید..." />}
        {!loading && error && !selectedCallId && <StateCard title="اتصال برقرار نشد" description={error} action={<button onClick={() => void loadShell()}>تلاش دوباره</button>} tone="error" />}
        {selectedCallId && <CallDetailView callId={selectedCallId} isAdmin={currentUser.role === "مدیر"} readOnly={readOnly} canReprocess={canExportCalls} onBack={closeCall} onToast={setToast} />}
        {!loading && !error && !selectedCallId && view === "overview" && <Overview overview={overview} calls={recentCalls} pendingTasks={pendingTasks} canUpload={!readOnly} onUpload={() => setUploadOpen(true)} onCalls={() => chooseView("calls")} onOpen={openCall} />}
        {!loading && !error && !selectedCallId && view === "calls" && <CallsExplorer canUpload={!readOnly} canExport={canExportCalls} onUpload={() => setUploadOpen(true)} onOpen={openCall} />}
        {!loading && !error && !selectedCallId && view === "tasks" && <FollowupsView onOpenCall={openCall} onToast={setToast} onCountChanged={loadShell} />}
        {!loading && !error && !selectedCallId && view === "messages" && <Messages items={messages} onChanged={loadShell} onToast={setToast} />}
        {!loading && !error && !selectedCallId && view === "settings" && <AdminPanel key={(organization?.id ?? "") + "-" + (organization?.name ?? "")} organization={organization} currentRole={currentUser.role} onOrganizationChanged={loadShell} onToast={setToast} />}
      </div>
    </main>
    {uploadOpen && <UploadDialog currentUser={currentUser} onClose={() => setUploadOpen(false)} onDone={async () => { setUploadOpen(false); setToast("تماس ثبت شد؛ وضعیت پردازش را در فهرست ببینید."); await loadShell(); chooseView("calls"); }} />}
    {toast && <div className="live-toast" role="status">{toast}</div>}
  </div>;
}

function StateCard({ title, description, action, tone }: { title: string; description: string; action?: React.ReactNode; tone?: string }) {
  return <section className={"live-state " + (tone ?? "")}><span>{tone === "error" ? "!" : "…"}</span><h1>{title}</h1><p>{description}</p>{action}</section>;
}
function Overview({ overview, calls, pendingTasks, canUpload, onUpload, onCalls, onOpen }: { overview: OverviewData; calls: CallItem[]; pendingTasks: number; canUpload: boolean; onUpload: () => void; onCalls: () => void; onOpen: (id: string) => void }) {
  return <><div className="live-heading"><div><span>مرکز عملیات</span><h1>نمای واقعی عملکرد فروش</h1><p>اعداد این صفحه مستقیماً از تماس‌های فضای کاری محاسبه می‌شوند.</p></div>{canUpload && <button onClick={onUpload}>＋ افزودن تماس</button>}</div>
    <section className="live-metrics"><Metric label="کل تماس‌ها" value={fa(overview.total_calls)} /><Metric label="تکمیل‌شده" value={fa(overview.completed_calls)} /><Metric label="امتیاز متوسط" value={overview.average_score == null ? "—" : fa(overview.average_score)} /><Metric label="نرخ تبدیل تأییدشده" value={overview.confirmed_conversion_rate == null ? "—" : fa(overview.confirmed_conversion_rate) + "٪"} /><Metric label="پیگیری باز" value={fa(pendingTasks)} /></section>
    <section className="live-panel"><div className="live-panel-head"><div><h2>آخرین تماس‌ها</h2><p>آخرین فایل‌های ثبت‌شده در سامانه</p></div>{calls.length > 0 && <button onClick={onCalls}>مشاهده همه</button>}</div>{calls.length === 0 ? <Empty title="هنوز تماسی ثبت نشده است" description={canUpload ? "اولین فایل صوتی را اضافه کنید تا پردازش آغاز شود." : "تماسی برای مشاهده ثبت نشده است."} action={canUpload ? <button onClick={onUpload}>آپلود اولین تماس</button> : undefined} /> : <CallTable calls={calls} onOpen={onOpen} />}</section></>;
}
function Metric({ label, value }: { label: string; value: string }) { return <article><span>{label}</span><strong>{value}</strong></article>; }
function Messages({ items, onChanged, onToast }: { items: MessageItem[]; onChanged: () => Promise<void>; onToast: (value: string) => void }) {
  async function approve(id: string) { try { await requestJson("/api/v1/messages/" + id + "/approve", { method: "POST" }); await onChanged(); onToast("پیام تأیید شد"); } catch (cause) { onToast(cause instanceof Error ? cause.message : "تأیید پیام انجام نشد"); } }
  return <><div className="live-heading"><div><span>ارتباط با مشتری</span><h1>پیش‌نویس پیام‌ها</h1><p>فقط پیام‌های ساخته‌شده از تحلیل‌های واقعی نمایش داده می‌شوند.</p></div></div><section className="live-panel">{items.length === 0 ? <Empty title="پیامی وجود ندارد" description="پس از تحلیل تماس و پیشنهاد پیگیری، پیش‌نویس پیام اینجا ظاهر می‌شود." /> : <div className="live-message-list">{items.map((item) => <article key={item.id}><header><span>{channelLabel[item.channel] ?? item.channel}</span><b className={"live-badge " + item.status}>{statusLabel[item.status] ?? item.status}</b></header>{item.subject && <h3>{item.subject}</h3>}<p>{item.content}</p>{item.status === "pending_approval" && <button onClick={() => void approve(item.id)}>تأیید پیام</button>}</article>)}</div>}</section></>;
}
function UploadDialog({ currentUser, onClose, onDone }: { currentUser: CurrentUser; onClose: () => void; onDone: () => Promise<void> }) {
  const input = useRef<HTMLInputElement>(null); const [file, setFile] = useState<File | null>(null); const [consent, setConsent] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function submit(event: FormEvent) { event.preventDefault(); if (!file || !consent) return; setBusy(true); setError(""); const body = new FormData(); body.append("audio", file); body.append("seller", currentUser.email); body.append("consent", "true"); try { await requestJson("/api/v1/calls", { method: "POST", body }); await onDone(); } catch (cause) { setError(cause instanceof Error ? cause.message : "آپلود انجام نشد"); setBusy(false); } }
  return <div className="live-modal"><button className="live-modal-bg" onClick={onClose} aria-label="بستن" /><form onSubmit={submit}><header><div><span>تماس جدید</span><h2>آپلود فایل صوتی</h2></div><button type="button" onClick={onClose}>×</button></header><input ref={input} type="file" accept="audio/*" hidden onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><button type="button" className="live-drop" onClick={() => input.current?.click()}><strong>{file ? file.name : "انتخاب فایل صوتی"}</strong><small>{file ? fa((file.size / 1024 / 1024).toFixed(1)) + " مگابایت" : "MP3، WAV، M4A یا OGG تا ۵۰۰ مگابایت"}</small></button><label className="live-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>تأیید می‌کنم رضایت لازم برای ضبط و پردازش این تماس دریافت شده است.</span></label>{error && <p className="live-form-error">{error}</p>}<footer><button type="button" className="secondary" onClick={onClose}>انصراف</button><button disabled={!file || !consent || busy}>{busy ? "در حال ارسال..." : "شروع پردازش"}</button></footer></form></div>;
}
function Empty({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) { return <div className="live-empty"><span>＋</span><h3>{title}</h3><p>{description}</p>{action}</div>; }

"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AdminPanel } from "./admin-panel";

type View = "overview" | "calls" | "tasks" | "messages" | "settings";
type CurrentUser = { name: string; email: string; role: string };
type OverviewData = { total_calls: number; completed_calls: number; average_score: number | null; confirmed_conversion_rate: number | null };
type CallItem = { id: string; customer_name?: string | null; seller_email?: string | null; seller_name?: string | null; original_file_name: string; status: string; outcome: string; duration_seconds?: number | null; score?: number | null; created_at: string };
type TaskItem = { id: string; title: string; customer?: string | null; priority: string; status: string; due_at?: string | null };
type MessageItem = { id: string; channel: string; subject?: string | null; content: string; status: string };
type Organization = { id: string; name: string; plan: string; monthly_minute_limit: number; retention_days: number; automation_mode: string; used_minutes: number };
type CallDetailData = { call: CallItem; analysis?: Record<string, unknown> | null; segments?: Array<{ id: string; speaker: string; role: string; start?: number | null; end?: number | null; content: string }>; audio_url?: string | null };

const nav: Array<{ id: View; label: string; icon: string }> = [
  { id: "overview", label: "نمای کلی", icon: "⌂" },
  { id: "calls", label: "تماس‌ها", icon: "☎" },
  { id: "tasks", label: "پیگیری‌ها", icon: "✓" },
  { id: "messages", label: "پیام‌ها", icon: "✉" },
  { id: "settings", label: "پنل مدیریت", icon: "♜" },
];

const statusLabel: Record<string, string> = {
  received: "دریافت‌شده", uploaded: "آپلودشده", queued: "در صف", transcribing: "در حال رونویسی",
  analyzing: "در حال تحلیل", review_needed: "نیازمند بازبینی", completed: "تکمیل‌شده", failed: "ناموفق",
  open: "باز", in_progress: "در حال انجام", done: "انجام‌شده", cancelled: "لغوشده",
  pending_approval: "منتظر تأیید", approved: "تأییدشده", scheduled: "زمان‌بندی‌شده", sent: "ارسال‌شده",
};
const outcomeLabel: Record<string, string> = { won: "فروش", lost: "ناموفق", follow_up: "پیگیری", unknown: "نامشخص" };
const channelLabel: Record<string, string> = { sms: "پیامک", whatsapp: "واتساپ", email: "ایمیل" };

function fa(value: string | number) { return String(value).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]); }
function formatDate(value?: string | null) { return value ? new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—"; }
function formatDuration(seconds?: number | null) { if (!seconds) return "—"; return fa(`${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`); }

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((body as { detail?: string; error?: string }).detail ?? (body as { error?: string }).error ?? "request_failed");
  return body as T;
}

export function SalesDashboard({ currentUser }: { currentUser: CurrentUser }) {
  const [view, setView] = useState<View>("overview");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [menuOpen, setMenuOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [overview, setOverview] = useState<OverviewData>({ total_calls: 0, completed_calls: 0, average_score: null, confirmed_conversion_rate: null });
  const [calls, setCalls] = useState<CallItem[]>([]);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [selectedCall, setSelectedCall] = useState<CallDetailData | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [overviewData, callData, taskData] = await Promise.all([
        requestJson<OverviewData>("/api/v1/overview"),
        requestJson<{ items?: CallItem[]; calls?: CallItem[] }>("/api/v1/calls"),
        requestJson<{ items: TaskItem[] }>("/api/v1/tasks"),
      ]);
      const canReviewMessages = currentUser.role === "مدیر" || currentUser.role === "سرپرست";
      const messageData = canReviewMessages ? await requestJson<{ items: MessageItem[] }>("/api/v1/messages") : { items: [] };
      const orgData = await requestJson<Organization>("/api/v1/admin/organization");
      setOverview(overviewData); setCalls(callData.items ?? callData.calls ?? []); setTasks(taskData.items ?? []);
      setMessages(messageData.items ?? []); setOrganization(orgData);
    } catch (cause) {
      setError(cause instanceof Error && cause.message === "processing_backend_not_configured"
        ? "سرویس پردازش هنوز اجرا نشده است. سامانه را با Docker Compose اجرا کنید."
        : "دریافت اطلاعات انجام نشد. اتصال API و ورود کاربر را بررسی کنید.");
    } finally { setLoading(false); }
  }, [currentUser.role]);

  useEffect(() => { const id = window.setTimeout(() => { void loadAll(); }, 0); return () => window.clearTimeout(id); }, [loadAll]);
  useEffect(() => {
    if (currentUser.role !== "مدیر" || new URLSearchParams(window.location.search).get("view") !== "admin") return;
    const id = window.setTimeout(() => setView("settings"), 0);
    return () => window.clearTimeout(id);
  }, [currentUser.role]);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => { if (!toast) return; const id = window.setTimeout(() => setToast(""), 3000); return () => clearTimeout(id); }, [toast]);

  async function openCall(id: string) {
    try { setSelectedCall(await requestJson<CallDetailData>(`/api/v1/calls/${id}`)); }
    catch { setToast("جزئیات تماس دریافت نشد"); }
  }

  const pendingTasks = useMemo(() => tasks.filter((item) => item.status !== "done" && item.status !== "cancelled").length, [tasks]);
  const waitingMessages = useMemo(() => messages.filter((item) => item.status === "pending_approval").length, [messages]);
  const visibleNav = useMemo(() => nav.filter((item) => {
    if (currentUser.role === "مدیر") return true;
    if (currentUser.role === "سرپرست") return item.id !== "settings";
    return item.id !== "messages" && item.id !== "settings";
  }), [currentUser.role]);

  return <div className="live-shell">
    <aside className={`live-sidebar ${menuOpen ? "open" : ""}`}>
      <div className="live-brand"><span>م</span><div><strong>مکالمه‌بان</strong><small>دستیار هوشمند فروش</small></div></div>
      <div className="live-workspace"><small>فضای کاری</small><strong>{organization?.name ?? "در حال دریافت..."}</strong><span>{organization ? `پلن ${organization.plan}` : ""}</span></div>
      <nav>{visibleNav.map((item) => <button key={item.id} className={`${view === item.id && !selectedCall ? "active" : ""} ${item.id === "settings" ? "admin-entry" : ""}`.trim()} onClick={() => { setView(item.id); setSelectedCall(null); setMenuOpen(false); }}><i>{item.icon}</i>{item.label}{item.id === "settings" && <small>فقط مدیر</small>}{item.id === "tasks" && pendingTasks > 0 && <b>{fa(pendingTasks)}</b>}{item.id === "messages" && waitingMessages > 0 && <b>{fa(waitingMessages)}</b>}</button>)}</nav>
      <div className="live-account"><span>{currentUser.name.slice(0, 1)}</span><div><strong>{currentUser.name}</strong><small>{currentUser.email}</small></div><a href="/api/auth/logout" title="خروج">↪</a></div>
    </aside>
    {menuOpen && <button className="live-scrim" onClick={() => setMenuOpen(false)} aria-label="بستن منو" />}

    <main className="live-main">
      <header className="live-top"><button className="live-menu" onClick={() => setMenuOpen(true)}>☰</button><div><strong>{selectedCall ? "جزئیات تماس" : visibleNav.find((item) => item.id === view)?.label}</strong><small>اطلاعات واقعی فضای کاری شما</small></div><button className="live-theme" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>{theme === "light" ? "☾" : "☀"}</button></header>
      <div className="live-content">
        {loading && <StateCard title="در حال دریافت اطلاعات" description="چند لحظه صبر کنید..." />}
        {!loading && error && <StateCard title="اتصال برقرار نشد" description={error} action={<button onClick={() => void loadAll()}>تلاش دوباره</button>} tone="error" />}
        {!loading && !error && selectedCall && <CallDetails data={selectedCall} onBack={() => setSelectedCall(null)} onRefresh={() => void openCall(selectedCall.call.id)} />}
        {!loading && !error && !selectedCall && view === "overview" && <Overview overview={overview} calls={calls} pendingTasks={pendingTasks} onUpload={() => setUploadOpen(true)} onCalls={() => setView("calls")} onOpen={openCall} />}
        {!loading && !error && !selectedCall && view === "calls" && <Calls calls={calls} onUpload={() => setUploadOpen(true)} onOpen={openCall} />}
        {!loading && !error && !selectedCall && view === "tasks" && <Tasks items={tasks} onChanged={loadAll} onToast={setToast} />}
        {!loading && !error && !selectedCall && view === "messages" && <Messages items={messages} onChanged={loadAll} onToast={setToast} />}
        {!loading && !error && !selectedCall && view === "settings" && <AdminPanel key={`${organization?.id}-${organization?.name}`} organization={organization} onOrganizationChanged={loadAll} onToast={setToast} />}
      </div>
    </main>
    {uploadOpen && <UploadDialog currentUser={currentUser} onClose={() => setUploadOpen(false)} onDone={async () => { setUploadOpen(false); setToast("تماس وارد صف پردازش شد"); await loadAll(); setView("calls"); }} />}
    {toast && <div className="live-toast">{toast}</div>}
  </div>;
}

function StateCard({ title, description, action, tone }: { title: string; description: string; action?: React.ReactNode; tone?: string }) {
  return <section className={`live-state ${tone ?? ""}`}><span>{tone === "error" ? "!" : "…"}</span><h1>{title}</h1><p>{description}</p>{action}</section>;
}

function Overview({ overview, calls, pendingTasks, onUpload, onCalls, onOpen }: { overview: OverviewData; calls: CallItem[]; pendingTasks: number; onUpload: () => void; onCalls: () => void; onOpen: (id: string) => void }) {
  return <><div className="live-heading"><div><span>مرکز عملیات</span><h1>نمای واقعی عملکرد فروش</h1><p>اعداد این صفحه مستقیماً از تماس‌های فضای کاری شما محاسبه می‌شوند.</p></div><button onClick={onUpload}>＋ افزودن تماس</button></div>
    <section className="live-metrics"><Metric label="کل تماس‌ها" value={fa(overview.total_calls)} /><Metric label="تکمیل‌شده" value={fa(overview.completed_calls)} /><Metric label="امتیاز متوسط" value={overview.average_score == null ? "—" : fa(overview.average_score)} /><Metric label="نرخ تبدیل تأییدشده" value={overview.confirmed_conversion_rate == null ? "—" : `${fa(overview.confirmed_conversion_rate)}٪`} /><Metric label="پیگیری باز" value={fa(pendingTasks)} /></section>
    <section className="live-panel"><div className="live-panel-head"><div><h2>آخرین تماس‌ها</h2><p>آخرین فایل‌های ثبت‌شده در سامانه</p></div>{calls.length > 0 && <button onClick={onCalls}>مشاهده همه</button>}</div>{calls.length === 0 ? <Empty title="هنوز تماسی ثبت نشده است" description="اولین فایل صوتی را اضافه کنید تا پردازش آغاز شود." action={<button onClick={onUpload}>آپلود اولین تماس</button>} /> : <CallTable calls={calls.slice(0, 5)} onOpen={onOpen} />}</section></>;
}

function Metric({ label, value }: { label: string; value: string }) { return <article><span>{label}</span><strong>{value}</strong></article>; }

function Calls({ calls, onUpload, onOpen }: { calls: CallItem[]; onUpload: () => void; onOpen: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const filtered = calls.filter((call) => `${call.customer_name ?? ""} ${call.seller_name ?? ""} ${call.seller_email ?? ""} ${call.original_file_name}`.toLowerCase().includes(query.toLowerCase()));
  return <><div className="live-heading"><div><span>مدیریت مکالمات</span><h1>تماس‌ها</h1><p>فقط تماس‌های ثبت‌شده فضای کاری شما نمایش داده می‌شوند.</p></div><button onClick={onUpload}>＋ افزودن تماس</button></div><section className="live-panel"><div className="live-filter"><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="جست‌وجوی مشتری، فروشنده یا نام فایل" /></div>{calls.length === 0 ? <Empty title="فهرست تماس‌ها خالی است" description="یک فایل صوتی مجاز آپلود کنید." action={<button onClick={onUpload}>افزودن تماس</button>} /> : filtered.length === 0 ? <Empty title="نتیجه‌ای پیدا نشد" description="عبارت دیگری جست‌وجو کنید." /> : <CallTable calls={filtered} onOpen={onOpen} />}</section></>;
}

function CallTable({ calls, onOpen }: { calls: CallItem[]; onOpen: (id: string) => void }) { return <div className="live-table-wrap"><table className="live-table"><thead><tr><th>مشتری</th><th>فروشنده</th><th>فایل</th><th>وضعیت</th><th>نتیجه</th><th>امتیاز</th><th>تاریخ</th><th /></tr></thead><tbody>{calls.map((call) => <tr key={call.id}><td>{call.customer_name || "هنوز استخراج نشده"}</td><td>{call.seller_name || call.seller_email || "تعیین نشده"}</td><td>{call.original_file_name}</td><td><span className={`live-badge ${call.status}`}>{statusLabel[call.status] ?? call.status}</span></td><td>{outcomeLabel[call.outcome] ?? "نامشخص"}</td><td>{call.score == null ? "—" : fa(call.score)}</td><td>{formatDate(call.created_at)}</td><td><button onClick={() => onOpen(call.id)}>مشاهده</button></td></tr>)}</tbody></table></div>; }

function CallDetails({ data, onBack, onRefresh }: { data: CallDetailData; onBack: () => void; onRefresh: () => void }) {
  const analysis = data.analysis as { executive_summary?: string; overall_score?: number; strengths?: Array<{ title?: string; action?: string }>; improvements?: Array<{ title?: string; action?: string }> } | null | undefined;
  return <><button className="live-back" onClick={onBack}>→ بازگشت به تماس‌ها</button><div className="live-heading"><div><span>{data.call.id}</span><h1>{data.call.customer_name || data.call.original_file_name}</h1><p>{statusLabel[data.call.status] ?? data.call.status} · {formatDate(data.call.created_at)}</p></div><button className="secondary" onClick={onRefresh}>تازه‌سازی وضعیت</button></div>
    {data.audio_url && <section className="live-panel"><audio controls src={data.audio_url} className="live-audio" /></section>}
    {data.call.status === "failed" && <StateCard tone="error" title="پردازش ناموفق بود" description="از مدیر بخواهید تماس را دوباره پردازش کند." />}
    {!analysis && data.call.status !== "failed" && <StateCard title="تحلیل هنوز آماده نیست" description="این صفحه را کمی بعد تازه‌سازی کنید. متن و تحلیل پس از پایان پردازش ظاهر می‌شوند." action={<button onClick={onRefresh}>تازه‌سازی</button>} />}
    {analysis && <section className="live-analysis"><article className="live-panel"><span>امتیاز کل</span><strong>{fa(analysis.overall_score ?? data.call.score ?? 0)}</strong><p>{analysis.executive_summary || "خلاصه‌ای ثبت نشده است."}</p></article><article className="live-panel"><h2>نقاط قوت</h2>{analysis.strengths?.length ? analysis.strengths.map((item, index) => <div key={index}><strong>{item.title}</strong><p>{item.action}</p></div>) : <p>موردی ثبت نشده است.</p>}</article><article className="live-panel"><h2>قابل بهبود</h2>{analysis.improvements?.length ? analysis.improvements.map((item, index) => <div key={index}><strong>{item.title}</strong><p>{item.action}</p></div>) : <p>موردی ثبت نشده است.</p>}</article></section>}
    <section className="live-panel"><div className="live-panel-head"><div><h2>متن کامل مکالمه</h2><p>گوینده و زمان هر بخش قابل مشاهده است.</p></div></div>{data.segments?.length ? <div className="live-transcript">{data.segments.map((segment) => <article key={segment.id}><span>{segment.role === "seller" ? "فروشنده" : segment.role === "customer" ? "مشتری" : segment.speaker}<small>{segment.start == null ? "" : formatDuration(segment.start)}</small></span><p>{segment.content}</p></article>)}</div> : <Empty title="متن هنوز آماده نیست" description="پس از پایان رونویسی، متن کامل اینجا قرار می‌گیرد." />}</section></>;
}

function Tasks({ items, onChanged, onToast }: { items: TaskItem[]; onChanged: () => Promise<void>; onToast: (value: string) => void }) {
  const [title, setTitle] = useState("");
  async function add(event: FormEvent) { event.preventDefault(); if (!title.trim()) return; try { await requestJson("/api/v1/tasks", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ title: title.trim(), customer_name: "", priority: "normal" }) }); setTitle(""); await onChanged(); onToast("وظیفه ثبت شد"); } catch { onToast("ثبت وظیفه انجام نشد"); } }
  async function complete(id: string) { try { await requestJson(`/api/v1/tasks/${id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ status: "done" }) }); await onChanged(); onToast("وظیفه انجام‌شده ثبت شد"); } catch { onToast("تغییر وضعیت انجام نشد"); } }
  return <><div className="live-heading"><div><span>مرکز اقدام</span><h1>پیگیری‌ها</h1><p>وظایف واقعی تیم فروش را ثبت و تکمیل کنید.</p></div></div><form className="live-inline-form" onSubmit={add}><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="عنوان وظیفه جدید" maxLength={180} /><button>ثبت وظیفه</button></form><section className="live-panel">{items.length === 0 ? <Empty title="وظیفه‌ای وجود ندارد" description="برای شروع، یک وظیفه جدید ثبت کنید." /> : <div className="live-list">{items.map((item) => <article key={item.id}><div><strong>{item.title}</strong><p>{item.customer || "بدون مشتری"} · اولویت {item.priority} · {formatDate(item.due_at)}</p></div><span className={`live-badge ${item.status}`}>{statusLabel[item.status] ?? item.status}</span>{item.status !== "done" && <button onClick={() => void complete(item.id)}>انجام شد</button>}</article>)}</div>}</section></>;
}

function Messages({ items, onChanged, onToast }: { items: MessageItem[]; onChanged: () => Promise<void>; onToast: (value: string) => void }) {
  async function approve(id: string) { try { await requestJson(`/api/v1/messages/${id}/approve`, { method: "POST" }); await onChanged(); onToast("پیام تأیید شد"); } catch { onToast("تأیید پیام انجام نشد"); } }
  return <><div className="live-heading"><div><span>ارتباط با مشتری</span><h1>پیش‌نویس پیام‌ها</h1><p>فقط پیام‌های ساخته‌شده از تحلیل‌های واقعی نمایش داده می‌شوند.</p></div></div><section className="live-panel">{items.length === 0 ? <Empty title="پیامی وجود ندارد" description="پس از تحلیل تماس و پیشنهاد پیگیری، پیش‌نویس پیام اینجا ظاهر می‌شود." /> : <div className="live-message-list">{items.map((item) => <article key={item.id}><header><span>{channelLabel[item.channel] ?? item.channel}</span><b className={`live-badge ${item.status}`}>{statusLabel[item.status] ?? item.status}</b></header>{item.subject && <h3>{item.subject}</h3>}<p>{item.content}</p>{item.status === "pending_approval" && <button onClick={() => void approve(item.id)}>تأیید پیام</button>}</article>)}</div>}</section></>;
}

function UploadDialog({ currentUser, onClose, onDone }: { currentUser: CurrentUser; onClose: () => void; onDone: () => Promise<void> }) {
  const input = useRef<HTMLInputElement>(null); const [file, setFile] = useState<File | null>(null); const [consent, setConsent] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function submit(event: FormEvent) { event.preventDefault(); if (!file || !consent) return; setBusy(true); setError(""); const body = new FormData(); body.append("audio", file); body.append("seller", currentUser.email); body.append("consent", "true"); try { await requestJson("/api/v1/calls", { method: "POST", body }); await onDone(); } catch (cause) { setError(cause instanceof Error ? cause.message : "آپلود انجام نشد"); setBusy(false); } }
  return <div className="live-modal"><button className="live-modal-bg" onClick={onClose} aria-label="بستن" /><form onSubmit={submit}><header><div><span>تماس جدید</span><h2>آپلود فایل صوتی</h2></div><button type="button" onClick={onClose}>×</button></header><input ref={input} type="file" accept="audio/*" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} /><button type="button" className="live-drop" onClick={() => input.current?.click()}><strong>{file ? file.name : "انتخاب فایل صوتی"}</strong><small>{file ? `${fa((file.size / 1024 / 1024).toFixed(1))} مگابایت` : "MP3، WAV، M4A یا OGG تا ۵۰۰ مگابایت"}</small></button><label className="live-consent"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /><span>تأیید می‌کنم رضایت لازم برای ضبط و پردازش این تماس دریافت شده است.</span></label>{error && <p className="live-form-error">{error}</p>}<footer><button type="button" className="secondary" onClick={onClose}>انصراف</button><button disabled={!file || !consent || busy}>{busy ? "در حال ارسال..." : "شروع پردازش"}</button></footer></form></div>;
}

function Empty({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) { return <div className="live-empty"><span>＋</span><h3>{title}</h3><p>{description}</p>{action}</div>; }

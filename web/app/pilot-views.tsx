"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

export type CallItem = {
  id: string;
  customer_name?: string | null;
  company_name?: string | null;
  company?: string | null;
  phone_number?: string | null;
  phone?: string | null;
  city?: string | null;
  province?: string | null;
  seller_email?: string | null;
  seller_name?: string | null;
  product_name?: string | null;
  product?: string | null;
  product_category?: string | null;
  original_file_name: string;
  source_path?: string | null;
  source?: string | null;
  status: string;
  outcome: string;
  direction?: string | null;
  duration_seconds?: number | null;
  score?: number | null;
  sentiment?: string | null;
  sales_stage?: string | null;
  lead_temperature?: string | null;
  followup_required?: boolean | number | null;
  followup_at?: string | null;
  followup_due_at?: string | null;
  has_manual_correction?: boolean | number | null;
  manually_corrected?: boolean | number | null;
  error_message?: string | null;
  error_code?: string | null;
  created_at: string;
};

type PaginatedCalls = {
  items?: CallItem[];
  calls?: CallItem[];
  total?: number;
  page?: number;
  page_size?: number;
  pages?: number;
  capabilities?: { excel_export?: boolean };
};

export type TaskItem = {
  id: string;
  call_id?: string | null;
  title: string;
  customer?: string | null;
  company?: string | null;
  assigned_agent?: string | null;
  priority: string;
  status: string;
  due_at?: string | null;
  reason?: string | null;
  completion_note?: string | null;
  completed_at?: string | null;
  creation_method?: string | null;
};

type Segment = {
  id: string;
  speaker?: string;
  speaker_id?: string;
  role?: string;
  speaker_role?: string;
  speaker_role_confidence?: number | null;
  role_confidence?: number | null;
  start?: number | null;
  start_time?: number | null;
  end?: number | null;
  end_time?: number | null;
  text?: string;
  content?: string;
  normalized_text?: string | null;
  is_manually_corrected?: boolean | number;
  manually_corrected?: boolean | number;
};

type Evidence = {
  id?: string;
  field_name?: string;
  field?: string;
  extracted_value?: unknown;
  value?: unknown;
  confidence?: number | null;
  source_segment_ids?: string[];
  exact_quote?: string | null;
  quote?: string | null;
  start_seconds?: number | null;
  start_time?: number | null;
  end_seconds?: number | null;
  end_time?: number | null;
  validation_status?: string;
  supported?: boolean;
  timestamp_seconds?: number | null;
};

type ProcessingEvent = {
  id?: string;
  stage?: string;
  status?: string;
  safe_message?: string | null;
  error_type?: string | null;
  retry_count?: number | null;
  worker?: string | null;
  correlation_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string | null;
};

type DetailCapabilities = {
  pdf_export?: boolean;
  excel_export?: boolean;
  reanalysis?: boolean;
  retry?: boolean;
  role_correction?: boolean;
  transcript_correction?: boolean;
  audio_download?: boolean;
};

type CallDetailData = {
  call: CallItem & Record<string, unknown>;
  analysis?: Record<string, unknown> | null;
  raw_analysis?: Record<string, unknown> | null;
  segments?: Segment[];
  transcript_segments?: Segment[];
  processing_timeline?: ProcessingEvent[];
  timeline?: ProcessingEvent[];
  processing?: { retry_count?: number; next_retry_at?: string | null; last_successful_stage?: string | null; events?: Array<ProcessingEvent & { from_state?: string; to_state?: string; attempt?: number }>; errors?: Array<ProcessingEvent & { code?: string; category?: string; transient?: boolean; attempt?: number; message?: string; resolved_at?: string | null }> };
  extraction?: Record<string, unknown> | null;
  evidence?: Evidence[];
  followups?: TaskItem[];
  audio_url?: string | null;
  capabilities?: DetailCapabilities;
};

const statusLabel: Record<string, string> = {
  discovered: "کشف‌شده", waiting_for_file: "منتظر تکمیل فایل", received: "دریافت‌شده", uploaded: "آپلودشده",
  queued: "در صف", preprocessing: "پیش‌پردازش", diarizing: "تفکیک گوینده", transcribing: "رونویسی",
  assigning_roles: "تشخیص نقش", analyzing: "تحلیل", validating: "اعتبارسنجی", creating_followups: "ساخت پیگیری",
  review_needed: "نیازمند بازبینی", completed: "تکمیل‌شده", retry_scheduled: "Retry زمان‌بندی‌شده",
  failed: "ناموفق", quarantined: "قرنطینه", ignored: "نادیده گرفته‌شده",
  open: "باز", in_progress: "در حال انجام", needs_scheduling: "بدون زمان مشخص", done: "انجام‌شده", cancelled: "لغوشده",
};
const outcomeLabel: Record<string, string> = { won: "فروش", lost: "از دست‌رفته", follow_up: "نیازمند پیگیری", unknown: "نامشخص" };
const roleLabel: Record<string, string> = { agent: "فروشنده", seller: "فروشنده", customer: "مشتری", other: "سایر", unknown: "نامشخص" };
const validationLabel: Record<string, string> = { verified: "تأییدشده", supported: "دارای شاهد", inferred: "استنباط‌شده", unsupported: "بدون شاهد", manually_confirmed: "تأیید دستی" };

export function fa(value: string | number) {
  return String(value).replace(/\d/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
}

export function formatDate(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}

export function formatDuration(value?: number | null) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const seconds = Math.max(0, Math.round(Number(value)));
  return fa(Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0"));
}

export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const type = response.headers.get("content-type") ?? "";
  const result = type.includes("json") ? await response.json().catch(() => ({})) : {};
  if (!response.ok) {
    const detail = result as { detail?: string; error?: string };
    throw new Error(detail.detail ?? detail.error ?? "request_failed");
  }
  return result as T;
}

function updateUrl(changes: Record<string, string | null>) {
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(changes)) {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  }
  window.history.replaceState({}, "", url.pathname + "?" + url.searchParams.toString());
}

const emptyFilters: Record<string, string> = {
  q: "", date_from: "", date_to: "", seller: "", customer: "", company: "", phone: "", city: "", province: "",
  product: "", product_category: "", outcome: "", sales_stage: "", lead_temperature: "", followup_required: "",
  followup_overdue: "", min_score: "", max_score: "", sentiment: "", risk_flag: "", status: "", direction: "",
  min_duration: "", max_duration: "", source_filename: "", has_error: "", manually_corrected: "", sort: "created_at", order: "desc",
};

function filtersFromLocation() {
  if (typeof window === "undefined") return emptyFilters;
  const params = new URLSearchParams(window.location.search);
  const result = { ...emptyFilters };
  for (const key of Object.keys(result)) result[key] = params.get(key) ?? result[key];
  return result;
}

function filterQuery(filters: Record<string, string>, page: number) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  params.set("page", String(page));
  params.set("page_size", "25");
  return params;
}

export function CallsExplorer({ onUpload, onOpen, canUpload = true, canExport = false }: { onUpload: () => void; onOpen: (id: string) => void; canUpload?: boolean; canExport?: boolean }) {
  const [draft, setDraft] = useState<Record<string, string>>(filtersFromLocation);
  const [applied, setApplied] = useState<Record<string, string>>(filtersFromLocation);
  const [page, setPage] = useState(() => typeof window === "undefined" ? 1 : Math.max(1, Number(new URLSearchParams(window.location.search).get("page")) || 1));
  const [data, setData] = useState<PaginatedCalls>({ items: [], total: 0, page: 1, pages: 1 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const query = useMemo(() => filterQuery(applied, page).toString(), [applied, page]);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setData(await requestJson<PaginatedCalls>("/api/v1/calls?" + query)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "دریافت تماس‌ها ناموفق بود"); }
    finally { setLoading(false); }
  }, [query]);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);

  function set(key: string, value: string) { setDraft((current) => ({ ...current, [key]: value })); }
  function apply(event: FormEvent) {
    event.preventDefault(); setApplied({ ...draft }); setPage(1);
    const changes: Record<string, string | null> = { view: "calls", page: "1" };
    for (const key of Object.keys(emptyFilters)) changes[key] = draft[key] || null;
    updateUrl(changes);
  }
  function reset() {
    setDraft({ ...emptyFilters }); setApplied({ ...emptyFilters }); setPage(1);
    const changes: Record<string, string | null> = { view: "calls", page: null };
    for (const key of Object.keys(emptyFilters)) changes[key] = null;
    updateUrl(changes);
  }
  function move(next: number) { setPage(next); updateUrl({ page: String(next) }); }
  const items = data.items ?? data.calls ?? [];
  const excelEnabled = canExport && data.capabilities?.excel_export !== false;

  return <>
    <div className="live-heading"><div><span>مدیریت مکالمات</span><h1>تماس‌ها</h1><p>فیلتر، مرتب‌سازی و صفحه‌بندی مستقیماً در سرور اجرا می‌شود.</p></div><div className="heading-actions">
      {canExport ? (excelEnabled ? <a className="pilot-button secondary" href={"/api/v1/exports/calls.xlsx?" + query}>خروجی Excel</a> : <button className="secondary" disabled title="در حالت محلی به سرویس گزارش‌ساز نیاز دارد">Excel غیرفعال</button>) : <button className="secondary" disabled title="خروجی گروهی فقط برای مدیر، مدیر فروش و سرپرست مجاز است">Excel فقط مدیران</button>}
      {canUpload && <button onClick={onUpload}>＋ افزودن تماس</button>}
    </div></div>
    {canExport && !excelEnabled && <CapabilityNotice>خروجی Excel در حالت D1 محلی ساخته نمی‌شود. با اتصال Backend، همین دکمه خروجی چندبرگی و منطبق با فیلترهای فعال را دریافت می‌کند.</CapabilityNotice>}
    <form className="pilot-filter-panel" onSubmit={apply}>
      <div className="pilot-filter-primary">
        <Field label="جست‌وجو"><input value={draft.q} onChange={(event) => set("q", event.target.value)} placeholder="نام، شماره، محصول یا فایل" /></Field>
        <Field label="از تاریخ"><input type="date" value={draft.date_from} onChange={(event) => set("date_from", event.target.value)} /></Field>
        <Field label="تا تاریخ"><input type="date" value={draft.date_to} onChange={(event) => set("date_to", event.target.value)} /></Field>
        <Field label="فروشنده"><input value={draft.seller} onChange={(event) => set("seller", event.target.value)} /></Field>
        <Field label="نتیجه"><select value={draft.outcome} onChange={(event) => set("outcome", event.target.value)}><option value="">همه</option><option value="won">فروش</option><option value="lost">از دست‌رفته</option><option value="follow_up">پیگیری</option><option value="unknown">نامشخص</option></select></Field>
        <Field label="وضعیت پردازش"><select value={draft.status} onChange={(event) => set("status", event.target.value)}><option value="">همه</option>{Object.entries(statusLabel).slice(0, 15).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
      </div>
      {advanced && <div className="pilot-filter-grid">
        <Field label="مشتری"><input value={draft.customer} onChange={(event) => set("customer", event.target.value)} /></Field>
        <Field label="شرکت"><input value={draft.company} onChange={(event) => set("company", event.target.value)} /></Field>
        <Field label="شماره تماس"><input dir="ltr" value={draft.phone} onChange={(event) => set("phone", event.target.value)} /></Field>
        <Field label="شهر"><input value={draft.city} onChange={(event) => set("city", event.target.value)} /></Field>
        <Field label="استان"><input value={draft.province} onChange={(event) => set("province", event.target.value)} /></Field>
        <Field label="محصول"><input value={draft.product} onChange={(event) => set("product", event.target.value)} /></Field>
        <Field label="دسته محصول"><input value={draft.product_category} onChange={(event) => set("product_category", event.target.value)} /></Field>
        <Field label="مرحله فروش"><input value={draft.sales_stage} onChange={(event) => set("sales_stage", event.target.value)} /></Field>
        <Field label="دمای سرنخ"><select value={draft.lead_temperature} onChange={(event) => set("lead_temperature", event.target.value)}><option value="">همه</option><option value="hot">داغ</option><option value="warm">گرم</option><option value="cold">سرد</option></select></Field>
        <Field label="پیگیری لازم"><select value={draft.followup_required} onChange={(event) => set("followup_required", event.target.value)}><option value="">همه</option><option value="true">بله</option><option value="false">خیر</option></select></Field>
        <Field label="پیگیری عقب‌افتاده"><select value={draft.followup_overdue} onChange={(event) => set("followup_overdue", event.target.value)}><option value="">همه</option><option value="true">فقط عقب‌افتاده</option></select></Field>
        <Field label="حس مکالمه"><input value={draft.sentiment} onChange={(event) => set("sentiment", event.target.value)} /></Field>
        <Field label="پرچم ریسک"><select value={draft.risk_flag} onChange={(event) => set("risk_flag", event.target.value)}><option value="">همه</option><option value="true">دارای ریسک</option><option value="false">بدون ریسک</option></select></Field>
        <Field label="حداقل امتیاز"><input type="number" min="0" max="100" value={draft.min_score} onChange={(event) => set("min_score", event.target.value)} /></Field>
        <Field label="حداکثر امتیاز"><input type="number" min="0" max="100" value={draft.max_score} onChange={(event) => set("max_score", event.target.value)} /></Field>
        <Field label="جهت تماس"><select value={draft.direction} onChange={(event) => set("direction", event.target.value)}><option value="">همه</option><option value="inbound">ورودی</option><option value="outbound">خروجی</option></select></Field>
        <Field label="حداقل مدت (ثانیه)"><input type="number" min="0" value={draft.min_duration} onChange={(event) => set("min_duration", event.target.value)} /></Field>
        <Field label="حداکثر مدت (ثانیه)"><input type="number" min="0" value={draft.max_duration} onChange={(event) => set("max_duration", event.target.value)} /></Field>
        <Field label="نام فایل"><input value={draft.source_filename} onChange={(event) => set("source_filename", event.target.value)} /></Field>
        <Field label="خطا"><select value={draft.has_error} onChange={(event) => set("has_error", event.target.value)}><option value="">همه</option><option value="true">دارای خطا</option><option value="false">بدون خطا</option></select></Field>
        <Field label="اصلاح دستی"><select value={draft.manually_corrected} onChange={(event) => set("manually_corrected", event.target.value)}><option value="">همه</option><option value="true">اصلاح‌شده</option><option value="false">بدون اصلاح</option></select></Field>
        <Field label="مرتب‌سازی"><select value={draft.sort} onChange={(event) => set("sort", event.target.value)}><option value="created_at">تاریخ</option><option value="score">امتیاز</option><option value="duration">مدت</option><option value="customer">مشتری</option><option value="seller">فروشنده</option><option value="outcome">نتیجه</option></select></Field>
        <Field label="ترتیب"><select value={draft.order} onChange={(event) => set("order", event.target.value)}><option value="desc">نزولی</option><option value="asc">صعودی</option></select></Field>
      </div>}
      <div className="pilot-filter-actions"><button type="button" className="secondary" onClick={() => setAdvanced(!advanced)}>{advanced ? "فیلترهای کمتر" : "فیلترهای بیشتر"}</button><button type="button" className="secondary" onClick={reset}>پاک‌کردن فیلترها</button><button>اعمال فیلتر</button></div>
    </form>
    <section className="live-panel pilot-results">
      <div className="live-panel-head"><div><h2>نتایج</h2><p>{fa(data.total ?? items.length)} تماس مطابق فیلترهای فعال</p></div></div>
      {loading ? <LoadingRows /> : error ? <InlineError message={error} onRetry={load} /> : items.length === 0 ? <Empty title="تماسی پیدا نشد" description="فیلترها را پاک کنید یا بازه دیگری انتخاب کنید." /> : <CallTable calls={items} onOpen={onOpen} />}
      {!loading && !error && <Pagination page={data.page ?? page} pages={data.pages ?? 1} onMove={move} />}
    </section>
  </>;
}

export function CallTable({ calls, onOpen }: { calls: CallItem[]; onOpen: (id: string) => void }) {
  return <div className="live-table-wrap"><table className="live-table"><thead><tr><th>مشتری و شرکت</th><th>فروشنده</th><th>محصول</th><th>وضعیت</th><th>نتیجه</th><th>امتیاز</th><th>مدت</th><th>تاریخ</th><th /></tr></thead><tbody>{calls.map((call) => <tr key={call.id}>
    <td><strong>{call.customer_name || "استخراج نشده"}</strong><small>{call.company_name || call.company || call.phone_number || call.phone || "—"}</small></td>
    <td>{call.seller_name || call.seller_email || "تعیین نشده"}</td><td>{call.product_name || call.product || "—"}</td>
    <td><span className={"live-badge " + call.status}>{statusLabel[call.status] ?? call.status}</span>{(call.error_message || call.error_code) && <small className="row-error">دارای خطا</small>}</td>
    <td>{outcomeLabel[call.outcome] ?? call.outcome}</td><td>{call.score == null ? "—" : fa(call.score)}</td><td>{formatDuration(call.duration_seconds)}</td><td>{formatDate(call.created_at)}</td>
    <td><button onClick={() => onOpen(call.id)}>جزئیات</button></td></tr>)}</tbody></table></div>;
}

export function FollowupsView({ onOpenCall, onToast, onCountChanged }: { onOpenCall: (id: string) => void; onToast: (value: string) => void; onCountChanged: () => Promise<void> }) {
  const initialBucket = typeof window === "undefined" ? "today" : new URLSearchParams(window.location.search).get("task_bucket") ?? "today";
  const [bucket, setBucket] = useState(initialBucket);
  const [seller, setSeller] = useState("");
  const [customer, setCustomer] = useState("");
  const [items, setItems] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [compatibilityFallback, setCompatibilityFallback] = useState(false);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    const params = new URLSearchParams({ bucket });
    if (seller) params.set("seller", seller);
    if (customer) params.set("customer", customer);
    try { setItems((await requestJson<{ items: TaskItem[] }>("/api/v1/tasks?" + params)).items ?? []); setCompatibilityFallback(false); }
    catch (cause) {
      const legacyBucket: Record<string, string> = { today: "all", unscheduled: "needs_attention", done: "completed", cancelled: "all" };
      if (!legacyBucket[bucket]) setError(cause instanceof Error ? cause.message : "دریافت پیگیری‌ها ناموفق بود");
      else try {
        params.set("bucket", legacyBucket[bucket]); const rows = (await requestJson<{ items: TaskItem[] }>("/api/v1/tasks?" + params)).items ?? [];
        const now = new Date(); const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()); const end = new Date(start); end.setDate(end.getDate() + 1);
        const narrowed = bucket === "today" ? rows.filter((item) => item.due_at && new Date(item.due_at) >= start && new Date(item.due_at) < end && !["done","cancelled"].includes(item.status)) : bucket === "unscheduled" ? rows.filter((item) => item.status === "needs_scheduling" || (!item.due_at && !["done","cancelled"].includes(item.status))) : bucket === "done" ? rows.filter((item) => item.status === "done") : rows.filter((item) => item.status === "cancelled");
        setItems(narrowed); setCompatibilityFallback(true);
      } catch (fallbackCause) { setError(fallbackCause instanceof Error ? fallbackCause.message : "دریافت پیگیری‌ها ناموفق بود"); }
    }
    finally { setLoading(false); }
  }, [bucket, seller, customer]);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);

  async function changeStatus(item: TaskItem, status: string) {
    const note = status === "done" ? window.prompt("یادداشت نتیجه پیگیری را وارد کنید (اختیاری):", item.completion_note ?? "") : null;
    if (status === "done" && note === null) return;
    try {
      await requestJson("/api/v1/tasks/" + item.id, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ status, completion_note: note }) });
      await load(); await onCountChanged(); onToast(status === "done" ? "پیگیری انجام‌شده ثبت شد" : "وضعیت پیگیری تغییر کرد");
    } catch (cause) { onToast(cause instanceof Error ? cause.message : "تغییر وضعیت انجام نشد"); }
  }
  function selectBucket(value: string) { setBucket(value); updateUrl({ view: "tasks", task_bucket: value }); }
  const buckets = [["today","امروز"],["overdue","عقب‌افتاده"],["unscheduled","بدون زمان"],["done","انجام‌شده"],["cancelled","لغوشده"],["all","همه"]];
  return <>
    <div className="live-heading"><div><span>مرکز اقدام</span><h1>پیگیری‌ها</h1><p>پیگیری‌های امروز، عقب‌افتاده و بدون زمان از داده واقعی سرور جدا شده‌اند.</p></div></div>
    <div className="pilot-buckets">{buckets.map(([value, label]) => <button key={value} className={bucket === value ? "active" : ""} onClick={() => selectBucket(value)}>{label}</button>)}</div>
    {compatibilityFallback && <CapabilityNotice>Backend قدیمی این دسته را مستقیم پشتیبانی نمی‌کند؛ نتیجه سازگار از حداکثر ۱۰۰ رکورد دریافت و در رابط محدود شده است. برای پایلوت پرترافیک، API جدید را اجرا کنید.</CapabilityNotice>}
    <div className="pilot-task-filters"><input value={seller} onChange={(event) => setSeller(event.target.value)} placeholder="فیلتر کارشناس" /><input value={customer} onChange={(event) => setCustomer(event.target.value)} placeholder="فیلتر مشتری" /></div>
    <section className="live-panel">{loading ? <LoadingRows /> : error ? <InlineError message={error} onRetry={load} /> : items.length === 0 ? <Empty title="پیگیری‌ای در این بخش نیست" description="با تغییر دسته یا فیلتر، موارد دیگر را ببینید." /> : <div className="pilot-task-list">{items.map((item) => <article key={item.id} className={bucket === "overdue" ? "overdue" : ""}>
      <div><span className={"live-badge " + item.status}>{statusLabel[item.status] ?? item.status}</span><h3>{item.title}</h3><p>{item.customer || "مشتری نامشخص"}{item.company ? " · " + item.company : ""}</p></div>
      <dl><div><dt>مسئول</dt><dd>{item.assigned_agent || "تعیین نشده"}</dd></div><div><dt>موعد</dt><dd>{item.due_at ? formatDate(item.due_at) : "نیازمند زمان‌بندی"}</dd></div><div><dt>دلیل</dt><dd>{item.reason || "ثبت نشده"}</dd></div><div><dt>منبع</dt><dd>{item.creation_method === "ai" ? "پیشنهاد هوش مصنوعی" : "دستی/سیستمی"}</dd></div></dl>
      <footer>{item.call_id && <button className="secondary" onClick={() => onOpenCall(String(item.call_id))}>مشاهده تماس</button>}{item.status !== "done" && item.status !== "cancelled" && <><button onClick={() => void changeStatus(item, "done")}>انجام شد</button><button className="danger-link" onClick={() => void changeStatus(item, "cancelled")}>لغو</button></>}</footer>
    </article>)}</div>}</section>
  </>;
}

export function CallDetailView({ callId, isAdmin, readOnly = false, canReprocess = false, onBack, onToast }: { callId: string; isAdmin: boolean; readOnly?: boolean; canReprocess?: boolean; onBack: () => void; onToast: (value: string) => void }) {
  const [data, setData] = useState<CallDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setData(await requestJson<CallDetailData>("/api/v1/calls/" + encodeURIComponent(callId))); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "جزئیات تماس دریافت نشد"); }
    finally { setLoading(false); }
  }, [callId]);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);

  async function action(name: "reanalyze" | "retry") {
    const label = name === "reanalyze" ? "تحلیل مجدد" : "تلاش مجدد";
    if (!window.confirm(label + " برای این تماس انجام شود؟")) return;
    try { await requestJson("/api/v1/calls/" + encodeURIComponent(callId) + "/reprocess", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ mode: name === "reanalyze" ? "reanalyze" : "resume" }) }); onToast(label + " در صف قرار گرفت"); await load(); }
    catch (cause) { onToast(cause instanceof Error ? cause.message : "عملیات انجام نشد"); }
  }
  function seek(seconds?: number | null) {
    const audio = document.getElementById("pilot-call-audio") as HTMLAudioElement | null;
    if (!audio || seconds == null) return;
    audio.currentTime = Math.max(0, Number(seconds)); void audio.play();
  }
  if (loading) return <><button className="live-back" onClick={onBack}>→ بازگشت</button><LoadingDetail /></>;
  if (error || !data) return <><button className="live-back" onClick={onBack}>→ بازگشت</button><InlineError message={error || "تماس پیدا نشد"} onRetry={load} /></>;
  const call = data.call;
  const analysis = asRecord(data.analysis);
  const segments = data.segments ?? data.transcript_segments ?? [];
  const processingEvents = data.processing?.events?.map((item) => ({ ...item, status: item.status ?? item.to_state, retry_count: item.retry_count ?? item.attempt })) ?? [];
  const processingErrors = data.processing?.errors?.map((item) => ({ ...item, status: "failed", error_type: item.error_type ?? item.category ?? item.code, safe_message: item.safe_message ?? item.message, retry_count: item.retry_count ?? item.attempt })) ?? [];
  const timeline = data.processing_timeline ?? data.timeline ?? [...processingEvents, ...processingErrors];
  const normalizedEvidence = (data.evidence ?? []).map((item) => ({ ...item, validation_status: item.validation_status ?? (item.supported === true ? "supported" : item.supported === false ? "unsupported" : undefined), start_seconds: item.start_seconds ?? item.timestamp_seconds }));
  const evidence = normalizedEvidence.filter((item) => item.validation_status !== "unsupported");
  const unsupportedCount = normalizedEvidence.length - evidence.length;
  const capabilities = data.capabilities ?? {};
  const pdfEnabled = capabilities.pdf_export !== false;
  const callExcelEnabled = capabilities.excel_export !== false;
  const reanalysisEnabled = capabilities.reanalysis !== false;
  const retryEnabled = capabilities.retry !== false;
  const extraction = asRecord(data.extraction);
  const customerAnalysis = nested(analysis, ["customer_information", "customer", "customer_info"]);
  const salesAnalysis = nested(analysis, ["sales_information", "sales", "deal"]);
  const followupAnalysis = nested(analysis, ["follow_up", "followup", "next_action"]);
  const customer: Record<string, unknown> = { ...customerAnalysis, customer_name: extraction.customer_name ?? customerAnalysis.customer_name ?? customerAnalysis.name, company_name: extraction.company ?? customerAnalysis.company_name ?? customerAnalysis.company, phone_number: extraction.phone ?? customerAnalysis.phone_number ?? customerAnalysis.phone, city: extraction.city ?? customerAnalysis.city, province: extraction.province ?? customerAnalysis.province };
  const sales: Record<string, unknown> = { ...customerAnalysis, ...salesAnalysis, product_name: extraction.product ?? salesAnalysis.product_name ?? customerAnalysis.product, product_category: extraction.product_category ?? salesAnalysis.product_category ?? customerAnalysis.product_category, exact_amount: extraction.amount ?? salesAnalysis.exact_amount ?? customerAnalysis.exact_amount ?? customerAnalysis.amount, sales_stage: extraction.sales_stage ?? salesAnalysis.sales_stage ?? customerAnalysis.sales_stage, lead_temperature: extraction.lead_temperature ?? salesAnalysis.lead_temperature ?? customerAnalysis.lead_temperature, budget_min: extraction.budget ?? salesAnalysis.budget_min ?? customerAnalysis.budget_min ?? customerAnalysis.budget };
  const followup: Record<string, unknown> = { ...followupAnalysis, followup_required: extraction.followup_required ?? followupAnalysis.followup_required, followup_date: extraction.followup_due_at ?? followupAnalysis.followup_date ?? customerAnalysis.followup_at, promised_action: extraction.promise ?? followupAnalysis.promised_action ?? followupAnalysis.title, followup_reason: followupAnalysis.followup_reason ?? followupAnalysis.rationale };
  const callAnalysis = nested(analysis, ["call_analysis", "analysis"]);
  const summary = firstString(callAnalysis.call_summary, analysis.executive_summary, analysis.summary, callAnalysis.executive_summary);
  const score = firstNumber(callAnalysis.quality_score, analysis.overall_score, call.score);
  const strengths = recordList(callAnalysis.agent_strengths ?? analysis.strengths);
  const weaknesses = recordList(callAnalysis.agent_weaknesses ?? analysis.improvements ?? analysis.weaknesses);
  const coaching = recordList(callAnalysis.coaching_recommendations ?? analysis.coaching_recommendations);
  const objections = recordList(callAnalysis.objections ?? analysis.objections);
  const commitments = recordList(callAnalysis.commitments ?? analysis.commitments ?? customerAnalysis.commitments);
  const missed = recordList(callAnalysis.missed_opportunities ?? analysis.missed_opportunities);
  const scoreBreakdown = scoreItemsRecord(callAnalysis.score_breakdown ?? analysis.score_breakdown ?? analysis.score_items);
  const metrics = recordList(callAnalysis.metrics ?? analysis.metrics);

  return <>
    <button className="live-back" onClick={onBack}>→ بازگشت به تماس‌ها</button>
    <div className="live-heading"><div><span>{call.id}</span><h1>{call.customer_name || call.original_file_name}</h1><p>{statusLabel[call.status] ?? call.status} · {formatDate(call.created_at)}</p></div><div className="heading-actions">
      {pdfEnabled ? <a className="pilot-button secondary" href={"/api/v1/calls/" + encodeURIComponent(callId) + "/export.pdf"} target="_blank">گزارش PDF</a> : <button className="secondary" disabled title="به سرویس گزارش‌ساز نیاز دارد">PDF غیرفعال</button>}
      {callExcelEnabled ? <a className="pilot-button secondary" href={"/api/v1/calls/" + encodeURIComponent(callId) + "/export.xlsx"}>گزارش Excel</a> : <button className="secondary" disabled title="به سرویس گزارش‌ساز نیاز دارد">Excel غیرفعال</button>}
      <button className="secondary" onClick={() => void load()}>تازه‌سازی</button>
      {!readOnly && canReprocess && <button disabled={!reanalysisEnabled} title={reanalysisEnabled ? "" : "در حالت محلی Worker متصل نیست"} onClick={() => void action("reanalyze")}>تحلیل مجدد</button>}
      {!readOnly && canReprocess && call.status === "failed" && <button disabled={!retryEnabled} onClick={() => void action("retry")}>Retry</button>}
    </div></div>
    {(!pdfEnabled || !callExcelEnabled || !reanalysisEnabled) && <CapabilityNotice>این صفحه در حالت محلی فقط اصلاح متن و نقش‌ها را ذخیره می‌کند. PDF، Excel، Retry و تحلیل مجدد با اتصال Backend/Worker فعال می‌شوند.</CapabilityNotice>}
    <AudioPlayer source={data.audio_url} duration={call.duration_seconds} downloadable={capabilities.audio_download !== false} />
    <section className="pilot-detail-grid">
      <DetailCard title="اطلاعات تماس"><DataGrid values={[
        ["فروشنده", call.seller_name ?? call.seller_email],["تاریخ", formatDate(call.created_at)],["جهت", call.direction === "inbound" ? "ورودی" : call.direction === "outbound" ? "خروجی" : call.direction],
        ["مدت", formatDuration(call.duration_seconds)],["منبع", call.source],["نام فایل", call.original_file_name],["مسیر منبع", call.source_path],
      ]} /></DetailCard>
      <DetailCard title="خلاصه مدیریتی"><div className="score-summary"><strong>{score == null ? "—" : fa(score)}</strong><span>امتیاز کل از ۱۰۰</span></div><p className="detail-copy">{summary || "خلاصه‌ای تأییدشده ثبت نشده است."}</p></DetailCard>
    </section>
    <ProcessingTimeline items={timeline} currentStatus={call.status} />
    <section className="pilot-detail-grid three">
      <DetailCard title="اطلاعات مشتری"><DataGrid values={[
        ["نام", supportedValue(call.customer_name ?? customer.customer_name, "customer_name", normalizedEvidence)],
        ["شرکت", supportedValue(call.company_name ?? call.company ?? customer.company_name, "company_name", normalizedEvidence)],
        ["شماره", supportedValue(call.phone_number ?? call.phone ?? customer.phone_number, "phone_number", normalizedEvidence)],
        ["شماره جایگزین", supportedValue(customer.alternate_phone, "alternate_phone", normalizedEvidence)],
        ["شهر", supportedValue(call.city ?? customer.city, "city", normalizedEvidence)],
        ["استان", supportedValue(call.province ?? customer.province, "province", normalizedEvidence)],
        ["نوع مشتری", supportedValue(customer.customer_type, "customer_type", normalizedEvidence)],
      ]} /></DetailCard>
      <DetailCard title="اطلاعات فروش"><DataGrid values={[
        ["محصول", supportedValue(call.product_name ?? call.product ?? sales.product_name, "product_name", normalizedEvidence)],
        ["دسته", supportedValue(call.product_category ?? sales.product_category, "product_category", normalizedEvidence)],
        ["تعداد", supportedValue(sales.quantity, "quantity", normalizedEvidence)],
        ["مبلغ دقیق", supportedValue(sales.exact_amount, "exact_amount", normalizedEvidence)],
        ["بودجه", supportedValue(joinRange(sales.budget_min, sales.budget_max), "budget", normalizedEvidence)],
        ["تخفیف", supportedValue(sales.requested_discount, "requested_discount", normalizedEvidence)],
        ["رقیب", supportedValue(sales.competitor_name, "competitor_name", normalizedEvidence)],
        ["مرحله فروش", call.sales_stage ?? sales.sales_stage],
        ["دمای سرنخ", call.lead_temperature ?? sales.lead_temperature],
        ["احتمال خرید", supportedValue(sales.purchase_probability, "purchase_probability", normalizedEvidence)],
      ]} /></DetailCard>
      <DetailCard title="پیگیری"><DataGrid values={[
        ["نیازمند پیگیری", truthy(call.followup_required ?? followup.followup_required) ? "بله" : "خیر/نامشخص"],
        ["موعد", call.followup_at || call.followup_due_at ? formatDate(call.followup_at ?? call.followup_due_at) : supportedValue(followup.followup_date ?? followup.due_at, "followup_date", normalizedEvidence)],
        ["مسئول", followup.followup_owner ?? followup.assigned_agent],
        ["دلیل", followup.followup_reason ?? followup.reason],
        ["اقدام وعده‌داده‌شده", supportedValue(followup.promised_action, "promised_action", normalizedEvidence)],
        ["وضعیت", followup.task_status],
      ]} />{data.followups?.length ? <div className="linked-followups">{data.followups.map((task) => <span key={task.id}>{task.title} · {statusLabel[task.status] ?? task.status}</span>)}</div> : null}</DetailCard>
    </section>
    <section className="pilot-detail-grid three">
      <InsightList title="نقاط قوت" items={strengths} empty="نقطه قوتی ثبت نشده است." />
      <InsightList title="نقاط قابل بهبود" items={weaknesses} empty="موردی ثبت نشده است." />
      <InsightList title="پیشنهاد مربیگری" items={coaching} empty="پیشنهادی ثبت نشده است." />
    </section>
    <section className="pilot-detail-grid">
      <InsightList title="اعتراض‌های مشتری و پاسخ فروشنده" items={objections} empty="اعتراضی ثبت نشده است." />
      <InsightList title="تعهدات طرفین" items={commitments} empty="تعهدی ثبت نشده است." />
    </section>
    <section className="pilot-detail-grid"><InsightList title="فرصت‌های ازدست‌رفته" items={missed} empty="فرصت ازدست‌رفته‌ای ثبت نشده است." /><MetricsPanel items={metrics} /></section>
    <DetailCard title="امتیازنامه و KPI"><ScoreBreakdown values={scoreBreakdown} /></DetailCard>
    <SpeakerRoles callId={callId} segments={segments} enabled={!readOnly && capabilities.role_correction !== false} onChanged={load} onToast={onToast} />
    <Transcript callId={callId} segments={segments} enabled={!readOnly && capabilities.transcript_correction !== false} onSeek={seek} onChanged={load} onToast={onToast} />
    <EvidencePanel items={evidence} unsupportedCount={unsupportedCount} onSeek={seek} />
    {(call.error_message || call.status === "failed" || timeline.some((item) => item.status === "failed")) && <ErrorPanel call={call} timeline={timeline} isAdmin={isAdmin} />}
    {isAdmin && <DetailCard title="تحلیل خام (فقط مدیر)"><pre className="raw-json">{JSON.stringify(data.raw_analysis ?? data.analysis ?? {}, null, 2)}</pre></DetailCard>}
  </>;
}

function AudioPlayer({ source, duration, downloadable }: { source?: string | null; duration?: number | null; downloadable: boolean }) {
  const audioRef = useRef<HTMLAudioElement>(null); const [current, setCurrent] = useState(0); const [knownDuration, setKnownDuration] = useState(Number(duration) || 0); const [speed, setSpeed] = useState(1); const [playing, setPlaying] = useState(false);
  function jump(delta: number) { const audio = audioRef.current; if (audio) audio.currentTime = Math.max(0, Math.min(knownDuration || Infinity, audio.currentTime + delta)); }
  function toggle() { const audio = audioRef.current; if (!audio) return; if (audio.paused) void audio.play(); else audio.pause(); }
  if (!source) return <DetailCard title="فایل صوتی"><Empty title="صوت در دسترس نیست" description="فایل هنوز وارد نشده یا مجوز پخش آن غیرفعال است." /></DetailCard>;
  return <section className="live-panel pilot-audio"><div className="live-panel-head"><div><h2>پخش تماس</h2><p>{formatDuration(current)} از {formatDuration(knownDuration || duration)}</p></div>{downloadable ? <a className="pilot-button secondary" href={source} download>دریافت صوت</a> : <span className="status-muted">دانلود محدود است</span>}</div>
    <audio id="pilot-call-audio" ref={audioRef} src={source} preload="metadata" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onTimeUpdate={(event) => setCurrent(event.currentTarget.currentTime)} onLoadedMetadata={(event) => setKnownDuration(event.currentTarget.duration)} />
    <input className="audio-range" aria-label="موقعیت پخش" type="range" min="0" max={knownDuration || duration || 0} value={current} step="0.1" onChange={(event) => { const value = Number(event.target.value); setCurrent(value); const audio = audioRef.current; if (audio) audio.currentTime = value; }} />
    <div className="audio-actions"><button onClick={() => jump(-10)}>۱۰− ثانیه</button><button className="audio-play" onClick={toggle}>{playing ? "توقف" : "پخش"}</button><button onClick={() => jump(10)}>۱۰+ ثانیه</button><label>سرعت <select value={speed} onChange={(event) => { const value = Number(event.target.value); setSpeed(value); const audio = audioRef.current; if (audio) audio.playbackRate = value; }}><option value=".75">۰٫۷۵×</option><option value="1">۱×</option><option value="1.25">۱٫۲۵×</option><option value="1.5">۱٫۵×</option><option value="2">۲×</option></select></label></div>
  </section>;
}

function ProcessingTimeline({ items, currentStatus }: { items: ProcessingEvent[]; currentStatus: string }) {
  const visible = items.length ? items : [{ stage: currentStatus, status: currentStatus, created_at: null }];
  return <DetailCard title="خط زمانی پردازش"><div className="processing-timeline">{visible.map((item, index) => <article key={item.id ?? index} className={item.status === "failed" ? "failed" : item.status === "completed" ? "complete" : ""}><i /><div><strong>{statusLabel[item.stage ?? ""] ?? item.stage ?? "پردازش"}</strong><span>{statusLabel[item.status ?? ""] ?? item.status}</span>{item.safe_message && <p>{item.safe_message}</p>}</div><time>{formatDate(item.finished_at ?? item.started_at ?? item.created_at)}</time></article>)}</div></DetailCard>;
}

function SpeakerRoles({ callId, segments, enabled, onChanged, onToast }: { callId: string; segments: Segment[]; enabled: boolean; onChanged: () => Promise<void>; onToast: (value: string) => void }) {
  const speakers = useMemo(() => {
    const map = new Map<string, { role: string; confidence?: number | null; count: number }>();
    for (const segment of segments) {
      const id = String(segment.speaker_id ?? segment.speaker ?? "unknown");
      const old = map.get(id); map.set(id, { role: segment.role ?? segment.speaker_role ?? "unknown", confidence: segment.speaker_role_confidence ?? segment.role_confidence, count: (old?.count ?? 0) + 1 });
    }
    return [...map.entries()];
  }, [segments]);
  async function update(speaker: string, role: string) {
    try { await requestJson("/api/v1/calls/" + encodeURIComponent(callId) + "/speaker-roles", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ assignments: [{ speaker_id: speaker, role }], reanalyze: false }) }); await onChanged(); onToast("نقش تمام بخش‌های گوینده اصلاح شد"); }
    catch (cause) { onToast(cause instanceof Error ? cause.message : "اصلاح نقش انجام نشد"); }
  }
  async function swap() {
    if (!window.confirm("نقش فروشنده و مشتری در تمام مکالمه جابه‌جا شود؟")) return;
    const assignments = speakers.filter(([, info]) => ["agent", "seller", "customer"].includes(info.role)).map(([speaker, info]) => ({ speaker_id: speaker, role: info.role === "customer" ? "agent" : "customer" }));
    if (!assignments.length) { onToast("نقش مشخصی برای جابه‌جایی وجود ندارد"); return; }
    try { await requestJson("/api/v1/calls/" + encodeURIComponent(callId) + "/speaker-roles", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ assignments, reanalyze: false }) }); await onChanged(); onToast("نقش‌ها جابه‌جا شدند"); }
    catch (cause) { onToast(cause instanceof Error ? cause.message : "جابه‌جایی انجام نشد"); }
  }
  return <DetailCard title="نقش گوینده‌ها" action={<button disabled={!enabled || speakers.length < 2} onClick={() => void swap()}>جابه‌جایی فروشنده و مشتری</button>}>
    {speakers.length === 0 ? <Empty title="گوینده‌ای ثبت نشده است" description="پس از رونویسی، نقش‌ها اینجا قابل اصلاح می‌شوند." /> : <div className="speaker-grid">{speakers.map(([speaker, info]) => <label key={speaker}><div><strong>{speaker}</strong><span>{fa(info.count)} بخش · اطمینان {info.confidence == null ? "اندازه‌گیری نشده" : fa(Math.round(info.confidence * 100)) + "٪"}</span></div><select disabled={!enabled} value={info.role} onChange={(event) => void update(speaker, event.target.value)}><option value="agent">فروشنده</option><option value="customer">مشتری</option><option value="other">سایر</option><option value="unknown">نامشخص</option></select></label>)}</div>}
  </DetailCard>;
}

function Transcript({ segments, enabled, onSeek, onChanged, onToast }: { callId: string; segments: Segment[]; enabled: boolean; onSeek: (seconds?: number | null) => void; onChanged: () => Promise<void>; onToast: (value: string) => void }) {
  return <DetailCard title="متن کامل مکالمه"><p className="section-note">روی زمان بزنید تا صوت از همان لحظه پخش شود. اصلاح دستی با نام کاربر در تاریخچه ثبت می‌شود.</p>
    {segments.length === 0 ? <Empty title="متن هنوز آماده نیست" description="پس از پایان رونویسی، متن گوینده‌بندی‌شده نمایش داده می‌شود." /> : <div className="pilot-transcript">{segments.map((segment) => <TranscriptRow key={segment.id} segment={segment} enabled={enabled} onSeek={onSeek} onChanged={onChanged} onToast={onToast} />)}</div>}
  </DetailCard>;
}

function TranscriptRow({ segment, enabled, onSeek, onChanged, onToast }: { segment: Segment; enabled: boolean; onSeek: (seconds?: number | null) => void; onChanged: () => Promise<void>; onToast: (value: string) => void }) {
  const [editing, setEditing] = useState(false); const [text, setText] = useState(segment.text ?? segment.content ?? ""); const [role, setRole] = useState(segment.role ?? segment.speaker_role ?? "unknown"); const [busy, setBusy] = useState(false);
  const start = segment.start ?? segment.start_time;
  async function save() {
    if (!text.trim()) return; setBusy(true);
    try { await requestJson("/api/v1/transcript-segments/" + encodeURIComponent(segment.id), { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: text.trim(), content: text.trim(), role, speaker_role: role, reanalyze: false }) }); setEditing(false); await onChanged(); onToast("اصلاح متن ذخیره شد؛ برای اعمال در تحلیل، تحلیل مجدد را اجرا کنید."); }
    catch (cause) { onToast(cause instanceof Error ? cause.message : "ذخیره اصلاح انجام نشد"); }
    finally { setBusy(false); }
  }
  const corrected = truthy(segment.is_manually_corrected ?? segment.manually_corrected);
  return <article className={corrected ? "corrected" : ""}><header><button className="timestamp" onClick={() => onSeek(start)}>{formatDuration(start)}</button><strong>{roleLabel[role] ?? segment.speaker ?? role}</strong>{corrected && <span>اصلاح دستی</span>}{enabled && <button className="edit-link" onClick={() => setEditing(!editing)}>{editing ? "انصراف" : "اصلاح"}</button>}</header>
    {editing ? <div className="transcript-editor"><select value={role} onChange={(event) => setRole(event.target.value)}><option value="agent">فروشنده</option><option value="customer">مشتری</option><option value="other">سایر</option><option value="unknown">نامشخص</option></select><textarea value={text} onChange={(event) => setText(event.target.value)} rows={4} /><button disabled={busy || !text.trim()} onClick={() => void save()}>{busy ? "در حال ذخیره..." : "ذخیره اصلاح"}</button></div> : <p>{segment.text ?? segment.content}</p>}
  </article>;
}

function EvidencePanel({ items, unsupportedCount, onSeek }: { items: Evidence[]; unsupportedCount: number; onSeek: (seconds?: number | null) => void }) {
  return <DetailCard title="شواهد و نقل‌قول‌ها"><p className="section-note">فقط داده‌های تأییدشده، دارای شاهد یا استنباط‌شده نمایش داده می‌شوند. استنباط‌ها برچسب جدا دارند.</p>
    {unsupportedCount > 0 && <div className="evidence-warning">{fa(unsupportedCount)} استخراج بدون شاهد از نمایش به‌عنوان واقعیت حذف شده است.</div>}
    {items.length === 0 ? <Empty title="شاهد معتبری ثبت نشده است" description="تا اعتبارسنجی انجام نشود، داده استخراج‌شده قطعی نمایش داده نمی‌شود." /> : <div className="evidence-list">{items.map((item, index) => <article key={item.id ?? index}><header><strong>{item.field_name ?? item.field ?? "فیلد استخراج‌شده"}</strong><span className={"validation " + (item.validation_status ?? "")}>{validationLabel[item.validation_status ?? ""] ?? item.validation_status}</span></header><p>«{item.exact_quote ?? item.quote ?? "نقل‌قول ثبت نشده"}»</p><footer><span>اطمینان {item.confidence == null ? "—" : fa(Math.round(item.confidence * 100)) + "٪"}</span><button onClick={() => onSeek(item.start_seconds ?? item.start_time)}>پخش شاهد در {formatDuration(item.start_seconds ?? item.start_time)}</button></footer></article>)}</div>}
  </DetailCard>;
}

function ErrorPanel({ call, timeline, isAdmin }: { call: CallItem & Record<string, unknown>; timeline: ProcessingEvent[]; isAdmin: boolean }) {
  const failed = [...timeline].reverse().find((item) => item.status === "failed");
  return <DetailCard title="اطلاعات خطا"><div className="error-grid"><DataGrid values={[
    ["مرحله", call.failed_stage ?? failed?.stage],["نوع", call.error_type ?? failed?.error_type],["پیام امن", call.error_message ?? failed?.safe_message],
    ["تعداد Retry", call.retry_count],["آخرین Retry", formatDate(String(call.last_retry_at ?? ""))],["Retry بعدی", formatDate(String(call.next_retry_at ?? ""))],
    ["Worker", call.worker ?? failed?.worker],["Correlation ID", call.correlation_id ?? failed?.correlation_id],
  ]} />{isAdmin && call.stack_trace ? <details><summary>Stack trace مدیر</summary><pre className="raw-json">{String(call.stack_trace)}</pre></details> : null}</div></DetailCard>;
}

function InsightList({ title, items, empty }: { title: string; items: Array<Record<string, unknown>>; empty: string }) {
  return <DetailCard title={title}>{items.length ? <div className="insight-list">{items.map((item, index) => <article key={index}><strong>{firstString(item.title, item.name, item.objection, item.commitment, item.recommendation) || "مورد " + fa(index + 1)}</strong><p>{firstString(item.action, item.description, item.response, item.better_response, item.detail, item.text) || displayValue(item)}</p>{item.score != null && <span>امتیاز {fa(String(item.score))}</span>}</article>)}</div> : <p className="muted-copy">{empty}</p>}</DetailCard>;
}

function ScoreBreakdown({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values);
  return entries.length ? <div className="score-breakdown">{entries.map(([key, value]) => { const record = asRecord(value); const score = firstNumber(record.score, record.value, value); return <article key={key}><div><strong>{record.label ? String(record.label) : key}</strong><span>{record.evidence ? String(record.evidence) : ""}</span></div><b>{score == null ? displayValue(value) : fa(score)}</b></article>; })}</div> : <Empty title="امتیاز تفصیلی وجود ندارد" description="پس از فعال‌شدن چک‌لیست KPI و تحلیل تماس، جزئیات امتیاز ظاهر می‌شود." />;
}

function MetricsPanel({ items }: { items: Array<Record<string, unknown>> }) {
  const sourceLabels: Record<string, string> = {
    measured: "اندازه‌گیری‌شده",
    inferred: "استنباط‌شده",
    confirmed: "تأییدشده",
    unavailable: "غیرقابل محاسبه",
  };
  return <DetailCard title="شاخص‌های تماس">{items.length ? <div className="insight-list">{items.map((item, index) => {
    const label = firstString(item.label, item.title, item.name, item.key) || "شاخص " + fa(index + 1);
    const value = item.value ?? item.score ?? item.result;
    const source = firstString(item.source, item.measurement_type, item.status);
    const note = firstString(item.note, item.description, item.explanation);
    return <article key={String(item.key ?? item.name ?? index)}><strong>{label}</strong><p>{displayValue(value)}</p>{source && <span>{sourceLabels[source] ?? source}</span>}{note && <small>{note}</small>}</article>;
  })}</div> : <p className="muted-copy">شاخص قابل‌اندازه‌گیری برای این تماس ثبت نشده است.</p>}</DetailCard>;
}

function DetailCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return <section className="live-panel detail-card"><div className="live-panel-head"><div><h2>{title}</h2></div>{action}</div>{children}</section>;
}
function DataGrid({ values }: { values: Array<[string, unknown]> }) { return <dl className="data-grid">{values.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{displayValue(value)}</dd></div>)}</dl>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="pilot-field"><span>{label}</span>{children}</label>; }
function CapabilityNotice({ children }: { children: React.ReactNode }) { return <div className="capability-notice"><strong>محدودیت محیط فعلی</strong><span>{children}</span></div>; }
function Empty({ title, description }: { title: string; description: string }) { return <div className="live-empty"><span>＋</span><h3>{title}</h3><p>{description}</p></div>; }
function LoadingRows() { return <div className="pilot-loading" aria-label="در حال دریافت"><i /><i /><i /></div>; }
function LoadingDetail() { return <div className="pilot-detail-loading"><LoadingRows /><LoadingRows /><LoadingRows /></div>; }
function InlineError({ message, onRetry }: { message: string; onRetry: () => void | Promise<void> }) { return <div className="pilot-error"><strong>دریافت اطلاعات انجام نشد</strong><p>{message}</p><button onClick={() => void onRetry()}>تلاش دوباره</button></div>; }
function Pagination({ page, pages, onMove }: { page: number; pages: number; onMove: (page: number) => void }) { return <nav className="pilot-pagination" aria-label="صفحه‌بندی"><button disabled={page <= 1} onClick={() => onMove(page - 1)}>صفحه قبل</button><span>صفحه {fa(page)} از {fa(pages)}</span><button disabled={page >= pages} onClick={() => onMove(page + 1)}>صفحه بعد</button></nav>; }

function asRecord(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function nested(source: Record<string, unknown>, keys: string[]) { for (const key of keys) { const value = asRecord(source[key]); if (Object.keys(value).length) return value; } return {}; }
function firstString(...values: unknown[]) { for (const value of values) if (typeof value === "string" && value.trim()) return value.trim(); return ""; }
function firstNumber(...values: unknown[]) { for (const value of values) { const number = Number(value); if (value !== null && value !== undefined && value !== "" && Number.isFinite(number)) return number; } return null; }
function truthy(value: unknown) { return value === true || value === 1 || value === "true" || value === "1"; }
function recordList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return value == null ? [] : [{ text: value }];
  return value.map((item) => typeof item === "string" ? { text: item } : asRecord(item)).filter((item) => Object.keys(item).length > 0);
}
function scoreItemsRecord(value: unknown): Record<string, unknown> {
  if (!Array.isArray(value)) return asRecord(value);
  return Object.fromEntries(value.map((item, index) => {
    const record = asRecord(item);
    const key = firstString(record.key, record.name, record.label) || "شاخص " + fa(index + 1);
    return [key, Object.keys(record).length ? record : item];
  }));
}
function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "ثبت نشده";
  if (typeof value === "boolean") return value ? "بله" : "خیر";
  if (typeof value === "number") return fa(value);
  if (Array.isArray(value)) return value.map(displayValue).join("، ") || "ثبت نشده";
  if (typeof value === "object") return Object.entries(asRecord(value)).map(([key, item]) => key + ": " + displayValue(item)).join(" · ") || "ثبت نشده";
  return String(value);
}
function supportedValue(value: unknown, field: string, evidence?: Evidence[]) {
  const match = evidence?.find((item) => (item.field_name ?? item.field) === field);
  if (match?.validation_status === "unsupported") return "تأیید نشده";
  if (value === null || value === undefined || value === "") return null;
  return value;
}
function joinRange(min: unknown, max: unknown) { if (min == null && max == null) return null; return displayValue(min) + " تا " + displayValue(max); }

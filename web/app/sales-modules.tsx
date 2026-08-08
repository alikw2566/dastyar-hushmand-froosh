"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { CallItem, fa, requestJson } from "./pilot-views";

type Dataset = { calls: CallItem[]; loading: boolean; error: string; reload: () => void };
type OpenCall = (id: string) => void;

const outcomeLabel: Record<string, string> = { won: "فروش", lost: "ازدست‌رفته", follow_up: "نیازمند پیگیری", unknown: "نامشخص" };

function useCalls(): Dataset {
  const [calls, setCalls] = useState<CallItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const data = await requestJson<{ items?: CallItem[]; calls?: CallItem[] }>("/api/v1/calls?page=1&page_size=100&sort=created_at&order=desc");
      setCalls(data.items ?? data.calls ?? []);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "دریافت اطلاعات انجام نشد"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);
  return { calls, loading, error, reload: () => void load() };
}

function Shell({ eyebrow, title, description, data, children }: { eyebrow: string; title: string; description: string; data: Dataset; children: React.ReactNode }) {
  return <><div className="live-heading"><div><span>{eyebrow}</span><h1>{title}</h1><p>{description}</p></div></div>
    {data.loading ? <State title="در حال محاسبه از تماس‌های واقعی" /> : data.error ? <State title={data.error} action={<button onClick={data.reload}>تلاش دوباره</button>} /> : children}</>;
}

function State({ title, action }: { title: string; action?: React.ReactNode }) { return <section className="live-panel"><div className="live-empty"><span>＋</span><h3>{title}</h3>{action}</div></section>; }
function Empty({ title, text }: { title: string; text: string }) { return <div className="live-empty"><span>＋</span><h3>{title}</h3><p>{text}</p></div>; }
function value(call: CallItem, first: keyof CallItem, second?: keyof CallItem) { return String(call[first] ?? (second ? call[second] : "") ?? "").trim(); }
function score(call: CallItem) { return typeof call.score === "number" ? call.score : null; }

export function CustomersView({ onOpenCall }: { onOpenCall: OpenCall }) {
  const data = useCalls();
  const [query, setQuery] = useState("");
  const customers = useMemo(() => {
    const map = new Map<string, { key: string; name: string; company: string; phone: string; city: string; product: string; calls: number; last: CallItem }>();
    for (const call of data.calls) {
      const name = value(call, "customer_name") || "مشتری نامشخص"; const phone = value(call, "phone_number", "phone");
      const key = phone || name + "|" + value(call, "company_name", "company"); const current = map.get(key);
      if (current) current.calls += 1;
      else map.set(key, { key, name, phone, company: value(call, "company_name", "company"), city: value(call, "city"), product: value(call, "product_name", "product"), calls: 1, last: call });
    }
    const needle = query.trim().toLocaleLowerCase("fa");
    return [...map.values()].filter((item) => !needle || [item.name, item.phone, item.company, item.city, item.product].some((field) => field.toLocaleLowerCase("fa").includes(needle)));
  }, [data.calls, query]);
  return <Shell eyebrow="مدیریت ارتباط" title="مشتریان" description="پروفایل مشتریان مستقیماً از اطلاعات استخراج‌شده تماس‌ها ساخته می‌شود." data={data}>
    <section className="live-panel"><div className="module-toolbar"><input aria-label="جست‌وجوی مشتری" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="نام، شماره، شرکت، شهر یا محصول" /><span>{fa(customers.length)} مشتری</span></div>
      {customers.length === 0 ? <Empty title="مشتری‌ای ثبت نشده است" text="پس از پردازش اولین تماس، اطلاعات استخراج‌شده مشتری اینجا قرار می‌گیرد." /> : <div className="live-table-wrap"><table className="live-table"><thead><tr><th>مشتری</th><th>شرکت و شهر</th><th>محصول</th><th>تعداد تماس</th><th>آخرین نتیجه</th><th /></tr></thead><tbody>{customers.map((item) => <tr key={item.key}><td><strong>{item.name}</strong><small>{item.phone || "شماره نامشخص"}</small></td><td>{item.company || "—"}<small>{item.city || ""}</small></td><td>{item.product || "—"}</td><td>{fa(item.calls)}</td><td><span className={"live-badge " + item.last.outcome}>{outcomeLabel[item.last.outcome] ?? item.last.outcome}</span></td><td><button onClick={() => onOpenCall(item.last.id)}>مشاهده</button></td></tr>)}</tbody></table></div>}
    </section></Shell>;
}

export function OpportunitiesView({ onOpenCall }: { onOpenCall: OpenCall }) {
  const data = useCalls();
  const opportunities = useMemo(() => data.calls.filter((call) => call.outcome === "lost" || call.outcome === "follow_up" || Boolean(call.followup_required) || (score(call) != null && score(call)! < 70)), [data.calls]);
  return <Shell eyebrow="تحلیل فروش" title="اعتراض‌ها و فرصت‌های ازدست‌رفته" description="تماس‌های پرریسک، ازدست‌رفته یا نیازمند اقدام برای بازبینی مدیر جدا شده‌اند." data={data}>
    <section className="module-metrics"><article><span>نیازمند بررسی</span><strong>{fa(opportunities.length)}</strong></article><article><span>ازدست‌رفته</span><strong>{fa(opportunities.filter((item) => item.outcome === "lost").length)}</strong></article><article><span>پیگیری‌دار</span><strong>{fa(opportunities.filter((item) => item.outcome === "follow_up" || item.followup_required).length)}</strong></article></section>
    <section className="live-panel">{opportunities.length === 0 ? <Empty title="فرصت پرریسکی ثبت نشده است" text="تحلیل اعتراض، پاسخ بهتر و شاهد زمانی داخل جزئیات هر تماس پردازش‌شده نمایش داده می‌شود." /> : <div className="module-card-grid">{opportunities.map((call) => <article key={call.id} className="module-card"><header><span className={"live-badge " + call.outcome}>{outcomeLabel[call.outcome] ?? call.outcome}</span><b>{score(call) == null ? "بدون امتیاز" : fa(score(call)!) + " از ۱۰۰"}</b></header><h3>{value(call, "customer_name") || "مشتری نامشخص"}</h3><p>{value(call, "company_name", "company") || value(call, "product_name", "product") || call.original_file_name}</p><small>{call.followup_required ? "پیگیری لازم است" : call.outcome === "lost" ? "فرصت ازدست‌رفته" : "نیازمند بازبینی کیفیت"}</small><button onClick={() => onOpenCall(call.id)}>دیدن تحلیل و شواهد</button></article>)}</div>}</section>
  </Shell>;
}

type SellerStat = { seller: string; calls: number; scored: number; totalScore: number; won: number; followups: number };
function sellerStats(calls: CallItem[]) {
  const map = new Map<string, SellerStat>();
  for (const call of calls) { const seller = value(call, "seller_name") || value(call, "seller_email") || "فروشنده نامشخص"; const item = map.get(seller) ?? { seller, calls: 0, scored: 0, totalScore: 0, won: 0, followups: 0 }; item.calls += 1; if (score(call) != null) { item.scored += 1; item.totalScore += score(call)!; } if (call.outcome === "won") item.won += 1; if (call.followup_required || call.outcome === "follow_up") item.followups += 1; map.set(seller, item); }
  return [...map.values()].sort((a, b) => (b.scored ? b.totalScore / b.scored : -1) - (a.scored ? a.totalScore / a.scored : -1));
}

export function TeamPerformanceView() {
  type TeamRow = { seller_email?: string | null; seller_name?: string | null; calls: number; average_score?: number | null; won: number; conversion_rate: number };
  const [items, setItems] = useState<TeamRow[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const load = useCallback(async () => { setLoading(true); setError(""); try { const result = await requestJson<{ items: TeamRow[] }>("/api/v1/reports/team"); setItems(result.items ?? []); } catch (cause) { setError(cause instanceof Error ? cause.message : "دریافت گزارش تیم انجام نشد"); } finally { setLoading(false); } }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);
  const data: Dataset = { calls: [], loading, error, reload: () => void load() };
  return <Shell eyebrow="مدیریت تیم" title="مقایسه فروشنده‌ها" description="این گزارش در سرور و فقط از نسخه‌های رسمی منتشرشده محاسبه می‌شود." data={data}><section className="live-panel">{items.length === 0 ? <Empty title="داده رسمی برای مقایسه وجود ندارد" text="پس از بازبینی و انتشار تماس‌ها، جدول عملکرد تیم ساخته می‌شود." /> : <div className="live-table-wrap"><table className="live-table"><thead><tr><th>فروشنده</th><th>تماس رسمی</th><th>امتیاز متوسط</th><th>فروش تأییدشده</th><th>نرخ تبدیل</th></tr></thead><tbody>{items.map((item) => <tr key={item.seller_email || item.seller_name || "unknown"}><td><strong>{item.seller_name || item.seller_email || "فروشنده نامشخص"}</strong></td><td>{fa(item.calls)}</td><td>{item.average_score == null ? "—" : fa(item.average_score)}</td><td>{fa(item.won)}</td><td>{fa(item.conversion_rate)}٪</td></tr>)}</tbody></table></div>}</section></Shell>;
}

export function CoachingView() {
  const data = useCalls(); const stats = useMemo(() => sellerStats(data.calls), [data.calls]);
  function advice(item: SellerStat) { const avg = item.scored ? item.totalScore / item.scored : null; if (avg == null) return "برای مربیگری، تماس امتیازدهی‌شده کافی نیست."; if (avg < 60) return "تمرکز فوری روی کشف نیاز، گوش‌دادن فعال و پاسخ به اعتراض."; if (item.followups > item.calls / 2) return "بهبود بستن تماس و توافق روشن روی اقدام بعدی."; if (item.won === 0) return "بازبینی تماس‌های ازدست‌رفته و تمرین پیشنهاد ارزش."; return "عملکرد پایدار؛ روی تکرار الگوی تماس‌های موفق تمرکز شود."; }
  return <Shell eyebrow="رشد فروشنده" title="مربیگری و پیشرفت" description="پیشنهاد مربیگری از امتیاز و نتیجه واقعی تماس‌ها ساخته می‌شود و با ورود داده جدید تغییر می‌کند." data={data}><section className="live-panel">{stats.length === 0 ? <Empty title="برنامه مربیگری هنوز ساخته نشده است" text="حداقل یک تماس پردازش‌شده برای هر فروشنده لازم است." /> : <div className="module-card-grid">{stats.map((item) => <article className="module-card" key={item.seller}><header><span className="live-badge">{fa(item.calls)} تماس</span><b>{item.scored ? fa(Math.round(item.totalScore / item.scored)) + "/۱۰۰" : "بدون امتیاز"}</b></header><h3>{item.seller}</h3><p>{advice(item)}</p><div className="module-progress"><i style={{ width: (item.scored ? Math.max(4, Math.min(100, item.totalScore / item.scored)) : 4) + "%" }} /></div></article>)}</div>}</section></Shell>;
}

export function ReportsView() {
  const data = useCalls(); const stats = useMemo(() => { const total = data.calls.length; const won = data.calls.filter((c) => c.outcome === "won").length; const lost = data.calls.filter((c) => c.outcome === "lost").length; const follow = data.calls.filter((c) => c.outcome === "follow_up" || c.followup_required).length; const scored = data.calls.filter((c) => score(c) != null); return { total, won, lost, follow, avg: scored.length ? Math.round(scored.reduce((sum, c) => sum + score(c)!, 0) / scored.length) : null }; }, [data.calls]);
  return <Shell eyebrow="تصمیم‌گیری مدیریتی" title="گزارش‌های فروش" description="گزارش این صفحه بر اساس داده موجود است؛ مقدار ناموجود با خط تیره نمایش داده می‌شود." data={data}><section className="module-metrics five"><article><span>کل تماس</span><strong>{fa(stats.total)}</strong></article><article><span>فروش</span><strong>{fa(stats.won)}</strong></article><article><span>ازدست‌رفته</span><strong>{fa(stats.lost)}</strong></article><article><span>پیگیری</span><strong>{fa(stats.follow)}</strong></article><article><span>امتیاز متوسط</span><strong>{stats.avg == null ? "—" : fa(stats.avg)}</strong></article></section><section className="live-panel"><div className="live-panel-head"><div><h2>توزیع نتیجه تماس</h2><p>درصد فقط از تماس‌های موجود محاسبه می‌شود.</p></div></div>{stats.total === 0 ? <Empty title="گزارشی برای نمایش وجود ندارد" text="با ورود تماس واقعی، نمودار نتیجه و KPIها اینجا فعال می‌شوند." /> : <div className="report-bars">{[["فروش", stats.won], ["ازدست‌رفته", stats.lost], ["پیگیری", stats.follow], ["سایر", Math.max(0, stats.total - stats.won - stats.lost - stats.follow)]].map(([label, count]) => <div key={String(label)}><header><span>{label}</span><b>{fa(Number(count))}</b></header><i><b style={{ width: Math.round(Number(count) / stats.total * 100) + "%" }} /></i></div>)}</div>}</section></Shell>;
}

type SearchEvidence = { call_id: string; position?: number; start_seconds?: number | null; speaker_label?: string; content: string };
export function SearchView({ onOpenCall }: { onOpenCall: OpenCall }) {
  const [query, setQuery] = useState(""); const [results, setResults] = useState<SearchEvidence[]>([]); const [searched, setSearched] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function submit(event: FormEvent) { event.preventDefault(); const q = query.trim(); if (q.length < 2) return; setBusy(true); setError(""); try { const data = await requestJson<{ evidence?: SearchEvidence[] }>("/api/v1/search?q=" + encodeURIComponent(q)); setResults(data.evidence ?? []); setSearched(true); } catch (cause) { setError(cause instanceof Error ? cause.message : "جست‌وجو انجام نشد"); } finally { setBusy(false); } }
  return <><div className="live-heading"><div><span>دانش مکالمات</span><h1>جست‌وجوی مکالمات</h1><p>نتیجه همراه شناسه تماس، گوینده و زمان شاهد نمایش داده می‌شود.</p></div></div><form className="module-search" onSubmit={submit}><input aria-label="عبارت جست‌وجو" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="مثلاً قیمت، بودجه، اعتراض یا نام محصول" minLength={2} required /><button disabled={busy}>{busy ? "در حال جست‌وجو..." : "جست‌وجو"}</button></form>{error && <p className="live-form-error">{error}</p>}<section className="live-panel">{!searched ? <Empty title="عبارتی را جست‌وجو کنید" text="جست‌وجوی فارسی ی/ي و ک/ك را یکسان‌سازی می‌کند." /> : results.length === 0 ? <Empty title="نتیجه‌ای پیدا نشد" text="عبارت دیگری را امتحان کنید یا ابتدا تماس‌ها را پردازش کنید." /> : <div className="search-results">{results.map((item, index) => <article key={item.call_id + "-" + (item.position ?? index)}><header><span>{item.speaker_label || "گوینده نامشخص"}</span><b>{item.start_seconds == null ? "بدون زمان" : fa(Math.floor(item.start_seconds / 60)) + ":" + String(Math.floor(item.start_seconds % 60)).padStart(2, "0")}</b></header><p>{item.content}</p><button onClick={() => onOpenCall(item.call_id)}>بازکردن تماس</button></article>)}</div>}</section></>;
}

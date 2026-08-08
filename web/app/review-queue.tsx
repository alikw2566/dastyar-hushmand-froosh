"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fa, formatDate, requestJson } from "./pilot-views";

type ReviewItem = {
  id: string;
  call_id: string;
  file_name: string;
  seller_email?: string | null;
  customer_name?: string | null;
  status: string;
  reasons: string[];
  assignee_email?: string | null;
  analysis_version: number;
  confidence?: number | null;
  outcome?: string | null;
  score?: number | null;
  created_at: string;
};

const statusLabels: Record<string, string> = {
  queued_for_review: "در صف بازبینی",
  in_review: "در حال بازبینی",
  changes_requested: "نیازمند اصلاح",
  approved: "تأییدشده",
  rejected: "ردشده",
  published: "منتشرشده",
  policy_approved: "تأیید سیاستی",
  superseded: "جایگزین‌شده",
};
const reasonLabels: Record<string, string> = {
  pilot_first_50: "۵۰ تماس اول پایلوت",
  low_confidence: "اطمینان پایین",
  unsupported_evidence: "شاهد ناکافی",
  ambiguous_speaker_roles: "نقش گوینده مبهم",
  critical_outcome: "نتیجه مهم فروش",
  critical_facts: "مبلغ، تاریخ یا تعهد مهم",
  quality_sample: "نمونه کنترل کیفیت",
  legacy_unreviewed: "خروجی قدیمی بررسی‌نشده",
};

export function ReviewQueue({ onOpenCall, onToast }: { onOpenCall: (id: string) => void; onToast: (message: string) => void }) {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [status, setStatus] = useState("queued_for_review");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    const query = new URLSearchParams();
    if (status) query.set("status", status);
    if (reason) query.set("reason", reason);
    try {
      const data = await requestJson<{ items: ReviewItem[] }>("/api/v1/reviews?" + query.toString());
      setItems(data.items ?? []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "دریافت صف بازبینی ناموفق بود");
    } finally { setLoading(false); }
  }, [reason, status]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function act(item: ReviewItem, action: "assign" | "approve" | "reject" | "request-changes" | "publish") {
    const needsNote = action === "reject" || action === "request-changes";
    const note = needsNote ? window.prompt("دلیل یا توضیح بازبینی را وارد کنید:") : window.prompt("یادداشت بازبینی (اختیاری):", "");
    if (note === null) return;
    setBusy(item.id + action);
    try {
      const body = action === "assign" ? { assignee_email: null, note } : { note };
      await requestJson(`/api/v1/reviews/${item.id}/${action}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      onToast(action === "publish" ? "نسخه رسمی منتشر شد" : "وضعیت بازبینی ثبت شد");
      await load();
    } catch (cause) { onToast(cause instanceof Error ? cause.message : "عملیات بازبینی انجام نشد"); }
    finally { setBusy(null); }
  }

  const pending = useMemo(() => items.filter((item) => !["published", "rejected", "superseded"].includes(item.status)).length, [items]);
  return <>
    <div className="live-heading"><div><span>کنترل کیفیت انسانی</span><h1>صف بازبینی خروجی هوش مصنوعی</h1><p>نسخه‌های پیش‌نویس را بررسی، اصلاح، تأیید و سپس به نسخه رسمی قابل استفاده تبدیل کنید.</p></div><div className="review-summary"><strong>{fa(pending)}</strong><span>مورد باز در این فیلتر</span></div></div>
    <section className="review-toolbar">
      <label><span>وضعیت</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">همه</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label><span>علت ورود به صف</span><select value={reason} onChange={(event) => setReason(event.target.value)}><option value="">همه علت‌ها</option>{Object.entries(reasonLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <button className="secondary" onClick={() => void load()}>تازه‌سازی</button>
    </section>
    <section className="live-panel">
      {loading ? <div className="review-state">در حال دریافت صف بازبینی…</div> : error ? <div className="review-state error"><p>{error}</p><button onClick={() => void load()}>تلاش دوباره</button></div> : items.length === 0 ? <div className="review-state"><h3>موردی در این فیلتر نیست</h3><p>فیلتر وضعیت یا علت را تغییر دهید.</p></div> : <div className="review-list">{items.map((item) => <article key={item.id}>
        <header><div><span className={`live-badge ${item.status}`}>{statusLabels[item.status] ?? item.status}</span><h3>{item.customer_name || item.file_name}</h3><p>{item.seller_email || "فروشنده نامشخص"} · {formatDate(item.created_at)}</p></div><div className="review-score"><strong>{item.score == null ? "—" : fa(item.score)}</strong><small>نسخه {fa(item.analysis_version)}</small></div></header>
        <div className="review-meta"><span>اطمینان: {item.confidence == null ? "—" : fa(Math.round(item.confidence * 100)) + "٪"}</span><span>نتیجه: {item.outcome || "نامشخص"}</span><span>بازبین: {item.assignee_email || "تخصیص‌نیافته"}</span></div>
        <div className="review-reasons">{item.reasons.map((value) => <span key={value}>{reasonLabels[value] ?? value}</span>)}</div>
        <footer><button className="secondary" onClick={() => onOpenCall(item.call_id)}>مشاهده تماس و شواهد</button>{item.status === "queued_for_review" && <button disabled={busy !== null} onClick={() => void act(item, "assign")}>شروع بازبینی</button>}{["queued_for_review", "in_review", "changes_requested"].includes(item.status) && <><button disabled={busy !== null} onClick={() => void act(item, "approve")}>تأیید</button><button className="warning" disabled={busy !== null} onClick={() => void act(item, "request-changes")}>درخواست اصلاح</button><button className="danger" disabled={busy !== null} onClick={() => void act(item, "reject")}>رد</button></>}{item.status === "approved" && <button disabled={busy !== null} onClick={() => void act(item, "publish")}>انتشار نسخه رسمی</button>}</footer>
      </article>)}</div>}
    </section>
  </>;
}

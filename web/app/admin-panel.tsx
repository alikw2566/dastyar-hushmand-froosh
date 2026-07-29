"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type Organization = { id: string; name: string; plan: string; monthly_minute_limit: number; retention_days: number; automation_mode: string; used_minutes: number };
type Overview = { members: number; teams: number; calls: number; used_minutes: number; storage_bytes: number; pending_tasks: number; active_integrations: number; active_rules: number };
type Member = { id: string; email: string; full_name: string; role: string; active: number; team_id?: string | null; team_name?: string | null; last_login_at?: string | null };
type Team = { id: string; name: string; description: string; supervisor_email?: string | null; active: number; member_count: number };
type Criterion = { label: string; weight: number };
type Scorecard = { id: string; name: string; criteria: Criterion[]; active: number; created_at: string };
type Automation = { id: string; name: string; event: string; action: string; mode: string; enabled: number };
type Integration = { id: string; name: string; kind: string; status: string };
type AiSettings = { provider: string; transcription_model: string; analysis_model: string; min_confidence: number };
type SecuritySettings = { require_consent: number; audio_download_enabled: number };
type Audit = { id: string; actor_email: string; action: string; entity_type: string; entity_id?: string | null; created_at: string };
type AdminTab = "overview" | "members" | "teams" | "scorecards" | "automations" | "integrations" | "ai" | "security" | "audit";

const tabs: Array<{ id: AdminTab; label: string; icon: string }> = [
  { id: "overview", label: "نمای مدیریتی", icon: "◫" }, { id: "members", label: "کاربران", icon: "♙" },
  { id: "teams", label: "تیم‌ها", icon: "♟" }, { id: "scorecards", label: "KPI و امتیاز", icon: "◎" },
  { id: "automations", label: "اتوماسیون", icon: "⚡" }, { id: "integrations", label: "اتصال‌ها", icon: "⌁" },
  { id: "ai", label: "هوش مصنوعی", icon: "✦" }, { id: "security", label: "امنیت و داده", icon: "◇" },
  { id: "audit", label: "گزارش فعالیت", icon: "≡" },
];

const roleLabel: Record<string, string> = { admin: "مدیر", supervisor: "سرپرست", seller: "فروشنده" };
const actionLabel: Record<string, string> = {
  "organization.created": "فضای کاری ساخته شد", "organization.updated": "تنظیمات شرکت تغییر کرد", "member.created": "کاربر اضافه شد", "member.updated": "دسترسی کاربر تغییر کرد",
  "team.created": "تیم ساخته شد", "team.updated": "تیم تغییر کرد", "scorecard.created": "چک‌لیست ساخته شد", "scorecard.activated": "چک‌لیست فعال شد",
  "automation.created": "قانون ساخته شد", "automation.toggled": "وضعیت قانون تغییر کرد", "integration.created": "اتصال ساخته شد", "integration.toggled": "وضعیت اتصال تغییر کرد",
  "ai_settings.updated": "تنظیمات AI تغییر کرد", "security.updated": "تنظیمات امنیت تغییر کرد",
};

function fa(value: string | number) { return String(value).replace(/\d/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]); }
function date(value?: string | null) { return value ? new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "هنوز وارد نشده"; }
function bytes(value: number) { if (!value) return "۰ بایت"; const unit = value >= 1073741824 ? [1073741824, "گیگابایت"] : value >= 1048576 ? [1048576, "مگابایت"] : [1024, "کیلوبایت"]; return `${fa((value / Number(unit[0])).toFixed(1))} ${unit[1]}`; }

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init); const result = await response.json().catch(() => ({})) as { error?: string; detail?: string };
  if (!response.ok) throw new Error(result.error ?? result.detail ?? "request_failed"); return result as T;
}

export function AdminPanel({ organization, onOrganizationChanged, onToast }: { organization: Organization | null; onOrganizationChanged: () => Promise<void>; onToast: (message: string) => void }) {
  const [tab, setTab] = useState<AdminTab>("overview"); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null); const [members, setMembers] = useState<Member[]>([]); const [teams, setTeams] = useState<Team[]>([]);
  const [scorecards, setScorecards] = useState<Scorecard[]>([]); const [automations, setAutomations] = useState<Automation[]>([]); const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [aiSettings, setAiSettings] = useState<AiSettings | null>(null); const [security, setSecurity] = useState<SecuritySettings | null>(null); const [audits, setAudits] = useState<Audit[]>([]);

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [overviewData, memberData, teamData, scorecardData, automationData, integrationData, aiData, securityData, auditData] = await Promise.all([
        api<Overview>("/api/v1/admin/overview"), api<{ items: Member[] }>("/api/v1/admin/members"), api<{ items: Team[] }>("/api/v1/admin/teams"),
        api<{ items: Scorecard[] }>("/api/v1/admin/scorecards"), api<{ items: Automation[] }>("/api/v1/admin/automations"), api<{ items: Integration[] }>("/api/v1/admin/integrations"),
        api<AiSettings>("/api/v1/admin/ai-settings"), api<SecuritySettings>("/api/v1/admin/security"), api<{ items: Audit[] }>("/api/v1/admin/audit-logs"),
      ]);
      setOverview(overviewData); setMembers(memberData.items); setTeams(teamData.items); setScorecards(scorecardData.items); setAutomations(automationData.items); setIntegrations(integrationData.items); setAiSettings(aiData); setSecurity(securityData); setAudits(auditData.items);
    } catch { setError("دریافت اطلاعات مدیریتی انجام نشد. دسترسی مدیر و اتصال سرویس را بررسی کنید."); } finally { setLoading(false); }
  }, []);
  useEffect(() => { const timer = window.setTimeout(() => void refresh(), 0); return () => window.clearTimeout(timer); }, [refresh]);

  async function run(work: () => Promise<unknown>, success: string) { try { await work(); await refresh(); onToast(success); } catch (cause) { onToast(errorMessage(cause)); } }
  const activeScorecard = useMemo(() => scorecards.find((item) => Boolean(item.active)), [scorecards]);

  return <div className="admin-page">
    <div className="live-heading admin-title"><div><span>مرکز کنترل شرکت</span><h1>پنل مدیریت</h1><p>کاربران، کیفیت فروش، هوش مصنوعی و امنیت را از یک نقطه مدیریت کنید.</p></div><div className="admin-health"><i /> سامانه آماده است</div></div>
    <div className="admin-layout">
      <aside className="admin-nav">{tabs.map((item) => <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}><i>{item.icon}</i><span>{item.label}</span>{item.id === "members" && <b>{fa(members.length)}</b>}</button>)}</aside>
      <section className="admin-surface">
        {loading ? <AdminState title="در حال دریافت اطلاعات مدیریت" /> : error ? <AdminState title={error} action={<button onClick={() => void refresh()}>تلاش دوباره</button>} /> : <>
          {tab === "overview" && overview && <AdminOverview data={overview} organization={organization} activeScorecard={activeScorecard} onTab={setTab} />}
          {tab === "members" && <Members members={members} teams={teams} run={run} />}
          {tab === "teams" && <Teams teams={teams} members={members} run={run} />}
          {tab === "scorecards" && <Scorecards items={scorecards} run={run} />}
          {tab === "automations" && <Automations items={automations} run={run} />}
          {tab === "integrations" && <Integrations items={integrations} run={run} />}
          {tab === "ai" && aiSettings && <AiConfiguration settings={aiSettings} run={run} />}
          {tab === "security" && security && <Security organization={organization} settings={security} run={run} onOrganizationChanged={onOrganizationChanged} />}
          {tab === "audit" && <AuditLog items={audits} />}
        </>}
      </section>
    </div>
  </div>;
}

function errorMessage(cause: unknown) {
  const code = cause instanceof Error ? cause.message : "request_failed";
  const labels: Record<string, string> = { email_exists: "این ایمیل قبلاً ثبت شده است.", weak_password: "رمز باید حداقل ۱۰ کاراکتر و شامل عدد باشد.", last_admin_protected: "آخرین مدیر شرکت را نمی‌توان غیرفعال یا تنزل داد.", team_exists: "تیمی با این نام وجود دارد.", invalid_scorecard: "وزن معیارها باید دقیقاً ۱۰۰ باشد." };
  return labels[code] ?? "عملیات انجام نشد؛ اطلاعات را بررسی و دوباره تلاش کنید.";
}

function AdminOverview({ data, organization, activeScorecard, onTab }: { data: Overview; organization: Organization | null; activeScorecard?: Scorecard; onTab: (tab: AdminTab) => void }) {
  const usage = organization?.monthly_minute_limit ? Math.min(100, Math.round(data.used_minutes / organization.monthly_minute_limit * 100)) : 0;
  return <><Header title="نمای مدیریتی" description="وضعیت لحظه‌ای فضای کاری و موارد نیازمند توجه" />
    <div className="admin-metrics"><Metric label="کاربران فعال" value={data.members} hint={`${data.teams} تیم`} icon="♙" /><Metric label="تماس‌های ثبت‌شده" value={data.calls} hint={`${data.pending_tasks} پیگیری باز`} icon="☎" /><Metric label="مصرف ماهانه" value={`${fa(data.used_minutes)} دقیقه`} hint={`${fa(usage)}٪ از سهمیه`} icon="◴" /><Metric label="فضای صوت" value={bytes(data.storage_bytes)} hint="ذخیره‌سازی واقعی" icon="▣" /></div>
    <div className="admin-overview-grid"><article className="admin-card"><div className="admin-card-head"><div><h3>آمادگی سامانه</h3><p>تنظیمات کلیدی برای بهره‌برداری</p></div><span className="status-good">فعال</span></div><Status label="چک‌لیست امتیاز" value={activeScorecard?.name ?? "هنوز تنظیم نشده"} good={Boolean(activeScorecard)} /><Status label="قوانین اتوماسیون" value={`${fa(data.active_rules)} قانون فعال`} good={data.active_rules > 0} /><Status label="اتصال‌های فعال" value={`${fa(data.active_integrations)} اتصال`} good={data.active_integrations > 0} /></article>
      <article className="admin-card"><div className="admin-card-head"><div><h3>راه‌اندازی سریع</h3><p>برای آماده‌شدن کامل این موارد را انجام دهید</p></div></div><Quick label="افزودن اعضای تیم" done={data.members > 1} onClick={() => onTab("members")} /><Quick label="ساخت تیم فروش" done={data.teams > 0} onClick={() => onTab("teams")} /><Quick label="فعال‌کردن KPI" done={Boolean(activeScorecard)} onClick={() => onTab("scorecards")} /><Quick label="تنظیم هوش مصنوعی" done onClick={() => onTab("ai")} /></article></div>
  </>;
}

function Members({ members, teams, run }: { members: Member[]; teams: Team[]; run: (work: () => Promise<unknown>, success: string) => Promise<void> }) {
  const [open, setOpen] = useState(false); const [query, setQuery] = useState(""); const filtered = members.filter((item) => `${item.full_name} ${item.email}`.toLowerCase().includes(query.toLowerCase()));
  async function add(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); await run(() => api("/api/v1/admin/members", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(values) }), "کاربر جدید اضافه شد"); setOpen(false); }
  return <><Header title="کاربران و دسترسی‌ها" description="نقش، تیم و وضعیت دسترسی اعضای شرکت" action={<button onClick={() => setOpen(!open)}>＋ افزودن عضو</button>} />
    {open && <form className="admin-form-grid admin-inline-card" onSubmit={add}><Field label="نام کامل"><input name="full_name" required minLength={2} /></Field><Field label="ایمیل"><input name="email" type="email" dir="ltr" required /></Field><Field label="رمز موقت"><input name="password" type="password" dir="ltr" minLength={10} required /></Field><Field label="نقش"><select name="role"><option value="seller">فروشنده</option><option value="supervisor">سرپرست</option><option value="admin">مدیر</option></select></Field><Field label="تیم"><select name="team_id"><option value="">بدون تیم</option>{teams.filter((team) => team.active).map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}</select></Field><button>ذخیره عضو</button></form>}
    <div className="admin-toolbar"><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="جست‌وجوی نام یا ایمیل" /><span>{fa(filtered.length)} عضو</span></div>
    <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>کاربر</th><th>نقش</th><th>تیم</th><th>آخرین ورود</th><th>دسترسی</th></tr></thead><tbody>{filtered.map((member) => <tr key={member.id}><td><div className="admin-person"><i>{member.full_name.slice(0, 1)}</i><span><strong>{member.full_name}</strong><small>{member.email}</small></span></div></td><td><select value={member.role} onChange={(event) => void run(() => api(`/api/v1/admin/members/${member.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ role: event.target.value, team_id: member.team_id, active: Boolean(member.active) }) }), "نقش کاربر تغییر کرد")}>{Object.entries(roleLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td><td><select value={member.team_id ?? ""} onChange={(event) => void run(() => api(`/api/v1/admin/members/${member.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ role: member.role, team_id: event.target.value, active: Boolean(member.active) }) }), "تیم کاربر تغییر کرد")}><option value="">بدون تیم</option>{teams.filter((team) => team.active).map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}</select></td><td>{date(member.last_login_at)}</td><td><Toggle checked={Boolean(member.active)} label={member.active ? "فعال" : "غیرفعال"} onChange={(active) => void run(() => api(`/api/v1/admin/members/${member.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ role: member.role, team_id: member.team_id, active }) }), active ? "دسترسی کاربر فعال شد" : "دسترسی کاربر متوقف شد")} /></td></tr>)}</tbody></table>{filtered.length === 0 && <AdminEmpty text="کاربری پیدا نشد" />}</div>
  </>;
}

function Teams({ teams, members, run }: { teams: Team[]; members: Member[]; run: (work: () => Promise<unknown>, success: string) => Promise<void> }) {
  const [open, setOpen] = useState(false); async function add(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); await run(() => api("/api/v1/admin/teams", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(values) }), "تیم جدید ساخته شد"); setOpen(false); }
  return <><Header title="تیم‌های فروش" description="ساختار تیم و سرپرست‌های مسئول" action={<button onClick={() => setOpen(!open)}>＋ تیم جدید</button>} />{open && <form className="admin-form-grid admin-inline-card" onSubmit={add}><Field label="نام تیم"><input name="name" required /></Field><Field label="توضیح"><input name="description" /></Field><Field label="سرپرست"><select name="supervisor_email"><option value="">بدون سرپرست</option>{members.filter((member) => member.role !== "seller" && member.active).map((member) => <option key={member.id} value={member.email}>{member.full_name}</option>)}</select></Field><button>ساخت تیم</button></form>}
    <div className="admin-card-grid">{teams.map((team) => <article className={`admin-team-card ${team.active ? "" : "disabled"}`} key={team.id}><header><i>♟</i><Toggle checked={Boolean(team.active)} label={team.active ? "فعال" : "متوقف"} onChange={(active) => void run(() => api(`/api/v1/admin/teams/${team.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ active }) }), "وضعیت تیم تغییر کرد")} /></header><h3>{team.name}</h3><p>{team.description || "بدون توضیح"}</p><footer><span>{fa(team.member_count)} عضو</span><span>{team.supervisor_email || "بدون سرپرست"}</span></footer></article>)}{teams.length === 0 && <AdminEmpty text="هنوز تیمی ساخته نشده است" />}</div>
  </>;
}

function Scorecards({ items, run }: { items: Scorecard[]; run: (work: () => Promise<unknown>, success: string) => Promise<void> }) {
  const [open, setOpen] = useState(false); const [name, setName] = useState(""); const [criteria, setCriteria] = useState<Criterion[]>([{ label: "", weight: 100 }]); const total = criteria.reduce((sum, item) => sum + Number(item.weight), 0);
  async function create(event: FormEvent) { event.preventDefault(); await run(() => api("/api/v1/admin/scorecards", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, criteria }) }), "چک‌لیست امتیاز ساخته شد"); setOpen(false); setName(""); setCriteria([{ label: "", weight: 100 }]); }
  return <><Header title="KPI و امتیازدهی" description="معیارهای اختصاصی ارزیابی مکالمات فروش" action={<button onClick={() => setOpen(!open)}>＋ چک‌لیست جدید</button>} />{open && <form className="admin-inline-card score-builder" onSubmit={create}><Field label="نام چک‌لیست"><input value={name} onChange={(event) => setName(event.target.value)} required /></Field><div className="criteria-list">{criteria.map((item, index) => <div key={index}><input value={item.label} onChange={(event) => setCriteria(criteria.map((row, rowIndex) => rowIndex === index ? { ...row, label: event.target.value } : row))} placeholder="نام معیار" required /><input type="number" min="1" max="100" value={item.weight} onChange={(event) => setCriteria(criteria.map((row, rowIndex) => rowIndex === index ? { ...row, weight: Number(event.target.value) } : row))} /><span>٪</span>{criteria.length > 1 && <button type="button" className="icon-danger" onClick={() => setCriteria(criteria.filter((_, rowIndex) => rowIndex !== index))}>×</button>}</div>)}</div><div className={`weight-summary ${total === 100 ? "valid" : "invalid"}`}><span>مجموع وزن‌ها</span><strong>{fa(total)}٪</strong></div><div className="form-actions"><button type="button" className="admin-secondary" onClick={() => setCriteria([...criteria, { label: "", weight: 0 }])}>افزودن معیار</button><button disabled={total !== 100}>ذخیره چک‌لیست</button></div></form>}
    <div className="admin-stack">{items.map((item) => <article className="admin-row-card" key={item.id}><div><span className={item.active ? "status-good" : "status-muted"}>{item.active ? "فعال" : "نسخه ذخیره‌شده"}</span><h3>{item.name}</h3><p>{fa(item.criteria.length)} معیار · مجموع وزن {fa(item.criteria.reduce((sum, criterion) => sum + Number(criterion.weight), 0))}٪</p></div><div className="criteria-chips">{item.criteria.slice(0, 4).map((criterion) => <span key={criterion.label}>{criterion.label} {fa(criterion.weight)}٪</span>)}</div>{!item.active && <button onClick={() => void run(() => api(`/api/v1/admin/scorecards/${item.id}/activate`, { method: "POST" }), "چک‌لیست فعال شد")}>فعال‌سازی</button>}</article>)}{items.length === 0 && <AdminEmpty text="هنوز چک‌لیست امتیازی ساخته نشده است" />}</div>
  </>;
}

function Automations({ items, run }: { items: Automation[]; run: (work: () => Promise<unknown>, success: string) => Promise<void> }) {
  const [open, setOpen] = useState(false); async function add(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); await run(() => api("/api/v1/admin/automations", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(values) }), "قانون اتوماسیون ساخته شد"); setOpen(false); }
  return <><Header title="اتوماسیون‌ها" description="اقدام‌های خودکار پس از تحلیل تماس" action={<button onClick={() => setOpen(!open)}>＋ قانون جدید</button>} />{open && <form className="admin-form-grid admin-inline-card" onSubmit={add}><Field label="نام قانون"><input name="name" required /></Field><Field label="رویداد"><select name="event"><option value="call.completed">تکمیل تحلیل تماس</option><option value="call.failed">خطای پردازش</option><option value="score.low">امتیاز پایین</option><option value="followup.overdue">پیگیری عقب‌افتاده</option></select></Field><Field label="اقدام"><select name="action"><option value="task.create">ساخت وظیفه</option><option value="message.create">ساخت پیام</option><option value="manager.notify">اعلان به مدیر</option><option value="webhook.send">ارسال Webhook</option></select></Field><Field label="شیوه اجرا"><select name="mode"><option value="approval">نیازمند تأیید</option><option value="draft">فقط پیش‌نویس</option><option value="automatic">خودکار</option></select></Field><button>ساخت قانون</button></form>}
    <div className="admin-stack">{items.map((item) => <article className="admin-row-card" key={item.id}><div className="rule-icon">⚡</div><div><h3>{item.name}</h3><p>{item.event} ← {item.action} · {item.mode}</p></div><Toggle checked={Boolean(item.enabled)} label={item.enabled ? "فعال" : "متوقف"} onChange={(enabled) => void run(() => api(`/api/v1/admin/automations/${item.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled }) }), "وضعیت قانون تغییر کرد")} /></article>)}{items.length === 0 && <AdminEmpty text="هنوز قانون اتوماسیونی ساخته نشده است" />}</div>
  </>;
}

function Integrations({ items, run }: { items: Integration[]; run: (work: () => Promise<unknown>, success: string) => Promise<void> }) {
  const [open, setOpen] = useState(false); async function add(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); await run(() => api("/api/v1/admin/integrations", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(values) }), "اتصال ذخیره شد"); setOpen(false); }
  return <><Header title="اتصال‌ها" description="ارتباط امن با سرویس‌های فروش و پیام‌رسانی" action={<button onClick={() => setOpen(!open)}>＋ اتصال جدید</button>} />{open && <form className="admin-form-grid admin-inline-card" onSubmit={add}><Field label="نام اتصال"><input name="name" required /></Field><Field label="نوع"><select name="kind"><option value="crm">CRM عمومی</option><option value="webhook">Webhook</option><option value="telephony">تلفن</option><option value="sms">پیامک</option><option value="email">ایمیل</option><option value="whatsapp">واتساپ</option><option value="api">API</option></select></Field><button>ذخیره اتصال</button></form>}
    <div className="admin-card-grid integrations-grid">{items.map((item) => <article className="admin-team-card" key={item.id}><header><i>⌁</i><span className={item.status === "active" ? "status-good" : "status-muted"}>{item.status === "active" ? "فعال" : "غیرفعال"}</span></header><h3>{item.name}</h3><p>{item.kind}</p><footer><Toggle checked={item.status === "active"} label={item.status === "active" ? "متصل" : "قطع"} onChange={(active) => void run(() => api(`/api/v1/admin/integrations/${item.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ status: active ? "active" : "inactive" }) }), "وضعیت اتصال تغییر کرد")} /></footer></article>)}{items.length === 0 && <AdminEmpty text="هنوز اتصالی تعریف نشده است" />}</div>
  </>;
}

function AiConfiguration({ settings, run }: { settings: AiSettings; run: (work: () => Promise<unknown>, success: string) => Promise<void> }) {
  const [form, setForm] = useState(settings); async function save(event: FormEvent) { event.preventDefault(); await run(() => api("/api/v1/admin/ai-settings", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(form) }), "تنظیمات هوش مصنوعی ذخیره شد"); }
  return <><Header title="هوش مصنوعی" description="مدل‌های رونویسی و تحلیل مکالمات" /><form className="admin-settings-form" onSubmit={save}><section className="admin-card"><div className="admin-card-head"><div><h3>مدل و ارائه‌دهنده</h3><p>کلید سرویس از متغیر امن سرور خوانده می‌شود و در مرورگر نمایش داده نمی‌شود.</p></div><span className="status-good">امن</span></div><div className="admin-form-grid"><Field label="ارائه‌دهنده"><select value={form.provider} onChange={(event) => setForm({ ...form, provider: event.target.value })}><option value="openai">OpenAI</option><option value="avalai">AvalAI</option></select></Field><Field label="مدل رونویسی"><input dir="ltr" value={form.transcription_model} onChange={(event) => setForm({ ...form, transcription_model: event.target.value })} /></Field><Field label="مدل تحلیل"><input dir="ltr" value={form.analysis_model} onChange={(event) => setForm({ ...form, analysis_model: event.target.value })} /></Field><Field label={`حداقل اطمینان: ${fa(Math.round(form.min_confidence * 100))}٪`}><input type="range" min="0.5" max="0.99" step="0.01" value={form.min_confidence} onChange={(event) => setForm({ ...form, min_confidence: Number(event.target.value) })} /></Field></div></section><button>ذخیره تنظیمات AI</button></form></>;
}

function Security({ organization, settings, run, onOrganizationChanged }: { organization: Organization | null; settings: SecuritySettings; run: (work: () => Promise<unknown>, success: string) => Promise<void>; onOrganizationChanged: () => Promise<void> }) {
  const [name, setName] = useState(organization?.name ?? ""); const [retention, setRetention] = useState(organization?.retention_days ?? 30); const [mode, setMode] = useState(organization?.automation_mode ?? "approval"); const [consent, setConsent] = useState(Boolean(settings.require_consent)); const [audio, setAudio] = useState(Boolean(settings.audio_download_enabled));
  async function save(event: FormEvent) { event.preventDefault(); await run(async () => { await Promise.all([api("/api/v1/admin/organization", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, retention_days: retention, automation_mode: mode }) }), api("/api/v1/admin/security", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ require_consent: consent, audio_download_enabled: audio }) })]); await onOrganizationChanged(); }, "تنظیمات امنیت و شرکت ذخیره شد"); }
  return <><Header title="امنیت و داده" description="سیاست‌های دسترسی، رضایت ضبط و نگهداری اطلاعات" /><form className="admin-settings-form" onSubmit={save}><section className="admin-card"><h3>فضای کاری</h3><div className="admin-form-grid"><Field label="نام شرکت"><input value={name} onChange={(event) => setName(event.target.value)} required /></Field><Field label="نگهداری فایل صوتی"><select value={retention} onChange={(event) => setRetention(Number(event.target.value))}><option value="30">۳۰ روز</option><option value="90">۹۰ روز</option><option value="365">یک سال</option></select></Field><Field label="حالت اتوماسیون"><select value={mode} onChange={(event) => setMode(event.target.value)}><option value="draft">فقط پیش‌نویس</option><option value="approval">نیازمند تأیید</option><option value="automatic">خودکار</option></select></Field></div></section><section className="admin-card security-options"><h3>کنترل دسترسی</h3><label><span><strong>اجبار رضایت ضبط</strong><small>بدون تأیید رضایت، فایل تماس پذیرفته نمی‌شود.</small></span><Toggle checked={consent} label={consent ? "فعال" : "غیرفعال"} onChange={setConsent} /></label><label><span><strong>اجازه دریافت فایل صوتی</strong><small>در صورت توقف، پخش و دانلود صوت از API مسدود می‌شود.</small></span><Toggle checked={audio} label={audio ? "فعال" : "غیرفعال"} onChange={setAudio} /></label></section><button>ذخیره همه تنظیمات</button></form></>;
}

function AuditLog({ items }: { items: Audit[] }) { return <><Header title="گزارش فعالیت" description="ردپای تغییرات مدیریتی فضای کاری" /><div className="admin-timeline">{items.map((item) => <article key={item.id}><i /><div><strong>{actionLabel[item.action] ?? item.action}</strong><p>{item.actor_email} · {item.entity_type}</p></div><time>{date(item.created_at)}</time></article>)}{items.length === 0 && <AdminEmpty text="هنوز فعالیت مدیریتی ثبت نشده است" />}</div></>; }

function Header({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) { return <header className="admin-section-head"><div><h2>{title}</h2><p>{description}</p></div>{action}</header>; }
function Metric({ label, value, hint, icon }: { label: string; value: string | number; hint: string; icon: string }) { return <article><i>{icon}</i><span>{label}</span><strong>{typeof value === "number" ? fa(value) : value}</strong><small>{hint}</small></article>; }
function Status({ label, value, good }: { label: string; value: string; good: boolean }) { return <div className="admin-status-row"><i className={good ? "good" : "warn"}>{good ? "✓" : "!"}</i><span><strong>{label}</strong><small>{value}</small></span></div>; }
function Quick({ label, done, onClick }: { label: string; done: boolean; onClick: () => void }) { return <button className="admin-quick" onClick={onClick}><i className={done ? "done" : ""}>{done ? "✓" : "○"}</i><span>{label}</span><b>←</b></button>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="admin-field"><span>{label}</span>{children}</label>; }
function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (checked: boolean) => void; label: string }) { return <label className="admin-toggle"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><i /><span>{label}</span></label>; }
function AdminState({ title, action }: { title: string; action?: React.ReactNode }) { return <div className="admin-state"><i>◌</i><p>{title}</p>{action}</div>; }
function AdminEmpty({ text }: { text: string }) { return <div className="admin-empty"><i>＋</i><p>{text}</p></div>; }

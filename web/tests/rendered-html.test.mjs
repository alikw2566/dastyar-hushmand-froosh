import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

test("ships a gated Persian dashboard without sample records", async () => {
  const [layout, page, auth, dashboard] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/auth/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/sales-dashboard.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(layout, /<html lang="fa" dir="rtl"/i);
  assert.match(layout, /مکالمه‌بان/);
  assert.match(page, /redirect\("\/auth"\)/);
  assert.match(auth, /ساخت حساب جدید/);
  assert.match(auth, /دستیار هوشمند فروش/);
  assert.match(dashboard, /اطلاعات واقعی فضای کاری شما/);
  assert.match(dashboard, /دستیار هوشمند فروش/);
  assert.match(dashboard, /پنل مدیریت/);
  assert.match(dashboard, /item\.id !== "settings"/);
  assert.match(dashboard, /هنوز تماسی ثبت نشده است/);
  assert.match(dashboard, /api\/v1\/calls/);
  assert.match(dashboard, /رضایت لازم برای ضبط/);
  assert.doesNotMatch(dashboard, /codex-preview/i);
});

test("ships production metadata and required Sites bindings", async () => {
  const [layout, hosting, packageJson] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../.openai/hosting.json", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  assert.match(layout, /og\.png/);
  assert.deepEqual(JSON.parse(hosting), {
    project_id: "appgprj_6a69a221ef1c8191b5e3a523cc671445",
    d1: "DB",
    r2: "AUDIO",
  });
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await access(new URL("../public/og.png", import.meta.url));
  await access(new URL("../public/favicon.svg", import.meta.url));
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
});

test("ships a complete role-gated admin center backed by durable APIs", async () => {
  const [adminPanel, adminApi, bootstrap, authPage] = await Promise.all([
    readFile(new URL("../app/admin-panel.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/admin-local-api.ts", import.meta.url), "utf8"),
    readFile(new URL("../db/bootstrap.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/auth/page.tsx", import.meta.url), "utf8"),
  ]);
  for (const label of ["کاربران", "تیم‌ها", "KPI و امتیاز", "اتوماسیون", "اتصال‌ها", "عملیات پردازش", "دقت مدل", "واژه‌نامه", "Issabel", "هوش مصنوعی", "امنیت و داده", "گزارش فعالیت"]) assert.match(adminPanel, new RegExp(label));
  for (const resource of ["members", "teams", "scorecards", "automations", "integrations", "processing-operations", "accuracy", "glossary", "issabel-settings", "ai-settings", "security", "audit-logs"]) assert.match(adminApi, new RegExp(`resource === "${resource}"`));
  for (const table of ["teams", "member_profiles", "scorecards", "automation_rules", "integrations", "ai_settings", "security_settings", "audit_logs", "processing_events", "extraction_evidence", "glossary_entries", "issabel_settings"]) assert.match(bootstrap, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`));
  assert.match(adminApi, /!admin && !manager/);
  assert.match(adminApi, /\["members", "security"\]/);
  assert.match(adminApi, /connector_backend_required/);
  assert.match(adminApi, /last_admin_protected/);
  assert.match(authPage, /className="admin-login-icon"/);
  assert.doesNotMatch(authPage, /admin-login-entry/);
});

test("ships operational call filters, follow-up buckets, detail controls and honest local capabilities", async () => {
  const [pilot, callQuery, localApi, callsRoute] = await Promise.all([
    readFile(new URL("../app/pilot-views.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/call-query.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/local-api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/v1/calls/route.ts", import.meta.url), "utf8"),
  ]);
  for (const filter of ["date_from", "date_to", "seller", "customer", "company", "phone", "city", "province", "product", "product_category", "outcome", "sales_stage", "lead_temperature", "followup_required", "followup_overdue", "min_score", "max_score", "sentiment", "risk_flag", "status", "direction", "min_duration", "max_duration", "source_filename", "has_error", "manually_corrected"]) assert.match(pilot, new RegExp(filter));
  for (const bucket of ["today", "overdue", "unscheduled", "done", "cancelled"]) assert.match(pilot, new RegExp(`"${bucket}"`));
  for (const feature of ["pilot-call-audio", "playbackRate", "speaker-roles", "transcript-segments", "شواهد و نقل‌قول‌ها", "خط زمانی پردازش"]) assert.match(pilot, new RegExp(feature));
  assert.ok(pilot.includes("تحلیل خام (فقط مدیر)"));
  assert.match(callQuery, /LIMIT \? OFFSET \?/);
  assert.match(callQuery, /ORDER BY \$\{sort\} \$\{order\}/);
  assert.match(callsRoute, /target\.search = new URL\(request\.url\)\.search/);
  assert.match(callsRoute, /seller_name, seller_email/);
  assert.match(callsRoute, /user\.displayName, user\.email/);
  assert.match(localApi, /pdf_export_requires_processing_backend/);
  assert.match(localApi, /excel_export_requires_processing_backend/);
  assert.match(localApi, /read_only_role/);
});

test("keeps D1 bootstrap, schema and additive migrations aligned", async () => {
  const [schema, bootstrap, migrationOne, migrationTwo] = await Promise.all([
    readFile(new URL("../db/schema.ts", import.meta.url), "utf8"),
    readFile(new URL("../db/bootstrap.ts", import.meta.url), "utf8"),
    readFile(new URL("../drizzle/0001_even_mastermind.sql", import.meta.url), "utf8"),
    readFile(new URL("../drizzle/0002_third_proudstar.sql", import.meta.url), "utf8"),
  ]);
  for (const table of ["processing_events", "extraction_evidence", "glossary_entries", "issabel_settings"]) {
    assert.match(schema, new RegExp(`"${table}"`));
    assert.match(bootstrap, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`));
    assert.match(migrationOne, new RegExp("CREATE TABLE `" + table + "`"));
  }
  for (const index of ["idx_calls_org_created", "idx_calls_org_status_created", "idx_calls_org_seller_created", "idx_calls_org_followup", "idx_tasks_org_status_due", "idx_processing_org_status_created", "idx_glossary_org_normalized"]) {
    assert.match(schema, new RegExp(index));
    assert.match(bootstrap, new RegExp(index));
    assert.match(migrationTwo, new RegExp(index));
  }
  const additiveUpgrade = bootstrap.indexOf('await ensureColumns(db, "calls"');
  assert.ok(additiveUpgrade > 0);
  assert.ok(bootstrap.indexOf("idx_calls_org_seller_created") > additiveUpgrade);
  assert.ok(bootstrap.indexOf("idx_calls_org_followup") > additiveUpgrade);
});

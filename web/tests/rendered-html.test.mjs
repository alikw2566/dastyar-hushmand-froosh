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
  for (const label of ["کاربران", "تیم‌ها", "KPI و امتیاز", "اتوماسیون", "اتصال‌ها", "هوش مصنوعی", "امنیت و داده", "گزارش فعالیت"]) assert.match(adminPanel, new RegExp(label));
  for (const resource of ["members", "teams", "scorecards", "automations", "integrations", "ai-settings", "security", "audit-logs"]) assert.match(adminApi, new RegExp(`resource === "${resource}"`));
  for (const table of ["teams", "member_profiles", "scorecards", "automation_rules", "integrations", "ai_settings", "security_settings", "audit_logs"]) assert.match(bootstrap, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`));
  assert.match(adminApi, /user\.role !== "مدیر"/);
  assert.match(adminApi, /last_admin_protected/);
  assert.match(authPage, /className="admin-login-icon"/);
  assert.doesNotMatch(authPage, /admin-login-entry/);
});

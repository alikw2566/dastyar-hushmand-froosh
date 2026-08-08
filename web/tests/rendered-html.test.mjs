import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const source = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("ships a gated RTL dashboard with no sample records", async () => {
  const [layout, page, dashboard] = await Promise.all([
    source("../app/layout.tsx"), source("../app/page.tsx"), source("../app/sales-dashboard.tsx"),
  ]);
  assert.match(layout, /<html lang="fa" dir="rtl"/i);
  assert.match(page, /redirect\("\/auth"\)/);
  for (const view of ["calls", "reviews", "customers", "tasks", "opportunities", "coaching", "reports", "search", "settings"]) assert.match(dashboard, new RegExp(`"${view}"`));
  assert.doesNotMatch(dashboard, /sample|demo data|codex-preview/i);
});

test("uses OIDC/FastAPI in server mode and a development-only local path", async () => {
  const [auth, localAuth, oidcConfig, proxy, hosting, packageJson] = await Promise.all([
    source("../app/auth/page.tsx"), source("../app/local-auth.ts"), source("../app/oidc-config.ts"), source("../app/api/v1/[...path]/route.ts"), source("../.openai/hosting.json"), source("../package.json"),
  ]);
  assert.match(auth, /oidcExternalIssuer/);
  assert.match(auth, /LocalAuthForm/);
  assert.match(localAuth, /process\.env\.NODE_ENV !== "production"/);
  assert.match(oidcConfig, /OIDC_ISSUER/);
  assert.match(proxy, /API_BASE_URL/);
  assert.match(proxy, /handleLocalApi/);
  assert.deepEqual(Object.keys(JSON.parse(hosting)).sort(), ["d1", "project_id", "r2"]);
  assert.match(packageJson, /drizzle-orm/);
  await access(new URL("../app/local-api.ts", import.meta.url));
  await access(new URL("../db/bootstrap.ts", import.meta.url));
});

test("exposes review workflow and immutable-version UI", async () => {
  const [queue, detail, dashboard] = await Promise.all([
    source("../app/review-queue.tsx"), source("../app/pilot-views.tsx"), source("../app/sales-dashboard.tsx"),
  ]);
  for (const action of ["assign", "approve", "reject", "request-changes", "publish"]) assert.match(queue, new RegExp(action));
  assert.match(queue, /\/api\/v1\/reviews/);
  assert.match(detail, /\/versions/);
  for (const format of ["export.txt", "export.html", "export.json", "export.pdf", "export.xlsx"]) assert.match(detail, new RegExp(format.replace(".", "\\.")));
  assert.match(dashboard, /ReviewQueue/);
});

test("keeps operational filters, follow-up buckets, protected audio and server reports", async () => {
  const [pilot, modules] = await Promise.all([source("../app/pilot-views.tsx"), source("../app/sales-modules.tsx")]);
  for (const filter of ["date_from", "date_to", "seller", "customer", "company", "phone", "city", "product", "outcome", "min_score", "max_score", "status"]) assert.match(pilot, new RegExp(filter));
  for (const bucket of ["today", "overdue", "unscheduled", "done", "cancelled"]) assert.match(pilot, new RegExp(`"${bucket}"`));
  assert.match(pilot, /pilot-call-audio/);
  assert.match(pilot, /speaker-roles/);
  assert.match(modules, /\/api\/v1\/reports\/team/);
});

test("ships production metadata and assets", async () => {
  const layout = await source("../app/layout.tsx");
  assert.match(layout, /og-redesign\.png/);
  await access(new URL("../public/og-redesign.png", import.meta.url));
  await access(new URL("../public/favicon.svg", import.meta.url));
});

test("does not expose the removed generic integrations feature", async () => {
  const [admin, localAdminApi, backend, models, localSchema, localBootstrap] = await Promise.all([
    source("../app/admin-panel.tsx"),
    source("../app/admin-local-api.ts"),
    source("../../backend/app/main.py"),
    source("../../backend/app/models.py"),
    source("../db/schema.ts"),
    source("../db/bootstrap.ts"),
  ]);
  assert.doesNotMatch(admin, /admin\/integrations|id: "integrations"|webhook\.send/);
  assert.doesNotMatch(localAdminApi, /resource === "integrations"|webhook\.send/);
  assert.doesNotMatch(backend, /api\/v1\/(?:admin\/)?integrations/);
  assert.doesNotMatch(models, /class Integration\b/);
  assert.doesNotMatch(localSchema, /sqliteTable\("integrations"/);
  assert.doesNotMatch(localBootstrap, /CREATE TABLE IF NOT EXISTS integrations/);
  assert.match(admin, /id: "issabel"/);
});

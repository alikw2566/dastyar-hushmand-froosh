export type CallListResult = {
  items: Record<string, unknown>[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  capabilities?: { excel_export: boolean };
};

const sortable: Record<string, string> = {
  created_at: "created_at",
  score: "score",
  duration_seconds: "duration_seconds",
  duration: "duration_seconds",
  customer_name: "customer_name",
  customer: "customer_name",
  seller_name: "seller_name",
  seller: "seller_name",
  status: "status",
  outcome: "outcome",
};

const exactFilters: Record<string, string> = {
  outcome: "outcome",
  sales_stage: "sales_stage",
  lead_temperature: "lead_temperature",
  sentiment: "sentiment",
  status: "status",
  direction: "direction",
};

const likeFilters: Record<string, string> = {
  seller: "COALESCE(seller_name, '') || ' ' || COALESCE(seller_email, '')",
  customer: "customer_name",
  company: "company_name",
  phone: "phone_number",
  city: "city",
  province: "province",
  product: "product_name",
  product_category: "product_category",
  source_filename: "original_file_name",
};

function positiveInt(value: string | null, fallback: number, maximum: number) {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? Math.min(parsed, maximum) : fallback;
}

function numeric(value: string | null) {
  if (value == null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export async function queryCalls(db: D1Database, organizationId: string, url: URL, sellerEmail?: string): Promise<CallListResult> {
  const params = url.searchParams;
  const where = ["organization_id = ?"];
  const bindings: unknown[] = [organizationId];
  if (sellerEmail) { where.push("seller_email = ?"); bindings.push(sellerEmail); }
  const q = params.get("q")?.trim();
  if (q) {
    where.push(`(customer_name LIKE ? OR company_name LIKE ? OR phone_number LIKE ? OR seller_name LIKE ? OR seller_email LIKE ? OR product_name LIKE ? OR original_file_name LIKE ?)`);
    for (let index = 0; index < 7; index += 1) bindings.push(`%${q}%`);
  }
  for (const [parameter, column] of Object.entries(exactFilters)) {
    const value = params.get(parameter)?.trim();
    if (value) { where.push(`${column} = ?`); bindings.push(value); }
  }
  for (const [parameter, expression] of Object.entries(likeFilters)) {
    const value = params.get(parameter)?.trim();
    if (value) { where.push(`${expression} LIKE ?`); bindings.push(`%${value}%`); }
  }
  const dateFrom = params.get("date_from");
  const dateTo = params.get("date_to");
  if (dateFrom) { where.push("created_at >= ?"); bindings.push(`${dateFrom}T00:00:00.000Z`); }
  if (dateTo) { where.push("created_at <= ?"); bindings.push(`${dateTo}T23:59:59.999Z`); }
  const minScore = numeric(params.get("min_score"));
  const maxScore = numeric(params.get("max_score"));
  const minDuration = numeric(params.get("min_duration"));
  const maxDuration = numeric(params.get("max_duration"));
  if (minScore != null) { where.push("score >= ?"); bindings.push(minScore); }
  if (maxScore != null) { where.push("score <= ?"); bindings.push(maxScore); }
  if (minDuration != null) { where.push("duration_seconds >= ?"); bindings.push(minDuration); }
  if (maxDuration != null) { where.push("duration_seconds <= ?"); bindings.push(maxDuration); }
  if (params.get("followup_required") === "true") where.push("followup_required = 1");
  if (params.get("followup_required") === "false") where.push("followup_required = 0");
  if (params.get("followup_overdue") === "true") where.push("followup_required = 1 AND followup_at IS NOT NULL AND followup_at < CURRENT_TIMESTAMP");
  if (params.get("has_error") === "true") where.push("(error_message IS NOT NULL OR status IN ('failed','quarantined'))");
  if (params.get("has_error") === "false") where.push("error_message IS NULL AND status NOT IN ('failed','quarantined')");
  if (params.get("manually_corrected") === "true") where.push("has_manual_correction = 1");
  if (params.get("manually_corrected") === "false") where.push("has_manual_correction = 0");
  if (params.get("risk_flag") === "true") where.push("risk_flags_json IS NOT NULL AND risk_flags_json NOT IN ('','[]')");
  if (params.get("risk_flag") === "false") where.push("(risk_flags_json IS NULL OR risk_flags_json IN ('','[]'))");

  const page = positiveInt(params.get("page"), 1, 1_000_000);
  const pageSize = positiveInt(params.get("page_size"), 25, 100);
  const sort = sortable[params.get("sort") ?? ""] ?? "created_at";
  const order = params.get("order") === "asc" ? "ASC" : "DESC";
  const clause = where.join(" AND ");
  const count = await db.prepare(`SELECT COUNT(*) AS value FROM calls WHERE ${clause}`).bind(...bindings).first<{ value: number }>();
  const total = Number(count?.value ?? 0);
  const rows = await db.prepare(`SELECT * FROM calls WHERE ${clause} ORDER BY ${sort} ${order}, id DESC LIMIT ? OFFSET ?`)
    .bind(...bindings, pageSize, (page - 1) * pageSize).all<Record<string, unknown>>();
  return {
    items: rows.results,
    total,
    page,
    page_size: pageSize,
    pages: Math.max(1, Math.ceil(total / pageSize)),
    capabilities: { excel_export: false },
  };
}

import { sql } from "drizzle-orm";
import { integer, real, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const organizations = sqliteTable("organizations", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  plan: text("plan", { enum: ["free", "team", "business", "enterprise"] }).notNull().default("free"),
  monthlyMinuteLimit: integer("monthly_minute_limit").notNull().default(120),
  retentionDays: integer("retention_days").notNull().default(30),
  automationMode: text("automation_mode", { enum: ["draft", "approval", "automatic"] }).notNull().default("approval"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const memberships = sqliteTable("memberships", {
  id: text("id").primaryKey(),
  organizationId: text("organization_id").notNull().references(() => organizations.id),
  email: text("email").notNull(),
  displayName: text("display_name").notNull(),
  role: text("role", { enum: ["admin", "supervisor", "seller"] }).notNull(),
  teamId: text("team_id"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (table) => [uniqueIndex("membership_org_email_idx").on(table.organizationId, table.email)]);

export const calls = sqliteTable("calls", {
  id: text("id").primaryKey(),
  organizationId: text("organization_id").notNull().references(() => organizations.id),
  externalId: text("external_id"),
  customerName: text("customer_name").notNull().default("در انتظار استخراج"),
  sellerName: text("seller_name").notNull().default("در انتظار تشخیص"),
  originalFileName: text("original_file_name").notNull(),
  objectKey: text("object_key").notNull(),
  mimeType: text("mime_type").notNull(),
  sizeBytes: integer("size_bytes").notNull(),
  source: text("source", { enum: ["upload", "api", "telephony"] }).notNull().default("upload"),
  status: text("status", { enum: ["received", "uploaded", "queued", "transcribing", "analyzing", "review_needed", "completed", "failed"] }).notNull().default("queued"),
  outcome: text("outcome", { enum: ["won", "lost", "follow_up", "unknown"] }).notNull().default("unknown"),
  outcomeConfirmed: integer("outcome_confirmed", { mode: "boolean" }).notNull().default(false),
  durationSeconds: real("duration_seconds"),
  score: real("score"),
  analysisVersion: text("analysis_version"),
  analysisJson: text("analysis_json", { mode: "json" }).$type<Record<string, unknown>>(),
  errorMessage: text("error_message"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (table) => [uniqueIndex("calls_org_external_idx").on(table.organizationId, table.externalId)]);

export const transcriptSegments = sqliteTable("transcript_segments", {
  id: text("id").primaryKey(),
  organizationId: text("organization_id").notNull(),
  callId: text("call_id").notNull().references(() => calls.id, { onDelete: "cascade" }),
  position: integer("position").notNull(),
  speakerLabel: text("speaker_label").notNull(),
  speakerRole: text("speaker_role", { enum: ["seller", "customer", "unknown"] }).notNull().default("unknown"),
  startSeconds: real("start_seconds"),
  endSeconds: real("end_seconds"),
  content: text("content").notNull(),
  editedBy: text("edited_by"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const tasks = sqliteTable("tasks", {
  id: text("id").primaryKey(),
  organizationId: text("organization_id").notNull(),
  callId: text("call_id").references(() => calls.id, { onDelete: "set null" }),
  customerName: text("customer_name").notNull(),
  title: text("title").notNull(),
  assigneeEmail: text("assignee_email"),
  priority: text("priority", { enum: ["low", "normal", "high", "critical"] }).notNull().default("normal"),
  status: text("status", { enum: ["open", "in_progress", "done", "cancelled"] }).notNull().default("open"),
  dueAt: text("due_at"),
  aiSuggested: integer("ai_suggested", { mode: "boolean" }).notNull().default(false),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const messageDrafts = sqliteTable("message_drafts", {
  id: text("id").primaryKey(),
  organizationId: text("organization_id").notNull(),
  callId: text("call_id").references(() => calls.id, { onDelete: "set null" }),
  channel: text("channel", { enum: ["sms", "whatsapp", "email"] }).notNull(),
  recipientMasked: text("recipient_masked"),
  subject: text("subject"),
  content: text("content").notNull(),
  status: text("status", { enum: ["draft", "pending_approval", "approved", "scheduled", "sent", "rejected", "failed"] }).notNull().default("pending_approval"),
  approvedBy: text("approved_by"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const integrations = sqliteTable("integrations", {
  id: text("id").primaryKey(),
  organizationId: text("organization_id").notNull(),
  kind: text("kind", { enum: ["telephony", "crm", "webhook", "sms", "email", "whatsapp", "api"] }).notNull(),
  name: text("name").notNull(),
  status: text("status", { enum: ["active", "inactive", "error"] }).notNull().default("inactive"),
  encryptedConfig: text("encrypted_config"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const scorecardVersions = sqliteTable("scorecard_versions", {
  id: text("id").primaryKey(),
  organizationId: text("organization_id").notNull(),
  version: integer("version").notNull(),
  name: text("name").notNull(),
  criteriaJson: text("criteria_json", { mode: "json" }).$type<Array<{ key: string; label: string; weight: number }>>().notNull(),
  active: integer("active", { mode: "boolean" }).notNull().default(false),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const auditLogs = sqliteTable("audit_logs", {
  id: text("id").primaryKey(),
  organizationId: text("organization_id").notNull(),
  actorEmail: text("actor_email").notNull(),
  action: text("action").notNull(),
  entityType: text("entity_type").notNull(),
  entityId: text("entity_id"),
  metadataJson: text("metadata_json", { mode: "json" }).$type<Record<string, unknown>>(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

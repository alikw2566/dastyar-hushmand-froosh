import { env } from "cloudflare:workers";
import { cookies } from "next/headers";
import { ensureCoreSchema } from "../db/bootstrap";

const COOKIE_NAME = "mokalemeban_local_session";
const SESSION_DAYS = 14;
type Bindings = { DB: D1Database };

export type LocalUser = {
  id: string;
  email: string;
  displayName: string;
  fullName: string;
  role: string;
  organizationId: string;
  organizationName: string;
};

function db() { return (env as unknown as Bindings).DB; }
function bytesToHex(bytes: Uint8Array) { return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(""); }
function randomToken(length = 32) { const bytes = crypto.getRandomValues(new Uint8Array(length)); return bytesToHex(bytes); }

async function sha256(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return bytesToHex(new Uint8Array(digest));
}

async function derivePassword(password: string, saltHex: string) {
  const salt = new Uint8Array(saltHex.match(/.{1,2}/g)?.map((item) => Number.parseInt(item, 16)) ?? []);
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: 210_000 }, key, 256);
  return bytesToHex(new Uint8Array(bits));
}

async function setSession(userId: string) {
  const token = randomToken();
  const tokenHash = await sha256(token);
  const expires = new Date(Date.now() + SESSION_DAYS * 86400_000);
  await db().prepare("INSERT INTO local_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)").bind(tokenHash, userId, expires.toISOString()).run();
  (await cookies()).set(COOKIE_NAME, token, { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", expires });
}

export function localAuthAvailable() { return !process.env.OIDC_ISSUER && process.env.NODE_ENV !== "production"; }

export async function registerLocalAccount(input: { fullName: string; email: string; password: string; organizationName: string }) {
  if (!localAuthAvailable()) throw new Error("local_auth_disabled");
  const database = db(); await ensureCoreSchema(database);
  const email = input.email.trim().toLowerCase();
  const fullName = input.fullName.trim();
  const organizationName = input.organizationName.trim();
  if (!/^\S+@\S+\.\S+$/.test(email)) throw new Error("invalid_email");
  if (fullName.length < 2 || organizationName.length < 2) throw new Error("invalid_profile");
  if (input.password.length < 10 || !/\d/.test(input.password)) throw new Error("weak_password");
  const exists = await database.prepare("SELECT id FROM local_users WHERE email = ?").bind(email).first();
  if (exists) throw new Error("email_exists");
  const organizationId = `org_${crypto.randomUUID()}`;
  const userId = `usr_${crypto.randomUUID()}`;
  const salt = randomToken(16);
  const passwordHash = await derivePassword(input.password, salt);
  await database.batch([
    database.prepare("INSERT INTO organizations (id, name, plan, monthly_minute_limit, retention_days, automation_mode) VALUES (?, ?, 'free', 120, 30, 'approval')").bind(organizationId, organizationName),
    database.prepare("INSERT INTO local_users (id, organization_id, email, full_name, password_hash, password_salt, role) VALUES (?, ?, ?, ?, ?, ?, 'admin')").bind(userId, organizationId, email, fullName, passwordHash, salt),
    database.prepare("INSERT INTO member_profiles (user_id, organization_id, active) VALUES (?, ?, 1)").bind(userId, organizationId),
    database.prepare("INSERT INTO ai_settings (organization_id) VALUES (?)").bind(organizationId),
    database.prepare("INSERT INTO security_settings (organization_id) VALUES (?)").bind(organizationId),
    database.prepare("INSERT INTO audit_logs (id, organization_id, actor_email, action, entity_type, entity_id, details_json) VALUES (?, ?, ?, 'organization.created', 'organization', ?, ?)").bind(`audit_${crypto.randomUUID()}`, organizationId, email, organizationId, JSON.stringify({ name: organizationName })),
  ]);
  await setSession(userId);
}

export async function loginLocalAccount(emailInput: string, password: string) {
  if (!localAuthAvailable()) throw new Error("local_auth_disabled");
  const database = db(); await ensureCoreSchema(database);
  const row = await database.prepare(`SELECT u.id, u.password_hash, u.password_salt FROM local_users u
    LEFT JOIN member_profiles p ON p.user_id = u.id WHERE u.email = ? AND COALESCE(p.active, 1) = 1`).bind(emailInput.trim().toLowerCase()).first<{ id: string; password_hash: string; password_salt: string }>();
  if (!row || await derivePassword(password, row.password_salt) !== row.password_hash) throw new Error("invalid_credentials");
  await database.prepare("UPDATE member_profiles SET last_login_at = ? WHERE user_id = ?").bind(new Date().toISOString(), row.id).run();
  await setSession(row.id);
}

export async function getLocalUser(): Promise<LocalUser | null> {
  if (!localAuthAvailable()) return null;
  const token = (await cookies()).get(COOKIE_NAME)?.value;
  if (!token) return null;
  const database = db(); await ensureCoreSchema(database);
  const tokenHash = await sha256(token);
  const row = await database.prepare(`SELECT u.id, u.email, u.full_name, u.role, u.organization_id, o.name AS organization_name
    FROM local_sessions s JOIN local_users u ON u.id = s.user_id JOIN organizations o ON o.id = u.organization_id
    LEFT JOIN member_profiles p ON p.user_id = u.id
    WHERE s.token_hash = ? AND s.expires_at > ? AND COALESCE(p.active, 1) = 1`).bind(tokenHash, new Date().toISOString()).first<{ id: string; email: string; full_name: string; role: string; organization_id: string; organization_name: string }>();
  if (!row) return null;
  const role = row.role === "admin" ? "مدیر" : row.role === "supervisor" ? "سرپرست" : "فروشنده";
  return { id: row.id, email: row.email, displayName: row.full_name, fullName: row.full_name, role, organizationId: row.organization_id, organizationName: row.organization_name };
}

export async function createManagedLocalUser(actor: LocalUser, input: { fullName: string; email: string; password: string; role: string; teamId?: string | null }) {
  if (!localAuthAvailable() || actor.role !== "مدیر") throw new Error("insufficient_role");
  const database = db(); await ensureCoreSchema(database);
  const email = input.email.trim().toLowerCase(); const fullName = input.fullName.trim();
  if (!/^\S+@\S+\.\S+$/.test(email)) throw new Error("invalid_email");
  if (fullName.length < 2) throw new Error("invalid_profile");
  if (input.password.length < 10 || !/\d/.test(input.password)) throw new Error("weak_password");
  if (!["admin", "supervisor", "seller"].includes(input.role)) throw new Error("invalid_role");
  if (await database.prepare("SELECT id FROM local_users WHERE email = ?").bind(email).first()) throw new Error("email_exists");
  if (input.teamId && !await database.prepare("SELECT id FROM teams WHERE id = ? AND organization_id = ?").bind(input.teamId, actor.organizationId).first()) throw new Error("team_not_found");
  const userId = `usr_${crypto.randomUUID()}`; const salt = randomToken(16); const passwordHash = await derivePassword(input.password, salt);
  await database.batch([
    database.prepare("INSERT INTO local_users (id, organization_id, email, full_name, password_hash, password_salt, role) VALUES (?, ?, ?, ?, ?, ?, ?)").bind(userId, actor.organizationId, email, fullName, passwordHash, salt, input.role),
    database.prepare("INSERT INTO member_profiles (user_id, organization_id, team_id, active) VALUES (?, ?, ?, 1)").bind(userId, actor.organizationId, input.teamId ?? null),
    database.prepare("INSERT INTO audit_logs (id, organization_id, actor_email, action, entity_type, entity_id, details_json) VALUES (?, ?, ?, 'member.created', 'member', ?, ?)").bind(`audit_${crypto.randomUUID()}`, actor.organizationId, actor.email, userId, JSON.stringify({ email, role: input.role })),
  ]);
  return { id: userId, email, full_name: fullName, role: input.role, active: 1, team_id: input.teamId ?? null };
}

export async function logoutLocalAccount() {
  const jar = await cookies(); const token = jar.get(COOKIE_NAME)?.value;
  if (token && localAuthAvailable()) { const database = db(); await ensureCoreSchema(database); await database.prepare("DELETE FROM local_sessions WHERE token_hash = ?").bind(await sha256(token)).run(); }
  jar.delete(COOKIE_NAME);
}

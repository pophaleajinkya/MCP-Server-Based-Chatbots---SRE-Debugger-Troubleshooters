/**
 * Server-side PingFederate OAuth 2.0 PKCE utilities.
 * Only used in API routes and middleware — never imported by client components.
 */

import { cookies } from "next/headers";
import { loggedFetch } from "@/lib/logger";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface AuthUser {
  sub: string;
  name: string;
  email: string;
  loginId: string;
  win_nbr?: string;
  /** Derived from employeeType (H/S) or wm-Type (V→H, A→S), else "standard" */
  user_type: string;
  /** Whether the user belongs to the configured admin AD group */
  isAdmin: boolean;
}

export interface AuthSession extends AuthUser {
  access_token: string;
  /** Unix timestamp (seconds) when the access_token expires */
  expires_at: number;
}

// ─── Cookie names ─────────────────────────────────────────────────────────────

export const SESSION_COOKIE = "sre_ai_session";
export const PKCE_STATE_COOKIE = "sre_ai_pkce";

// ─── PingFed config from env ──────────────────────────────────────────────────

export function getPingFedConfig() {
  const clientId = process.env.PINGFED_CLIENT_ID;
  const clientSecret = process.env.PINGFED_CLIENT_SECRET;
  const redirectUri = process.env.PINGFED_REDIRECT_URI;
  const authUrl = process.env.PINGFED_AUTH_URL;
  const tokenUrl = process.env.PINGFED_TOKEN_URL;
  const userInfoUrl = process.env.PINGFED_USERINFO_URL;
  const logoutUrl = process.env.PINGFED_LOGOUT_URL ?? "";
  const scope = process.env.PINGFED_SCOPE ?? "openid profile email";

  if (!clientId || !clientSecret || !redirectUri || !authUrl || !tokenUrl || !userInfoUrl) {
    throw new Error(
      "PingFed configuration is incomplete. Set PINGFED_CLIENT_ID, PINGFED_CLIENT_SECRET, " +
        "PINGFED_REDIRECT_URI, PINGFED_AUTH_URL, PINGFED_TOKEN_URL, PINGFED_USERINFO_URL in .env.local"
    );
  }

  return { clientId, clientSecret, redirectUri, authUrl, tokenUrl, userInfoUrl, logoutUrl, scope };
}

// ─── PKCE helpers ────────────────────────────────────────────────────────────

/** Returns a cryptographically random base64url string of `byteLength` bytes. */
function randomBase64url(byteLength: number): string {
  const bytes = crypto.getRandomValues(new Uint8Array(byteLength));
  return uint8ToBase64url(bytes);
}

function uint8ToBase64url(bytes: Uint8Array): string {
  let str = "";
  bytes.forEach((b) => (str += String.fromCharCode(b)));
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

export async function generatePKCE(): Promise<{ verifier: string; challenge: string; state: string }> {
  const verifier = randomBase64url(32);
  const state = randomBase64url(16);

  // SHA-256 of the verifier → base64url
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  const challenge = uint8ToBase64url(new Uint8Array(digest));

  return { verifier, challenge, state };
}

// ─── Session cookie ───────────────────────────────────────────────────────────

const CHUNK_SIZE = 3000; // Safe limit below 4096 bytes

export async function setSessionCookie(session: AuthSession): Promise<void> {
  // Cookie lives exactly as long as the access_token is valid
  const maxAge = Math.max(session.expires_at - Math.floor(Date.now() / 1000), 60);
  // Use secure+sameSite=none on stage/prod (HTTPS) so the cookie survives the
  // cross-site OAuth redirect chain (PingFed → app → middleware → callback).
  // On local dev/test (HTTP) use lax so localhost works without HTTPS.
  const isLocalDev = process.env.NODE_ENV === "development" || process.env.NODE_ENV === "test";
  const cookieStore = await cookies();
  const options = {
    httpOnly: true,
    secure: !isLocalDev,
    sameSite: (isLocalDev ? "lax" : "none") as "lax" | "none",
    maxAge,
    path: "/",
  };

  const raw = JSON.stringify(session);

  // Fallback: If the payload is too large, chunk it.
  if (raw.length > 3500) {
    const totalChunks = Math.ceil(raw.length / CHUNK_SIZE);
    cookieStore.set(SESSION_COOKIE, JSON.stringify({ chunks: totalChunks }), options);
    
    for (let i = 0; i < totalChunks; i++) {
      const chunk = raw.substring(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);
      cookieStore.set(`${SESSION_COOKIE}.${i}`, chunk, options);
    }
  } else {
    // Normal size: store in a single cookie.
    cookieStore.set(SESSION_COOKIE, raw, options);
    // Clean up any lingering chunks if the previous session was large
    for (let i = 0; i < 5; i++) {
      cookieStore.delete(`${SESSION_COOKIE}.${i}`);
    }
  }
}

export async function getSessionCookie(): Promise<AuthSession | null> {
  try {
    const cookieStore = await cookies();
    const raw = cookieStore.get(SESSION_COOKIE)?.value;
    if (!raw) return null;
    
    let parsed: any;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return null;
    }

    // Check if it's a chunked session metadata marker
    if (parsed && typeof parsed === "object" && "chunks" in parsed) {
      const { chunks } = parsed;
      let fullRaw = "";
      for (let i = 0; i < chunks; i++) {
        const chunk = cookieStore.get(`${SESSION_COOKIE}.${i}`)?.value;
        if (!chunk) return null; // Missing chunk, session is invalid
        fullRaw += chunk;
      }
      return JSON.parse(fullRaw) as AuthSession;
    }

    // Normal, non-chunked session
    return parsed as AuthSession;
  } catch {
    return null;
  }
}

export async function clearSessionCookie(): Promise<void> {
  const isLocalDev = process.env.NODE_ENV === "development" || process.env.NODE_ENV === "test";
  const expireOpts = {
    httpOnly: true,
    secure: !isLocalDev,
    sameSite: (isLocalDev ? "lax" : "none") as "lax" | "none",
    maxAge: 0,
    path: "/",
  };

  const cookieStore = await cookies();
  const metaRaw = cookieStore.get(SESSION_COOKIE)?.value;

  // Expire the main session cookie (maxAge: 0 instructs the browser to delete it)
  cookieStore.set(SESSION_COOKIE, "", expireOpts);

  if (metaRaw) {
    try {
      const parsed = JSON.parse(metaRaw);
      if (parsed && typeof parsed === "object" && "chunks" in parsed) {
        for (let i = 0; i < parsed.chunks; i++) {
          cookieStore.set(`${SESSION_COOKIE}.${i}`, "", expireOpts);
        }
      }
    } catch {}
  }

  // Aggressively expire a few chunks just in case metadata was corrupt
  for (let i = 0; i < 5; i++) {
    cookieStore.set(`${SESSION_COOKIE}.${i}`, "", expireOpts);
  }
}

// ─── PKCE state cookie ────────────────────────────────────────────────────────

export async function setPKCECookie(state: string, verifier: string, returnTo?: string): Promise<void> {
  // Same secure+sameSite=none logic as session cookie — must survive the
  // cross-site PingFed redirect back to the app on stage/prod.
  const isLocalDev = process.env.NODE_ENV === "development" || process.env.NODE_ENV === "test";
  const cookieStore = await cookies();
  cookieStore.set(PKCE_STATE_COOKIE, JSON.stringify({ state, verifier, ...(returnTo && { returnTo }) }), {
    httpOnly: true,
    secure: !isLocalDev,
    sameSite: (isLocalDev ? "lax" : "none") as "lax" | "none",
    maxAge: 300, // 5 min — only needed during login flow
    path: "/",
  });
}

export async function consumePKCECookie(
  expectedState: string
): Promise<{ verifier: string; returnTo?: string } | null> {
  try {
    const cookieStore = await cookies();
    const raw = cookieStore.get(PKCE_STATE_COOKIE)?.value;
    if (!raw) return null;
    const { state, verifier, returnTo } = JSON.parse(raw) as {
      state: string;
      verifier: string;
      returnTo?: string;
    };
    cookieStore.delete(PKCE_STATE_COOKIE);
    if (state !== expectedState) return null;
    return { verifier, ...(returnTo !== undefined && { returnTo }) };
  } catch {
    return null;
  }
}

// ─── Token exchange ───────────────────────────────────────────────────────────

export async function exchangeCodeForTokens(
  code: string,
  codeVerifier: string
): Promise<{ access_token: string; id_token?: string; expires_in?: number }> {
  const cfg = getPingFedConfig();

  const params = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: cfg.redirectUri,
    code_verifier: codeVerifier,
    client_id: cfg.clientId,
    client_secret: cfg.clientSecret,
  });

  const res = await loggedFetch(cfg.tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: params.toString(),
    ui: "-",   // user not yet authenticated at token-exchange time
    tag: "auth-server.ts",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Token exchange failed (${res.status}): ${text}`);
  }

  return res.json();
}

// ─── UserInfo ─────────────────────────────────────────────────────────────────

export async function fetchUserInfo(accessToken: string): Promise<Record<string, unknown>> {
  const cfg = getPingFedConfig();

  const res = await loggedFetch(cfg.userInfoUrl, {
    method: "GET",
    headers: { Authorization: `Bearer ${accessToken}` },
    ui: "-",   // loginId not yet resolved — this call is what resolves it
    tag: "auth-server.ts",
  });

  if (!res.ok) {
    throw new Error(`UserInfo request failed (${res.status})`);
  }

  return res.json();
}

// ─── LLM Gateway headers ──────────────────────────────────────────────────────

/**
 * Builds the mandatory LLM Gateway headers from the current session.
 * Accepts an optional request object to extract client IP and user-agent.
 *
 * Centralised here so every API route sends the same headers — not just
 * the chat/stream route.
 */
export function buildLLMGatewayHeaders(
  session: AuthSession | null,
  req?: { headers: { get(name: string): string | null } }
): Record<string, string> {
  if (!session) return {};

  const headers: Record<string, string> = {};

  if (session.user_type)    headers["wm_llm_gw.user_type"] = session.user_type;
  if (session.loginId)      headers["wm_llm_gw.user_name"] = session.loginId;
  if (session.loginId)      headers["loginId"]              = session.loginId;
  if (session.access_token) headers["Authorization"]        = `Bearer ${session.access_token}`;

  if (req) {
    const ip =
      req.headers.get("x-forwarded-for")?.split(",")[0].trim() ??
      req.headers.get("x-real-ip") ??
      undefined;
    if (ip) headers["wm_llm_gw.user_ip"] = ip;
    const ua = req.headers.get("user-agent");
    if (ua)  headers["wm_llm_gw.user_agent"] = ua;
  }

  return headers;
}

// ─── user_type extraction ─────────────────────────────────────────────────────

/**
 * LLM Gateway-compliant user type values.
 * See: https://dx.walmart.com/elementgenai/documentation/confluence/Access-Using-REST-APIs--Legacy--2720898364
 */
export type LLMGatewayUserType =
  | "ASSOCIATE"
  | "RETAIL_CUSTOMER"
  | "VENDOR"
  | "TECH_DEVELOPMENT"
  | "NO_END_USER";

/**
 * Derives LLM Gateway-compliant user_type from PingFed token claims.
 *
 * Hierarchical check (mirrors maof-ui logic):
 *   1. employeeType field  → "S" (Salaried) → ASSOCIATE, "H" (Hourly) → ASSOCIATE
 *   2. wm-Type field       → "A" (Associate) → ASSOCIATE, "V" (Vendor) → VENDOR
 *   3. Existing user_type  → pass-through if already set
 *   4. Fallback            → ASSOCIATE (internal tool — all users are Walmart associates)
 */
export function extractUserType(claims: Record<string, unknown>): LLMGatewayUserType {
  // LEVEL 1: Check employeeType field (case-insensitive key lookup)
  const employeeType =
    (claims["employeeType"] as string | undefined) ??
    (claims["employeetype"] as string | undefined);
  if (employeeType) {
    const type = employeeType.toString().toUpperCase();
    if (type.includes("S")) return "ASSOCIATE"; // Salaried → Associate
    if (type.includes("H")) return "ASSOCIATE"; // Hourly → Associate (still a Walmart employee)
  }

  // LEVEL 2: Check wm-Type field (Walmart-specific claim, case-insensitive key fallback)
  let wmType =
    (claims["wm-Type"] as string | undefined) ??
    (claims["wm-type"] as string | undefined);
  if (!wmType) {
    const key = Object.keys(claims).find((k) => k.toLowerCase() === "wm-type");
    if (key) wmType = claims[key] as string;
  }
  if (wmType) {
    const type = wmType.toString().toUpperCase();
    if (type.includes("A")) return "ASSOCIATE"; // Associate
    if (type.includes("V")) return "VENDOR";    // Vendor
  }

  // LEVEL 3: Check if user_type is already a valid LLM Gateway value
  const existing = claims["user_type"] as string | undefined;
  if (existing) {
    const upper = existing.toUpperCase();
    if (["ASSOCIATE", "RETAIL_CUSTOMER", "VENDOR", "TECH_DEVELOPMENT", "NO_END_USER"].includes(upper)) {
      return upper as LLMGatewayUserType;
    }
  }

  // LEVEL 4: Default — this is an internal SRE tool, all users are Walmart associates
  return "ASSOCIATE";
}

/**
 * Extracts AD group names from PingFed claims.
 * PingFed may return groups under "memberOf", "groups", or "group" — and
 * the value can be a string array or a single comma-separated string.
 */
function extractGroups(claims: Record<string, unknown>): string[] {
  const raw =
    claims["memberOf"] ?? claims["groups"] ?? claims["group"] ??
    claims["MemberOf"] ?? claims["Groups"] ?? claims["Group"];
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.map(String);
  if (typeof raw === "string") return raw.split(",").map((g) => g.trim()).filter(Boolean);
  return [];
}

/** Maps a raw PingFed userinfo response to our AuthUser shape. */
export function mapUserInfo(
  claims: Record<string, unknown>,
  accessToken: string,
  /** Seconds until the access_token expires (from the token response). Defaults to 3h. */
  expiresIn = 3 * 60 * 60
): AuthSession {
  // Extract groups to check for admin access, but do not store the array in the cookie
  // to avoid overflowing the 4KB limit.
  const groups = extractGroups(claims);
  const adminGroup = process.env.ADMIN_AD_GROUP || "INTLSRE";
  
  // Lab users get automatic admin access for testing
  const email = String(claims["email"] ?? "");
  const isLabUser = email.toLowerCase().endsWith("@lab.wal-mart.com");
  const isAdmin = isLabUser || groups.includes(adminGroup);

  return {
    sub: String(claims["sub"] ?? ""),
    name: String(claims["name"] ?? claims["loginId"] ?? ""),
    email,
    loginId: String(claims["loginId"] ?? claims["sub"] ?? ""),
    win_nbr: claims["win_nbr"] ? String(claims["win_nbr"]) : undefined,
    user_type: extractUserType(claims),
    isAdmin,
    access_token: accessToken,
    expires_at: Math.floor(Date.now() / 1000) + expiresIn,
  };
}

/**
 * Checks whether the given session user is an admin.
 */
export function isAdminUser(session: AuthSession): boolean {
  return session.isAdmin === true;
}

"use server";

import { headers } from "next/headers";
import { getSessionCookie, type AuthSession } from "@/lib/auth-server";

/**
 * Build the user-context object that the openclaw api-layer (and from there
 * the openclaw plugin + super-agent) expects.
 *
 * Kept in sync with `src/lib/a2a-client.ts`'s `UserContext` interface — both
 * paths carry the same identity to super-agent, just one hop longer for the
 * monitor loop. openclaw honors every field listed below; see
 * `openclaw/api/src/clients/openclawClient.ts::mergeUserCtxHeaders`.
 *
 * `timezone` and `currentEpochMs` are optional — when the caller (a client
 * component) knows them they should be forwarded so super-agent can anchor
 * relative time expressions; server actions can't read them from the browser
 * directly so we accept them as explicit arguments.
 */
interface BuiltUserCtx {
  userId?: string;
  userName?: string;
  userType: string;
  loginId?: string;
  accessToken?: string;
  userAgent?: string;
  userIp?: string;
  timezone?: string;
  currentEpochMs?: number;
}

async function buildUserCtx(
  session: AuthSession | null,
  extras?: { timezone?: string; currentEpochMs?: number },
): Promise<BuiltUserCtx | null> {
  if (!session) return null;
  const headersList = await headers();
  const ip =
    headersList.get("x-forwarded-for")?.split(",")[0].trim() ??
    headersList.get("x-real-ip") ??
    undefined;
  const ua = headersList.get("user-agent") ?? undefined;
  const ctx: BuiltUserCtx = {
    userId: session.loginId,
    userName: session.name,
    // All sre-ai-ui users are Walmart associates by construction (PingFed
    // `extractUserType` already maps to one of the 5 allowed gateway values);
    // this fallback only fires if `user_type` was lost somehow, and ASSOCIATE
    // is the safest value the LLM gateway will accept.
    userType: session.user_type || "ASSOCIATE",
    loginId: session.loginId,
    accessToken: session.access_token,
  };
  if (ua) ctx.userAgent = ua;
  if (ip) ctx.userIp = ip;
  if (extras?.timezone) ctx.timezone = extras.timezone;
  if (extras?.currentEpochMs) ctx.currentEpochMs = extras.currentEpochMs;
  return ctx;
}

function getBaseUrl(): string {
  return process.env.SRE_AI_WORKERS || "http://localhost:8080";
}

export async function scheduleAlertRetry(
  alertId: string,
  conversationId: string,
  delayMinutes: number,
  maxInvocations: number,
  customPrompt: string | null = null,
  extras?: { timezone?: string; currentEpochMs?: number },
) {
  const session = await getSessionCookie();
  const userCtx = await buildUserCtx(session, extras);

  const payload: Record<string, unknown> = {
    conversation_id: conversationId,
    delay_minutes: delayMinutes,
    max_invocations: maxInvocations,
    user_ctx: userCtx,
  };
  if (customPrompt) payload.custom_prompt = customPrompt;

  const response = await fetch(`${getBaseUrl()}/api/alerts/${alertId}/schedule`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    return { error: err.detail || "Failed to schedule retry" };
  }
  return { success: true, data: await response.json() };
}

export async function getScheduledAlerts(conversationId: string) {
  try {
    const response = await fetch(
      `${getBaseUrl()}/api/sessions/${conversationId}/alerts`,
      { method: "GET" },
    );
    if (!response.ok) return { data: {} };
    const res = await response.json();
    return { data: res.data || {} };
  } catch (error) {
    console.error("Failed to fetch scheduled alerts:", error);
    return { data: {} };
  }
}

export async function getActiveMonitors() {
  try {
    const response = await fetch(`${getBaseUrl()}/api/sessions/active-monitors`, {
      method: "GET",
    });
    if (!response.ok) return { data: [] };
    const res = await response.json();
    return { data: res.data || [] };
  } catch (error) {
    console.error("Failed to fetch active monitors:", error);
    return { data: [] };
  }
}

export async function stopAlertRetry(alertId: string, conversationId: string) {
  const response = await fetch(
    `${getBaseUrl()}/api/alerts/${alertId}/schedule?conversation_id=${conversationId}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    return { error: err.detail || "Failed to stop retry" };
  }
  return { success: true };
}

async function postControl(
  path: "pause" | "resume" | "run-now",
  alertId: string,
  conversationId: string,
  extras?: { timezone?: string; currentEpochMs?: number },
): Promise<{ success: true } | { error: string }> {
  const session = await getSessionCookie();
  const userCtx = await buildUserCtx(session, extras);
  const response = await fetch(`${getBaseUrl()}/api/alerts/${alertId}/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // The api-layer's ScheduleControlRequest treats delay_minutes /
    // max_invocations as optional — we no longer send dummy values here
    // because run-now reads them from Redis state, and pause/resume ignore
    // them entirely. See openclaw/api/src/schemas/alerts.ts.
    body: JSON.stringify({
      conversation_id: conversationId,
      user_ctx: userCtx,
    }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    return { error: err.detail || `Failed to ${path} retry` };
  }
  return { success: true };
}

export async function pauseAlertRetry(alertId: string, conversationId: string) {
  return postControl("pause", alertId, conversationId);
}

export async function resumeAlertRetry(
  alertId: string,
  conversationId: string,
  extras?: { timezone?: string; currentEpochMs?: number },
) {
  return postControl("resume", alertId, conversationId, extras);
}

export async function runNowAlertRetry(
  alertId: string,
  conversationId: string,
  extras?: { timezone?: string; currentEpochMs?: number },
) {
  return postControl("run-now", alertId, conversationId, extras);
}

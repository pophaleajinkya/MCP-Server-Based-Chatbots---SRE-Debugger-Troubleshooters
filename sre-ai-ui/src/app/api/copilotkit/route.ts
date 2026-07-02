import { type NextRequest } from "next/server";
import {
  CopilotRuntime,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { A2AAgent, abortRun } from "@/lib/a2a-copilotkit-adapter";
import { getSessionCookie } from "@/lib/auth-server";
import type { UserContext } from "@/lib/a2a-client";

/**
 * POST /api/copilotkit
 *
 * CopilotKit AG-UI runtime endpoint.
 * Reads agentId + sessionId from URL query params so the agent can route
 * to the correct A2A backend and maintain Redis session continuity.
 *
 * Frontend sets: <CopilotKit runtimeUrl="/api/copilotkit" headers={{ "x-agent-id": "...", "x-session-id": "..." }} />
 */
export const POST = async (req: NextRequest) => {
  // ── agent/stop fast-path ───────────────────────────────────────────────────
  // CopilotKit sends {"method":"agent/stop","params":{"agentId":"...","threadId":"..."}}
  // as a *separate* HTTP POST.  We intercept it here so we can abort the
  // in-flight fetch inside A2AAgent.run() via the module-level run registry.
  // Without this, the stop request creates a brand-new A2AAgent instance that
  // has no knowledge of the running AbortController.
  let body: Record<string, unknown> | null = null;
  try {
    body = await req.clone().json();
  } catch { /* not JSON — fall through */ }

  if (body?.method === "agent/stop") {
    const threadId = (body.params as Record<string, string> | undefined)?.threadId;
    if (threadId) abortRun(threadId);
    return new Response(JSON.stringify({ success: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Read agentId + sessionId from headers (not URL params) so the runtimeUrl
  // stays clean and ProxiedCopilotRuntimeAgent can build /agent/:id/stop/:threadId correctly.
  const agentId        = req.headers.get("x-agent-id")        ?? undefined;
  const sessionId      = req.headers.get("x-session-id")      ?? undefined;
  const timezone       = req.headers.get("x-user-timezone")   ?? undefined;
  const epochMsRaw     = req.headers.get("x-current-epoch-ms");
  const currentEpochMs = epochMsRaw ? Number(epochMsRaw) : undefined;

  // Build user context — two reliable sources in priority order:
  //   1. Next.js middleware headers: x-user-login-id / x-user-name (set on EVERY
  //      authenticated request by middleware.ts — most reliable source)
  //   2. sre_ai_session cookie (also valid but may miss edge-cases like server restarts)
  // Using both prevents sessions being stored under A2A_USER_* (anonymous) keys.
  const session = await getSessionCookie();
  const loginId =
    session?.loginId ||
    req.headers.get("x-user-login-id") ||
    "";
  const userName =
    session?.name ||
    req.headers.get("x-user-name") ||
    loginId.split("@")[0];

  const userCtx: UserContext | undefined = loginId
    ? {
        userId: loginId,
        userName: userName,
        userType: session?.user_type ?? "",
        loginId: loginId,
        accessToken: session?.access_token,
        userAgent: req.headers.get("user-agent") ?? undefined,
        userIp:
          req.headers.get("x-forwarded-for")?.split(",")[0].trim() ??
          req.headers.get("x-real-ip") ??
          undefined,
        timezone,
        currentEpochMs,
      }
    : undefined;

  // A2AAgent implements AbstractAgent — passes the ag-ui Observable event stream
  // directly to CopilotKit runtime without needing an LLM service adapter.
  const agent = new A2AAgent({ agentId, sessionId, userCtx });

  const runtime = new CopilotRuntime({ agents: { default: agent } as any });

  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    endpoint: "/api/copilotkit",
  });

  return handleRequest(req);
};

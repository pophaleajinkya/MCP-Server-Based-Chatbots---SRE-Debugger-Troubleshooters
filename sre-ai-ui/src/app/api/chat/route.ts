import { NextRequest, NextResponse } from "next/server";
import { sendA2AQuery, extractTaskText, type UserContext } from "@/lib/a2a-client";
import { loadAgents } from "@/lib/agents";
import { getSessionCookie } from "@/lib/auth-server";
import { createLogger } from "@/lib/logger";
const log = createLogger('api/chat/route.ts');

export async function POST(req: NextRequest) {
  let agentId: string | undefined;
  let agentUrl: string | undefined;

  try {
    const body = await req.json();
    const { query, sessionId, agentId: reqAgentId } = body as {
      query?: string;
      sessionId?: string;
      agentId?: string;
    };

    agentId = reqAgentId;

    if (!query || typeof query !== "string" || query.trim().length === 0) {
      return NextResponse.json(
        { error: "query is required and must be a non-empty string" },
        { status: 400 }
      );
    }

    if (query.length > 4000) {
      return NextResponse.json(
        { error: "query exceeds maximum length of 4000 characters" },
        { status: 400 }
      );
    }

    // Resolve agent
    const agents = loadAgents();
    const agent = agentId
      ? (agents.find((a) => a.id === agentId) ?? agents[0])
      : agents[0];

    if (!agent) {
      return NextResponse.json(
        { error: "No agents configured. Set ADK_AGENTS in your .env.local" },
        { status: 503 }
      );
    }

    agentUrl = agent.url;

    // Build user context from session cookie
    const session = await getSessionCookie();
    const userCtx: UserContext | undefined = session
      ? {
          userId: session.loginId,
          userName: session.name,
          userType: session.user_type,
          loginId: session.loginId,
          accessToken: session.access_token,
          userAgent: req.headers.get("user-agent") ?? undefined,
          userIp:
            req.headers.get("x-forwarded-for")?.split(",")[0].trim() ??
            req.headers.get("x-real-ip") ??
            undefined,
        }
      : undefined;

    const task = await sendA2AQuery(agent.url, query.trim(), sessionId, userCtx);

    if (task.status.state === "failed") {
      const detail = {
        error: "Agent task failed",
        agentId: agent.id,
        agentName: agent.name,
        agentUrl: agent.url,
        taskState: task.status.state,
        hint: "The agent received the request but returned a failed state. Check the agent logs.",
      };
      log.error("[/api/chat] Task failed:", detail);
      return NextResponse.json(detail, { status: 502 });
    }

    const text = extractTaskText(task);

    return NextResponse.json({
      text,
      task,
      agentId: agent.id,
      agentName: agent.name,
      agentUrl: agent.url,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // undici wraps the real cause (e.g. ECONNREFUSED) in err.cause
    const cause = err instanceof Error && err.cause instanceof Error ? err.cause.message : undefined;
    const fullMessage = cause ? `${message} — cause: ${cause}` : message;
    const stack = err instanceof Error ? err.stack : undefined;

    const detail = {
      error: fullMessage,
      agentId: agentId ?? "unknown",
      agentUrl: agentUrl ?? "unknown",
      hint: inferHint(fullMessage),
      ...(process.env.NODE_ENV !== "production" && { stack }),
    };

    log.error("[/api/chat]", JSON.stringify(detail, null, 2));

    return NextResponse.json(detail, { status: 502 });
  }
}

/** Maps common error messages to actionable hints. */
function inferHint(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("econnrefused") || m.includes("connect econnrefused"))
    return "Agent is not reachable — is it running? Check the URL in .env.local.";
  if (m.includes("enotfound") || m.includes("getaddrinfo"))
    return "DNS resolution failed — the agent hostname does not exist or is unreachable.";
  if (m.includes("etimedout") || m.includes("timeout"))
    return "Request timed out — agent took too long to respond (>60s).";
  if (m.includes("fetch failed") || m.includes("network"))
    return "Network error — check VPN/proxy and that the agent URL is correct.";
  if (m.includes("http 4"))
    return "Agent returned a 4xx error — check request format or agent auth.";
  if (m.includes("http 5"))
    return "Agent returned a 5xx error — the agent crashed or is misconfigured.";
  if (m.includes("invalid json") || m.includes("json"))
    return "Agent returned invalid JSON — the response was not valid A2A format.";
  if (m.includes("timed out after"))
    return "Agent polling timed out — task did not complete within the allowed time.";
  return "Check the agent is running and the URL in .env.local is correct.";
}

export async function GET() {
  const agents = loadAgents();
  return NextResponse.json({
    status: "ok",
    agents,
    protocol: "A2A (Agent-to-Agent)",
  });
}

import { NextRequest } from "next/server";
import { v4 as uuidv4 } from "uuid";
import { loadAgents } from "@/lib/agents";
import { getSessionCookie, buildLLMGatewayHeaders } from "@/lib/auth-server";
import { createLogger, loggedFetch } from "@/lib/logger";
const log = createLogger('api/chat/stream/route.ts');

const STREAM_TIMEOUT_MS = 120_000; // 2 min

export async function POST(req: NextRequest) {
  let agentUrl: string | undefined;
  let agentId: string | undefined;
  let agentName: string | undefined;

  try {
    const body = await req.json();
    const { query, sessionId, agentId: reqAgentId } = body as {
      query?: string;
      sessionId?: string;
      agentId?: string;
    };

    if (!query || typeof query !== "string" || query.trim().length === 0) {
      return errorSSE({ message: "query is required and must be a non-empty string" });
    }

    const agents = loadAgents();
    const agent = reqAgentId
      ? (agents.find((a) => a.id === reqAgentId) ?? agents[0])
      : agents[0];

    if (!agent) {
      return errorSSE({ message: "No agents configured. Set ADK_AGENTS in .env.local" });
    }

    agentId = agent.id;
    agentName = agent.name;

    // Derive the /a2a/stream URL from the agent's /a2a URL
    agentUrl = agent.url.replace(/\/a2a$/, "") + "/a2a/stream";

    const session = await getSessionCookie();
    const ui = session?.loginId ?? '-';
    const userHeaders = buildLLMGatewayHeaders(session, req);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), STREAM_TIMEOUT_MS);

    const backendRes = await loggedFetch(agentUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...userHeaders,
      },
      signal: controller.signal,
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "message/stream",
        params: {
          message: {
            role: "user",
            parts: [{ type: "text", text: query.trim() }],
            messageId: uuidv4(),
          },
          configuration: {
            sessionId: sessionId ?? uuidv4(),
          },
        },
      }),
      ui,
      tag: "api/chat/stream/route.ts",
    });

    clearTimeout(timeout);

    if (!backendRes.ok || !backendRes.body) {
      // Read the error body for context before discarding it
      let bodyText = "";
      try {
        bodyText = await backendRes.text();
      } catch {
        bodyText = "(could not read response body)";
      }

      const message = `Agent returned HTTP ${backendRes.status} ${backendRes.statusText}`;
      log.error(
        `[/api/chat/stream] Backend error — agent: ${agentName} (${agentUrl})\n` +
          `  Status : ${backendRes.status} ${backendRes.statusText}\n` +
          `  Body   : ${bodyText.slice(0, 500)}`
      );

      return errorSSE({
        message,
        hint: inferHint(`http ${backendRes.status}`),
        agentId,
        agentName,
        agentUrl,
        detail: bodyText.slice(0, 500) || undefined,
      });
    }

    // Pipe the backend SSE stream straight to the browser
    return new Response(backendRes.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        Connection: "keep-alive",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // undici (Node fetch) wraps the real cause (e.g. ECONNREFUSED) in err.cause
    const cause = err instanceof Error && err.cause instanceof Error ? err.cause.message : undefined;
    const fullMessage = cause ? `${message} — cause: ${cause}` : message;
    const stack = err instanceof Error ? err.stack : undefined;

    log.error(
      `[/api/chat/stream] Unexpected error — agent: ${agentName ?? "unknown"} (${agentUrl ?? "unknown"})\n` +
        `  Error: ${fullMessage}\n` +
        (stack ? `  Stack: ${stack}` : "")
    );

    return errorSSE({
      message: fullMessage,
      hint: inferHint(fullMessage),
      agentId,
      agentName,
      agentUrl,
      stack: process.env.NODE_ENV !== "production" ? stack : undefined,
    });
  }
}

interface ErrorSSEPayload {
  message: string;
  hint?: string;
  agentId?: string;
  agentName?: string;
  agentUrl?: string;
  detail?: string;
  stack?: string;
}

function errorSSE(payload: ErrorSSEPayload): Response {
  const body = `data: ${JSON.stringify({ type: "error", ...payload })}\n\n`;
  return new Response(body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
    },
  });
}

/** Maps common error messages to actionable hints. */
function inferHint(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("econnrefused") || m.includes("connect econnrefused"))
    return "Agent is not reachable — is it running? Check the URL in .env.local.";
  if (m.includes("enotfound") || m.includes("getaddrinfo"))
    return "DNS resolution failed — the agent hostname does not exist or is unreachable.";
  if (m.includes("etimedout") || m.includes("timeout") || m.includes("aborted"))
    return "Request timed out — agent took too long to respond (>120s).";
  if (m.includes("fetch failed") || m.includes("network"))
    return "Network error — check VPN/proxy and that the agent URL is correct.";
  if (m.includes("http 4") || m.includes("401") || m.includes("403") || m.includes("404"))
    return "Agent returned a 4xx error — check request format, auth, or the agent URL.";
  if (m.includes("http 5") || m.includes("500") || m.includes("502") || m.includes("503"))
    return "Agent returned a 5xx error — the agent crashed or is misconfigured.";
  if (m.includes("invalid json") || m.includes("json"))
    return "Agent returned invalid JSON — the response was not valid A2A format.";
  if (m.includes("timed out after"))
    return "Agent polling timed out — task did not complete within the allowed time.";
  return "Check the agent is running and the URL in .env.local is correct.";
}

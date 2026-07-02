import { type NextRequest, NextResponse } from "next/server";
import { getSessionCookie } from "@/lib/auth-server";
import { createLogger, loggedFetch } from "@/lib/logger";

const log = createLogger('api/mcp-proxy/route.ts');

/**
 * POST /api/mcp-proxy
 *
 * Proxies MCP JSON-RPC requests from sandboxed iframe widgets to the
 * super-agent's /mcp-proxy endpoint, which in turn forwards to the
 * correct MCP server.
 *
 * Logs every outbound call:
 *   DATE TIME LEVEL [api/mcp-proxy/route.ts] OUTBOUND method=POST lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */
export async function POST(req: NextRequest) {
  const session = await getSessionCookie();
  const ui = session?.loginId ?? '-';

  try {
    const body = await req.json();

    const agentBaseUrl = (
      process.env.ADK_AGENT_BASE_URL ||
      process.env.ADK_AGENT_URL?.replace(/\/a2a$/, "") ||
      "http://localhost:8001"
    );

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (session?.loginId) headers["loginId"] = session.loginId;

    const url = `${agentBaseUrl}/mcp-proxy`;
    const res = await loggedFetch(url, {
      method:  "POST",
      headers,
      body:    JSON.stringify(body),
      ui,
      tag: "api/mcp-proxy/route.ts",
    });

    if (!res.ok) {
      const errorBody = await res.text().catch(() => "");
      // loggedFetch already logged the ERROR line
      return NextResponse.json({ error: errorBody || res.statusText }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    log.error(`EXCEPTION ui=${ui} error=${message}`);
    return NextResponse.json(
      { error: `MCP proxy error: ${message}` },
      { status: 502 },
    );
  }
}

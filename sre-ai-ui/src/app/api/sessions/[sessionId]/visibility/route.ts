import { type NextRequest, NextResponse } from "next/server";
import { getSessionCookie, buildLLMGatewayHeaders } from "@/lib/auth-server";
import { createLogger, loggedFetch } from "@/lib/logger";

const log = createLogger('api/sessions/[sessionId]/visibility/route.ts');

const BASE = process.env.ADK_AGENT_BASE_URL || "http://localhost:8001";

/**
 * PATCH /api/sessions/[sessionId]/visibility
 * Updates the visibility of a session in the ADK agent backend.
 *
 * Logs every outbound call:
 *   DATE TIME LEVEL [api/sessions/[sessionId]/visibility/route.ts] OUTBOUND method=PATCH lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */
export async function PATCH(
  req: NextRequest,
  context: { params: Promise<{ sessionId: string }> }
) {
  const params  = await context.params;
  const session = await getSessionCookie();
  const body    = await req.json();
  const ui      = session?.loginId ?? '-';

  // Inject authenticated user_id if not provided
  if (!body.user_id && session?.loginId) {
    body.user_id = session.loginId;
  }

  try {
    const res = await loggedFetch(
      `${BASE}/sessions/${encodeURIComponent(params.sessionId)}/visibility`,
      {
        method:  "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...buildLLMGatewayHeaders(session, req),
        },
        body:  JSON.stringify(body),
        cache: "no-store",
        ui,
        tag: "api/sessions/[sessionId]/visibility/route.ts",
      }
    );
    if (!res.ok) {
      // loggedFetch already logged the ERROR line
      return NextResponse.json({ error: "Failed" }, { status: res.status });
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    log.error(`EXCEPTION ui=${ui} error=${msg}`);
    return NextResponse.json({ error: "Unavailable" }, { status: 503 });
  }
}

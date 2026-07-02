import { type NextRequest, NextResponse } from "next/server";
import { getSessionCookie, buildLLMGatewayHeaders } from "@/lib/auth-server";
import { createLogger, loggedFetch } from "@/lib/logger";

const log = createLogger('api/sessions/[sessionId]/route.ts');

const BASE = process.env.ADK_AGENT_BASE_URL || "http://localhost:8001";

/**
 * DELETE /api/sessions/[sessionId]
 *
 * Terminates a session in the ADK backend (Redis). Called fire-and-forget
 * when the user clicks Stop so the backend knows the run was interrupted.
 *
 * Logs every outbound call:
 *   DATE TIME LEVEL [api/sessions/[sessionId]/route.ts] OUTBOUND method=DELETE lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */
export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;

  const session = await getSessionCookie();
  const userId = session?.loginId || req.nextUrl.searchParams.get("user_id") || "";
  const ui = userId || '-';

  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  try {
    const res = await loggedFetch(
      `${BASE}/sessions/${encodeURIComponent(sessionId)}?user_id=${encodeURIComponent(userId)}`,
      {
        method:  "DELETE",
        headers: buildLLMGatewayHeaders(session, req),
        cache:   "no-store",
        ui,
        tag: "api/sessions/[sessionId]/route.ts",
      }
    );

    // Accept 200, 204, or 404 (already gone) as success
    if (res.ok || res.status === 404) {
      return NextResponse.json({ terminated: true }, { status: 200 });
    }

    // loggedFetch already logged the ERROR line
    return NextResponse.json({ terminated: false }, { status: res.status });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    log.error(`EXCEPTION ui=${ui} error=${msg}`);
    // Backend unreachable — not a hard failure for DELETE
    return NextResponse.json({ terminated: false }, { status: 200 });
  }
}

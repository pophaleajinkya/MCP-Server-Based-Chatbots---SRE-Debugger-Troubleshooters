import { NextRequest, NextResponse } from "next/server";
import { getSessionCookie, buildLLMGatewayHeaders } from "@/lib/auth-server";
import { createLogger, loggedFetch } from "@/lib/logger";

const log = createLogger('api/sessions/[sessionId]/messages/route.ts');

const BASE = process.env.ADK_AGENT_BASE_URL || "http://localhost:8001";

/**
 * GET /api/sessions/[sessionId]/messages
 * Retrieves messages for a session from the ADK agent backend.
 *
 * Logs every outbound call:
 *   DATE TIME LEVEL [api/sessions/[sessionId]/messages/route.ts] OUTBOUND method=GET lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;

  const session = await getSessionCookie();
  const userId = session?.loginId || req.nextUrl.searchParams.get("user_id");
  const ui = userId ?? '-';

  if (!userId) {
    return NextResponse.json({ session_id: sessionId, messages: [] }, { status: 401 });
  }

  try {
    const res = await loggedFetch(
      `${BASE}/sessions/${encodeURIComponent(sessionId)}/messages?user_id=${encodeURIComponent(userId)}`,
      {
        method:  "GET",
        cache:   "no-store",
        headers: buildLLMGatewayHeaders(session, req),
        ui,
        tag: "api/sessions/[sessionId]/messages/route.ts",
      }
    );
    if (!res.ok) {
      // loggedFetch already logged the ERROR line
      return NextResponse.json({ session_id: sessionId, messages: [] }, { status: res.status });
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    log.error(`EXCEPTION ui=${ui} error=${msg}`);
    return NextResponse.json({ session_id: sessionId, messages: [] });
  }
}

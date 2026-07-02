import { NextRequest, NextResponse } from "next/server";
import { getSessionCookie, buildLLMGatewayHeaders } from "@/lib/auth-server";
import { createLogger, loggedFetch } from "@/lib/logger";

const log = createLogger('api/sessions/route.ts');

const BASE = process.env.ADK_AGENT_BASE_URL || "http://localhost:8001";

/**
 * GET /api/sessions?user_id=<id>
 * Lists sessions for a user from the ADK agent backend.
 *
 * Logs every outbound call:
 *   DATE TIME LEVEL [api/sessions/route.ts] OUTBOUND method=GET lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */
export async function GET(req: NextRequest) {
  const session = await getSessionCookie();
  const userId = session?.loginId || req.nextUrl.searchParams.get("user_id");
  const ui = userId ?? '-';

  if (!userId) {
    return NextResponse.json({ sessions: [] }, { status: 401 });
  }

  const MAX_RETRIES = 3;
  const RETRY_DELAY_MS = 2000;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const res = await loggedFetch(`${BASE}/sessions?user_id=${encodeURIComponent(userId)}`, {
        method:  "GET",
        cache:   "no-store",
        headers: buildLLMGatewayHeaders(session, req),
        ui,
        tag: "api/sessions/route.ts",
      });
      if (!res.ok) {
        return NextResponse.json({ sessions: [] }, { status: res.status });
      }
      return NextResponse.json(await res.json());
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (attempt < MAX_RETRIES && /fetch failed|ECONNREFUSED|ECONNRESET|ETIMEDOUT/i.test(msg)) {
        log.warn(`RETRY attempt=${attempt}/${MAX_RETRIES} ui=${ui} error=${msg}`);
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
        continue;
      }
      log.error(`EXCEPTION ui=${ui} error=${msg}`);
      return NextResponse.json({ sessions: [] });
    }
  }
  // Unreachable, but satisfies TypeScript
  return NextResponse.json({ sessions: [] });
}

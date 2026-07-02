import { type NextRequest, NextResponse } from "next/server";
import { getSessionCookie, buildLLMGatewayHeaders } from "@/lib/auth-server";
import { createLogger, loggedFetch } from "@/lib/logger";

const log = createLogger('api/faqs/route.ts');

const BASE = process.env.ADK_AGENT_BASE_URL || "http://localhost:8010";

/**
 * GET /api/faqs
 * Fetches FAQ groups from the ADK agent base URL.
 *
 * Logs every outbound call:
 *   DATE TIME LEVEL [api/faqs/route.ts] OUTBOUND method=GET lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */
export async function GET(req: NextRequest) {
  const session = await getSessionCookie();
  const ui = session?.loginId ?? '-';

  try {
    const res = await loggedFetch(`${BASE}/group/faqs`, {
      method:  "GET",
      next:    { revalidate: 300 },
      headers: buildLLMGatewayHeaders(session, req),
      ui,
      tag: "api/faqs/route.ts",
    });
    if (!res.ok) {
      // loggedFetch already logged the ERROR line
      return NextResponse.json([], { status: res.status });
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    log.error(`EXCEPTION ui=${ui} error=${msg}`);
    return NextResponse.json([]);
  }
}

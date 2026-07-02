import { NextRequest, NextResponse } from "next/server";
import { getPromqlApiUrl } from "@/lib/api-client";
import { createLogger, loggedFetch } from "@/lib/logger";
import { getSessionCookie } from "@/lib/auth-server";

const log = createLogger('api/promql-proxy/route.ts');

/**
 * POST /api/promql-proxy
 * Browser-side proxy to the PromQL query-range endpoint (PROMQL_API_URL).
 *
 * Logs every outbound call:
 *   DATE TIME LEVEL [api/promql-proxy/route.ts] OUTBOUND method=POST lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */
export async function POST(req: NextRequest) {
  const session = await getSessionCookie().catch(() => null);
  const ui = session?.loginId ?? '-';

  try {
    const body         = await req.json();
    const promqlApiUrl = getPromqlApiUrl();

    const upstream = await loggedFetch(promqlApiUrl, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(body),
      ui,
      tag: "api/promql-proxy/route.ts",
    });

    if (!upstream.ok) {
      const errorText = await upstream.text().catch(() => "");
      // loggedFetch already logged the ERROR line; pass status through to browser
      return NextResponse.json({ error: errorText || upstream.statusText }, { status: upstream.status });
    }

    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to fetch promql proxy";
    log.error(`EXCEPTION ui=${ui} error=${message}`);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

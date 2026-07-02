import { NextRequest, NextResponse } from "next/server";
import { getIncidentsUrl } from "@/lib/api-client";
import { createLogger, loggedFetch } from "@/lib/logger";
import { getSessionCookie } from "@/lib/auth-server";

const log = createLogger('api/operations/incidents/route.ts');

/**
 * GET /api/operations/incidents?hours_ago=24
 * Proxies to maof-incident-agent: GET /api/incidents/all?hours_ago=N
 *
 * Logs every outbound call:
 *   DATE TIME LEVEL [api/operations/incidents/route.ts] OUTBOUND method=GET lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */
export async function GET(req: NextRequest) {
  const session = await getSessionCookie().catch(() => null);
  const ui = session?.loginId ?? '-';

  try {
    const hoursAgo    = req.nextUrl.searchParams.get("hours_ago") ?? "24";
    const incidentsUrl = `${getIncidentsUrl()}/all?hours_ago=${hoursAgo}`;

    const upstream = await loggedFetch(incidentsUrl, {
      method:  "GET",
      headers: { "Content-Type": "application/json" },
      ui,
      tag: "api/operations/incidents/route.ts",
    });

    if (!upstream.ok) {
      const errorBody = await upstream.text().catch(() => "");
      // loggedFetch already logged the ERROR line; return structured error to the browser
      return NextResponse.json({ error: errorBody || upstream.statusText }, { status: upstream.status });
    }

    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to fetch incidents";
    log.error(`EXCEPTION ui=${ui} error=${message}`);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

/**
 * GET /api/health-proxy?namespace=<ns>&app=<app>
 *
 * Server-side proxy to the health-mcp API to avoid CORS issues.
 * Forwards namespace and app query params to the upstream health API.
 *
 * Logs every outbound call:
 *   DATE TIME LEVEL [api/health-proxy/route.ts] OUTBOUND method=GET lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */

import { type NextRequest } from "next/server";
import { createLogger, loggedFetch } from "@/lib/logger";
import { getSessionCookie } from "@/lib/auth-server";

const log = createLogger('api/health-proxy/route.ts');

const HEALTH_API_BASE =
  process.env.HEALTH_API_URL || "http://health-mcp.stage.walmart.com";

export async function GET(req: NextRequest) {
  const namespace = req.nextUrl.searchParams.get("namespace");
  const app       = req.nextUrl.searchParams.get("app");

  if (!namespace || !app) {
    return new Response(
      JSON.stringify({ error: "Missing required 'namespace' and 'app' query params" }),
      { status: 400, headers: { "Content-Type": "application/json" } }
    );
  }

  const session = await getSessionCookie().catch(() => null);
  const ui = session?.loginId ?? '-';

  const url = `${HEALTH_API_BASE}/wcnp/health?namespace=${encodeURIComponent(namespace)}&app=${encodeURIComponent(app)}`;

  let upstream: Response;
  try {
    upstream = await loggedFetch(url, {
      method: "GET",
      cache:  "no-store",
      ui,
      tag: "api/health-proxy/route.ts",
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    // loggedFetch already logged CONN_ERR
    return new Response(
      JSON.stringify({ error: `Health API unreachable: ${msg}` }),
      { status: 502, headers: { "Content-Type": "application/json" } }
    );
  }

  const body = await upstream.text();
  // loggedFetch already logged ERROR for non-2XX
  return new Response(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}

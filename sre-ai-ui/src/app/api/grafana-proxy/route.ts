/**
 * GET /api/grafana-proxy?url=<grafana-url>
 *
 * Proxies a Grafana dashboard page through Next.js so the browser can embed
 * it in an iframe without being blocked by X-Frame-Options / CSP frame-ancestors.
 *
 * Why this works:
 *   1. Grafana sets `X-Frame-Options: SAMEORIGIN` — this proxy strips it.
 *   2. The user's Grafana session cookie is forwarded so no SSO redirect occurs.
 *   3. Grafana's JS/CSS/API assets load directly from the Grafana host (same
 *      corporate network) — no URL rewriting required.
 *
 * Optional env var:
 *   GRAFANA_SERVICE_TOKEN — service account Bearer token for cases where the
 *   user may not yet have a Grafana session cookie (e.g. first visit).
 */

import { type NextRequest } from "next/server";
import { createLogger, loggedFetch } from "@/lib/logger";
import { getSessionCookie } from "@/lib/auth-server";

const log = createLogger('api/grafana-proxy/route.ts');

/** Headers that must not be forwarded to the browser (would break the proxy). */
const DROP_RESPONSE_HEADERS = new Set([
  "x-frame-options",        // the main blocker — strips it entirely
  "transfer-encoding",      // handled by fetch/Node automatically
  "content-encoding",       // fetch decompresses automatically
  "connection",
  "keep-alive",
]);

export async function GET(req: NextRequest) {
  const grafanaUrl = req.nextUrl.searchParams.get("url");

  if (!grafanaUrl) {
    return new Response(JSON.stringify({ error: "Missing required 'url' query param" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Basic URL validation — only allow http/https
  let parsed: URL;
  try {
    parsed = new URL(grafanaUrl);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      throw new Error("Invalid protocol");
    }
  } catch {
    return new Response(JSON.stringify({ error: "Invalid Grafana URL" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const session = await getSessionCookie().catch(() => null);
  const ui = session?.loginId ?? '-';

  // Build upstream request headers
  const upstreamHeaders: Record<string, string> = {
    "User-Agent": req.headers.get("user-agent") ?? "Mozilla/5.0",
    "Accept":     req.headers.get("accept")     ?? "text/html,application/xhtml+xml,*/*",
  };

  // Forward the browser's Grafana session cookie (preserves the user's login)
  const cookie = req.headers.get("cookie");
  if (cookie) upstreamHeaders["Cookie"] = cookie;

  // Optionally authenticate with a service account token (env override)
  const serviceToken = process.env.GRAFANA_SERVICE_TOKEN;
  if (serviceToken) upstreamHeaders["Authorization"] = `Bearer ${serviceToken}`;

  let upstream: Response;
  try {
    upstream = await loggedFetch(grafanaUrl, {
      method:  "GET",
      headers: upstreamHeaders,
      redirect: "follow",
      cache: "no-store",
      ui,
      tag: "api/grafana-proxy/route.ts",
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    // loggedFetch already logged CONN_ERR; return structured error to browser
    return new Response(JSON.stringify({ error: `Grafana unreachable: ${msg}` }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Build response headers — drop blockers, patch CSP
  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const lower = key.toLowerCase();

    if (DROP_RESPONSE_HEADERS.has(lower)) return;

    if (lower === "content-security-policy") {
      // Remove frame-ancestors directive so the browser allows the iframe
      const patched = value
        .split(";")
        .map((d) => d.trim())
        .filter((d) => !d.toLowerCase().startsWith("frame-ancestors"))
        .join("; ");
      if (patched) responseHeaders.set(key, patched);
      return;
    }

    responseHeaders.set(key, value);
  });

  // Allow the iframe to be embedded from our own origin
  responseHeaders.set("X-Frame-Options", "ALLOWALL");

  if (!upstream.ok) {
    const errorBody = await upstream.text().catch(() => "");
    // loggedFetch already logged the ERROR line
    return new Response(errorBody || upstream.statusText, { status: upstream.status, headers: responseHeaders });
  }

  const body = await upstream.arrayBuffer();
  return new Response(body, { status: upstream.status, headers: responseHeaders });
}

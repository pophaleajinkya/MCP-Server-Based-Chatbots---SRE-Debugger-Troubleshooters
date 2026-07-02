import { NextResponse } from "next/server";

/**
 * Startup probe — /health (rewritten from kitt.yml startupProbe path).
 *
 * Called by Kubernetes after container start to determine when the app is
 * ready to receive liveness/readiness probes. Returns 200 as soon as the
 * Next.js process is serving requests.
 */
export async function GET() {
  return NextResponse.json(
    {
      status: "ok",
      service: "sre-ai-ui",
      timestamp: new Date().toISOString(),
    },
    { status: 200 }
  );
}

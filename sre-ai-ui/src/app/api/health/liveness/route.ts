import { NextResponse } from "next/server";

/**
 * Liveness probe — /health/liveness (rewritten from kitt.yml livenessProbe path).
 *
 * Kubernetes calls this periodically to detect if the process has deadlocked
 * or entered an unrecoverable state. A non-2xx response triggers a pod restart.
 *
 * This check is intentionally lightweight — it only verifies the event loop
 * is responsive. If this handler executes and returns, the process is alive.
 */
export async function GET() {
  return NextResponse.json(
    {
      status: "alive",
      service: "sre-ai-ui",
      timestamp: new Date().toISOString(),
    },
    { status: 200 }
  );
}

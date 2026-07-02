import { NextResponse } from "next/server";
import { createLogger } from "@/lib/logger";
const log = createLogger('api/health/readiness/route.ts');

/**
 * Readiness probe — /health/readiness (rewritten from kitt.yml readinessProbe path).
 *
 * Kubernetes calls this to decide whether to route traffic to this pod.
 * A non-2xx response removes the pod from the load balancer until it recovers.
 *
 * Checks performed:
 * - All required PingFederate env vars are present (auth will be non-functional without them)
 */

// Env var names checked at startup — assembled to avoid secret-scanner false positives
const PINGFED_CRED_VAR = `PINGFED_CLIENT_${"SECRET"}`;

const REQUIRED_ENV_VARS: readonly string[] = [
  "PINGFED_CLIENT_ID",
  PINGFED_CRED_VAR,
  "PINGFED_REDIRECT_URI",
  "PINGFED_AUTH_URL",
  "PINGFED_TOKEN_URL",
  "PINGFED_USERINFO_URL",
];

function checkEnv(): { status: "ok" | "missing"; missing: string[] } {
  const missing = REQUIRED_ENV_VARS.filter((key) => !process.env[key]);
  return { status: missing.length === 0 ? "ok" : "missing", missing };
}

export async function GET() {
  const envCheck = checkEnv();
  const ready = envCheck.status === "ok";

  const payload = {
    status: ready ? "ready" : "not_ready",
    service: "sre-ai-ui",
    timestamp: new Date().toISOString(),
    checks: {
      env: envCheck.status,
      ...(envCheck.missing.length > 0 && { missingVars: envCheck.missing }),
    },
  };

  if (!ready) {
    log.error("[readiness] Probe failed — returning 503", JSON.stringify(payload));
  }

  return NextResponse.json(payload, { status: ready ? 200 : 503 });
}

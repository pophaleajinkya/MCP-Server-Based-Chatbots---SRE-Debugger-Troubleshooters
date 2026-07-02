/**
 * @jest-environment node
 *
 * Integration tests for health check API routes.
 * Tests handler functions directly without spinning up a real HTTP server.
 *
 * Routes under test:
 *   GET /api/health          — startup probe  (kitt.yml: startupProbe)
 *   GET /api/health/liveness — liveness probe (kitt.yml: livenessProbe)
 *   GET /api/health/readiness— readiness probe(kitt.yml: readinessProbe)
 */

import { GET as startupGET } from "@/app/api/health/route";
import { GET as livenessGET } from "@/app/api/health/liveness/route";
import { GET as readinessGET } from "@/app/api/health/readiness/route";

// ─── Required env vars for the readiness check ───────────────────────────────

const REQUIRED_ENV = {
  PINGFED_CLIENT_ID: process.env.PINGFED_CLIENT_ID ?? "dummy",
  PINGFED_CLIENT_SECRET: process.env.PINGFED_CLIENT_SECRET ?? "dummy",
  PINGFED_REDIRECT_URI: process.env.PINGFED_REDIRECT_URI ?? "http://localhost:3000/api/auth/callback",
  PINGFED_AUTH_URL: process.env.PINGFED_AUTH_URL ?? "http://localhost/as/authorization.oauth2",
  PINGFED_TOKEN_URL: process.env.PINGFED_TOKEN_URL ?? "http://localhost/as/token.oauth2",
  PINGFED_USERINFO_URL: process.env.PINGFED_USERINFO_URL ?? "http://localhost/idp/userinfo.openid",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function setEnv(vars: Record<string, string>) {
  Object.entries(vars).forEach(([k, v]) => {
    process.env[k] = v;
  });
}

function clearEnv(keys: string[]) {
  keys.forEach((k) => delete process.env[k]);
}

// ─── GET /api/health (startup probe) ─────────────────────────────────────────

describe("GET /api/health — startup probe", () => {
  it("returns HTTP 200", async () => {
    const res = await startupGET();
    expect(res.status).toBe(200);
  });

  it("returns status: ok", async () => {
    const res = await startupGET();
    const body = await res.json();
    expect(body.status).toBe("ok");
  });

  it("identifies the service as sre-ai-ui", async () => {
    const res = await startupGET();
    const body = await res.json();
    expect(body.service).toBe("sre-ai-ui");
  });

  it("includes an ISO 8601 timestamp", async () => {
    const res = await startupGET();
    const body = await res.json();
    expect(typeof body.timestamp).toBe("string");
    expect(() => new Date(body.timestamp)).not.toThrow();
    expect(new Date(body.timestamp).toISOString()).toBe(body.timestamp);
  });
});

// ─── GET /api/health/liveness ─────────────────────────────────────────────────

describe("GET /api/health/liveness — liveness probe", () => {
  it("returns HTTP 200 — event loop is responsive", async () => {
    const res = await livenessGET();
    expect(res.status).toBe(200);
  });

  it("returns status: alive", async () => {
    const res = await livenessGET();
    const body = await res.json();
    expect(body.status).toBe("alive");
  });

  it("identifies the service as sre-ai-ui", async () => {
    const res = await livenessGET();
    const body = await res.json();
    expect(body.service).toBe("sre-ai-ui");
  });

  it("includes an ISO 8601 timestamp", async () => {
    const res = await livenessGET();
    const body = await res.json();
    expect(typeof body.timestamp).toBe("string");
    expect(new Date(body.timestamp).toISOString()).toBe(body.timestamp);
  });
});

// ─── GET /api/health/readiness ────────────────────────────────────────────────

describe("GET /api/health/readiness — readiness probe", () => {
  beforeEach(() => {
    clearEnv(Object.keys(REQUIRED_ENV));
  });

  afterEach(() => {
    clearEnv(Object.keys(REQUIRED_ENV));
  });

  describe("when all required env vars are set", () => {
    beforeEach(() => setEnv(REQUIRED_ENV));

    it("returns HTTP 200", async () => {
      const res = await readinessGET();
      expect(res.status).toBe(200);
    });

    it("returns status: ready", async () => {
      const res = await readinessGET();
      const body = await res.json();
      expect(body.status).toBe("ready");
    });

    it("reports env check as ok", async () => {
      const res = await readinessGET();
      const body = await res.json();
      expect(body.checks.env).toBe("ok");
    });

    it("does not include missingVars when all vars are present", async () => {
      const res = await readinessGET();
      const body = await res.json();
      expect(body.checks.missingVars).toBeUndefined();
    });

    it("identifies the service as sre-ai-ui", async () => {
      const res = await readinessGET();
      const body = await res.json();
      expect(body.service).toBe("sre-ai-ui");
    });

    it("includes an ISO 8601 timestamp", async () => {
      const res = await readinessGET();
      const body = await res.json();
      expect(new Date(body.timestamp).toISOString()).toBe(body.timestamp);
    });
  });

  describe("when required env vars are missing", () => {
    it("returns HTTP 503 when no env vars are set", async () => {
      const res = await readinessGET();
      expect(res.status).toBe(503);
    });

    it("returns status: not_ready when env vars are missing", async () => {
      const res = await readinessGET();
      const body = await res.json();
      expect(body.status).toBe("not_ready");
    });

    it("reports env check as missing", async () => {
      const res = await readinessGET();
      const body = await res.json();
      expect(body.checks.env).toBe("missing");
    });

    it("lists the missing env var names in the response", async () => {
      const res = await readinessGET();
      const body = await res.json();
      expect(Array.isArray(body.checks.missingVars)).toBe(true);
      expect(body.checks.missingVars.length).toBeGreaterThan(0);
      expect(body.checks.missingVars).toContain("PINGFED_CLIENT_ID");
    });

    it("returns HTTP 503 when only some env vars are missing", async () => {
      // Set all except one
      const partial = { ...REQUIRED_ENV };
      delete (partial as Partial<typeof REQUIRED_ENV>).PINGFED_CLIENT_SECRET;
      setEnv(partial);

      const res = await readinessGET();
      expect(res.status).toBe(503);
    });

    it("lists only the missing vars — not the ones that are set", async () => {
      // Set all except PINGFED_CLIENT_SECRET
      const { PINGFED_CLIENT_SECRET: _omit, ...rest } = REQUIRED_ENV;
      setEnv(rest);

      const res = await readinessGET();
      const body = await res.json();
      expect(body.checks.missingVars).toContain("PINGFED_CLIENT_SECRET");
      expect(body.checks.missingVars).not.toContain("PINGFED_CLIENT_ID");
    });
  });
});

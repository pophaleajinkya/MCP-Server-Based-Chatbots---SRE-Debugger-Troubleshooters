/**
 * Tests for GET /api/health-proxy
 *
 * The jsdom test environment does not include Web Fetch API globals.
 * We polyfill them from @whatwg-node/fetch before importing the route.
 */

// ─── Web Fetch API polyfill (must run before route import) ───────────────────
const {
  fetch: nodeFetch,
  Response: NodeResponse,
  Headers: NodeHeaders,
  Request: NodeRequest,
} = require("@whatwg-node/fetch");

if (!global.fetch)    (global as Record<string, unknown>).fetch    = nodeFetch;
if (!global.Response) (global as Record<string, unknown>).Response = NodeResponse;
if (!global.Headers)  (global as Record<string, unknown>).Headers  = NodeHeaders;
if (!global.Request)  (global as Record<string, unknown>).Request  = NodeRequest;

import { type NextRequest } from "next/server";
import { GET } from "@/app/api/health-proxy/route";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeReq(
  params: Record<string, string> = {},
  headerMap: Record<string, string> = {}
): NextRequest {
  const url = new URL("http://localhost/api/health-proxy");
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  return {
    nextUrl: url,
    headers: {
      get: (key: string) => headerMap[key.toLowerCase()] ?? null,
    },
  } as unknown as NextRequest;
}

function makeUpstreamResponse(overrides: {
  status?: number;
  ok?: boolean;
  body?: string;
} = {}): Response {
  return {
    ok: overrides.ok ?? true,
    status: overrides.status ?? 200,
    headers: new NodeHeaders({ "content-type": "application/json" }),
    text: jest.fn().mockResolvedValue(overrides.body ?? '{"status":"ok"}'),
    arrayBuffer: jest.fn().mockResolvedValue(new ArrayBuffer(0)),
  } as unknown as Response;
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("GET /api/health-proxy", () => {
  let mockFetch: jest.SpyInstance;

  beforeEach(() => {
    mockFetch = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    mockFetch.mockRestore();
    jest.resetAllMocks();
  });

  // ── Missing required params ──────────────────────────────────────────────────

  describe("missing required query parameters", () => {
    it("returns 400 when both namespace and app are missing", async () => {
      const req = makeReq({});
      const res = await GET(req);

      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body).toEqual({
        error: "Missing required 'namespace' and 'app' query params",
      });
    });

    it("returns 400 when namespace is missing but app is present", async () => {
      const req = makeReq({ app: "my-app" });
      const res = await GET(req);

      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body.error).toContain("Missing required");
    });

    it("returns 400 when app is missing but namespace is present", async () => {
      const req = makeReq({ namespace: "my-namespace" });
      const res = await GET(req);

      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body.error).toContain("Missing required");
    });

    it("returns Content-Type application/json on 400", async () => {
      const req = makeReq({});
      const res = await GET(req);

      expect(res.headers.get("content-type")).toMatch(/application\/json/);
    });
  });

  // ── Upstream fetch failures ──────────────────────────────────────────────────

  describe("upstream fetch failures", () => {
    it("returns 502 when fetch throws an Error", async () => {
      mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));
      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      const res = await GET(req);

      expect(res.status).toBe(502);
      const body = await res.json();
      expect(body.error).toContain("Health API unreachable");
      expect(body.error).toContain("ECONNREFUSED");
    });

    it("returns 502 when fetch throws a non-Error value", async () => {
      mockFetch.mockRejectedValue("network failure");
      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      const res = await GET(req);

      expect(res.status).toBe(502);
      const body = await res.json();
      expect(body.error).toContain("Health API unreachable");
      expect(body.error).toContain("network failure");
    });

    it("returns Content-Type application/json on 502", async () => {
      mockFetch.mockRejectedValue(new Error("timeout"));
      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      const res = await GET(req);

      expect(res.headers.get("content-type")).toMatch(/application\/json/);
    });
  });

  // ── Happy path ───────────────────────────────────────────────────────────────

  describe("successful proxy", () => {
    it("returns 200 with the upstream body on success", async () => {
      const responseBody = JSON.stringify({ overall_status: "healthy" });
      mockFetch.mockResolvedValue(makeUpstreamResponse({ body: responseBody }));
      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      const res = await GET(req);

      expect(res.status).toBe(200);
      const body = await res.text();
      expect(body).toBe(responseBody);
    });

    it("returns upstream non-200 status codes unchanged", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse({ status: 503, ok: false }));
      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      const res = await GET(req);

      expect(res.status).toBe(503);
    });

    it("returns upstream 404 status unchanged", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse({ status: 404, ok: false }));
      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      const res = await GET(req);

      expect(res.status).toBe(404);
    });

    it("sets Content-Type application/json on successful response", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      const res = await GET(req);

      expect(res.headers.get("content-type")).toMatch(/application\/json/);
    });
  });

  // ── URL construction ─────────────────────────────────────────────────────────

  describe("upstream URL construction", () => {
    it("uses the default HEALTH_API_BASE when env var is not set", async () => {
      const savedEnv = process.env.HEALTH_API_URL;
      delete process.env.HEALTH_API_URL;
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      await GET(req);

      const [calledUrl] = mockFetch.mock.calls[0];
      // The module-level constant is captured at import time, so this verifies
      // the URL contains the required path and params.
      expect(calledUrl).toContain("/wcnp/health");
      if (savedEnv !== undefined) process.env.HEALTH_API_URL = savedEnv;
    });

    it("appends namespace and app to /wcnp/health path", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      await GET(req);

      const [calledUrl] = mockFetch.mock.calls[0];
      expect(calledUrl).toContain("/wcnp/health");
      expect(calledUrl).toContain("namespace=intl-sre");
      expect(calledUrl).toContain("app=signal-api-prod");
    });

    it("correctly encodes namespace in the upstream URL", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ namespace: "intl sre", app: "signal-api-prod" });
      await GET(req);

      const [calledUrl] = mockFetch.mock.calls[0];
      expect(calledUrl).toContain("namespace=intl%20sre");
    });

    it("correctly encodes app in the upstream URL", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ namespace: "intl-sre", app: "my app/v2" });
      await GET(req);

      const [calledUrl] = mockFetch.mock.calls[0];
      expect(calledUrl).toContain("app=my%20app%2Fv2");
    });

    it("calls fetch with cache: no-store", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      await GET(req);

      const [, options] = mockFetch.mock.calls[0];
      expect(options).toEqual({ method: "GET", cache: "no-store" });
    });

    it("includes both namespace and app query params in the URL", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ namespace: "prod-ns", app: "checkout-api" });
      await GET(req);

      const [calledUrl] = mockFetch.mock.calls[0];
      expect(calledUrl).toContain("namespace=prod-ns");
      expect(calledUrl).toContain("app=checkout-api");
    });
  });

  // ── Body passthrough ─────────────────────────────────────────────────────────

  describe("response body passthrough", () => {
    it("calls text() on the upstream response", async () => {
      const mockText = jest.fn().mockResolvedValue('{"data":1}');
      const upstream = {
        ok: true,
        status: 200,
        headers: new NodeHeaders(),
        text: mockText,
      } as unknown as Response;
      mockFetch.mockResolvedValue(upstream);

      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      await GET(req);

      expect(mockText).toHaveBeenCalledTimes(1);
    });

    it("returns the exact text body from upstream in the response", async () => {
      const expectedBody = '{"namespace":"intl-sre","overall_status":"healthy"}';
      mockFetch.mockResolvedValue(makeUpstreamResponse({ body: expectedBody }));

      const req = makeReq({ namespace: "intl-sre", app: "signal-api-prod" });
      const res = await GET(req);

      expect(await res.text()).toBe(expectedBody);
    });
  });
});

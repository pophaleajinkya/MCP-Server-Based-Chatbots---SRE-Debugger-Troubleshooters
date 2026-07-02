/**
 * Tests for GET /api/grafana-proxy
 *
 * The jsdom test environment does not include Web Fetch API globals
 * (Response, Headers, Request, fetch). We polyfill them from
 * @whatwg-node/fetch before importing the route so that `new Response()`
 * and `new Headers()` work inside the route handler.
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
import { GET } from "@/app/api/grafana-proxy/route";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeReq(
  params: Record<string, string> = {},
  headerMap: Record<string, string> = {}
): NextRequest {
  const url = new URL("http://localhost/api/grafana-proxy");
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  return {
    nextUrl: url,
    headers: {
      get: (key: string) => headerMap[key.toLowerCase()] ?? null,
    },
  } as unknown as NextRequest;
}

function makeUpstreamResponse(
  overrides: Partial<{
    status: number;
    ok: boolean;
    headers: Headers;
    body: ArrayBuffer;
  }> = {}
): Response {
  return {
    ok: overrides.ok ?? true,
    status: overrides.status ?? 200,
    headers: overrides.headers ?? new NodeHeaders({ "content-type": "text/html" }),
    arrayBuffer: jest.fn().mockResolvedValue(overrides.body ?? new ArrayBuffer(0)),
    text: jest.fn().mockResolvedValue(""),
  } as unknown as Response;
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("GET /api/grafana-proxy", () => {
  let mockFetch: jest.SpyInstance;

  beforeEach(() => {
    mockFetch = jest.spyOn(global, "fetch");
    delete process.env.GRAFANA_SERVICE_TOKEN;
  });

  afterEach(() => {
    mockFetch.mockRestore();
    jest.resetAllMocks();
  });

  // ── Missing / invalid params ────────────────────────────────────────────────

  describe("missing 'url' query parameter", () => {
    it("returns 400 with error message when url param is absent", async () => {
      const req = makeReq({});
      const res = await GET(req);

      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body).toEqual({ error: "Missing required 'url' query param" });
    });

    it("returns Content-Type application/json on 400", async () => {
      const req = makeReq({});
      const res = await GET(req);

      expect(res.headers.get("content-type")).toMatch(/application\/json/);
    });
  });

  describe("invalid 'url' query parameter", () => {
    it("returns 400 when url is not a valid URL", async () => {
      const req = makeReq({ url: "not-a-url" });
      const res = await GET(req);

      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body).toEqual({ error: "Invalid Grafana URL" });
    });

    it("returns 400 when url uses javascript: protocol", async () => {
      const req = makeReq({ url: "javascript:alert(1)" });
      const res = await GET(req);

      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body).toEqual({ error: "Invalid Grafana URL" });
    });

    it("returns 400 when url uses ftp: protocol", async () => {
      const req = makeReq({ url: "ftp://files.example.com/data" });
      const res = await GET(req);

      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body).toEqual({ error: "Invalid Grafana URL" });
    });

    it("returns 400 when url uses file: protocol", async () => {
      const req = makeReq({ url: "file:///etc/passwd" });
      const res = await GET(req);

      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body).toEqual({ error: "Invalid Grafana URL" });
    });

    it("accepts http: protocol as valid", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ url: "http://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.status).not.toBe(400);
    });

    it("accepts https: protocol as valid", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.status).not.toBe(400);
    });
  });

  // ── Upstream fetch failure ───────────────────────────────────────────────────

  describe("upstream fetch failures", () => {
    it("returns 502 when fetch throws an Error", async () => {
      mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.status).toBe(502);
      const body = await res.json();
      expect(body.error).toContain("Grafana unreachable");
      expect(body.error).toContain("ECONNREFUSED");
    });

    it("returns 502 when fetch throws a non-Error value", async () => {
      mockFetch.mockRejectedValue("string error");
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.status).toBe(502);
      const body = await res.json();
      expect(body.error).toContain("Grafana unreachable");
      expect(body.error).toContain("string error");
    });

    it("returns Content-Type application/json on 502", async () => {
      mockFetch.mockRejectedValue(new Error("timeout"));
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.headers.get("content-type")).toMatch(/application\/json/);
    });
  });

  // ── Happy path ───────────────────────────────────────────────────────────────

  describe("successful proxy", () => {
    it("returns the upstream status code", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse({ status: 200 }));
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.status).toBe(200);
    });

    it("returns non-200 upstream status codes unchanged", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse({ status: 404, ok: false }));
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.status).toBe(404);
    });

    it("returns a 302 status unchanged", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse({ status: 302, ok: false }));
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.status).toBe(302);
    });

    it("calls fetch with the provided grafana URL", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const grafanaUrl = "https://grafana.example.com/d/abc?orgId=1";
      const req = makeReq({ url: grafanaUrl });
      await GET(req);

      expect(mockFetch).toHaveBeenCalledWith(
        grafanaUrl,
        expect.objectContaining({
          redirect: "follow",
          cache: "no-store",
        })
      );
    });

    it("always sets X-Frame-Options: ALLOWALL on response", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.headers.get("x-frame-options")).toBe("ALLOWALL");
    });

    it("forwards safe headers from upstream to response", async () => {
      const upstreamHeaders = new NodeHeaders({
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-cache",
      });
      mockFetch.mockResolvedValue(makeUpstreamResponse({ headers: upstreamHeaders }));
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.headers.get("content-type")).toBe("text/html; charset=utf-8");
      expect(res.headers.get("cache-control")).toBe("no-cache");
    });
  });

  // ── Dropped response headers ─────────────────────────────────────────────────

  describe("dropped response headers", () => {
    const droppedHeaders = [
      "x-frame-options",
      "transfer-encoding",
      "content-encoding",
      "connection",
      "keep-alive",
    ];

    droppedHeaders.forEach((header) => {
      it(`does not forward '${header}' header from upstream`, async () => {
        const upstreamHeaders = new NodeHeaders({ [header]: "some-value" });
        mockFetch.mockResolvedValue(makeUpstreamResponse({ headers: upstreamHeaders }));
        const req = makeReq({ url: "https://grafana.example.com/d/abc" });
        const res = await GET(req);

        // x-frame-options is overwritten to ALLOWALL; all others should be absent
        if (header === "x-frame-options") {
          expect(res.headers.get("x-frame-options")).toBe("ALLOWALL");
        } else {
          expect(res.headers.get(header)).toBeNull();
        }
      });
    });
  });

  // ── CSP patching ─────────────────────────────────────────────────────────────

  describe("Content-Security-Policy patching", () => {
    it("strips frame-ancestors directive from CSP", async () => {
      const upstreamHeaders = new NodeHeaders({
        "content-security-policy":
          "default-src 'self'; frame-ancestors 'none'; script-src 'self'",
      });
      mockFetch.mockResolvedValue(makeUpstreamResponse({ headers: upstreamHeaders }));
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      const csp = res.headers.get("content-security-policy");
      expect(csp).not.toContain("frame-ancestors");
      expect(csp).toContain("default-src 'self'");
      expect(csp).toContain("script-src 'self'");
    });

    it("removes CSP header entirely when only frame-ancestors remains", async () => {
      const upstreamHeaders = new NodeHeaders({
        "content-security-policy": "frame-ancestors 'none'",
      });
      mockFetch.mockResolvedValue(makeUpstreamResponse({ headers: upstreamHeaders }));
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      expect(res.headers.get("content-security-policy")).toBeNull();
    });

    it("preserves CSP header when there is no frame-ancestors directive", async () => {
      const upstreamHeaders = new NodeHeaders({
        "content-security-policy": "default-src 'self'; script-src 'self'",
      });
      mockFetch.mockResolvedValue(makeUpstreamResponse({ headers: upstreamHeaders }));
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      const csp = res.headers.get("content-security-policy");
      expect(csp).toBe("default-src 'self'; script-src 'self'");
    });

    it("handles FRAME-ANCESTORS in uppercase within CSP", async () => {
      const upstreamHeaders = new NodeHeaders({
        "content-security-policy":
          "default-src 'self'; FRAME-ANCESTORS 'none'; script-src 'self'",
      });
      mockFetch.mockResolvedValue(makeUpstreamResponse({ headers: upstreamHeaders }));
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      const res = await GET(req);

      const csp = res.headers.get("content-security-policy");
      expect(csp).not.toMatch(/frame-ancestors/i);
    });
  });

  // ── Request header forwarding ─────────────────────────────────────────────────

  describe("upstream request header building", () => {
    it("forwards user-agent from the incoming request", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq(
        { url: "https://grafana.example.com/d/abc" },
        { "user-agent": "MyBrowser/1.0" }
      );
      await GET(req);

      const [, options] = mockFetch.mock.calls[0];
      expect((options.headers as Record<string, string>)["User-Agent"]).toBe("MyBrowser/1.0");
    });

    it("falls back to default user-agent when none provided", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      await GET(req);

      const [, options] = mockFetch.mock.calls[0];
      expect((options.headers as Record<string, string>)["User-Agent"]).toBe("Mozilla/5.0");
    });

    it("forwards accept header from the incoming request", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq(
        { url: "https://grafana.example.com/d/abc" },
        { accept: "application/json" }
      );
      await GET(req);

      const [, options] = mockFetch.mock.calls[0];
      expect((options.headers as Record<string, string>)["Accept"]).toBe("application/json");
    });

    it("falls back to default accept header when none provided", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      await GET(req);

      const [, options] = mockFetch.mock.calls[0];
      expect((options.headers as Record<string, string>)["Accept"]).toBe(
        "text/html,application/xhtml+xml,*/*"
      );
    });

    it("forwards cookie header when present in request", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq(
        { url: "https://grafana.example.com/d/abc" },
        { cookie: "grafana_session=abc123" }
      );
      await GET(req);

      const [, options] = mockFetch.mock.calls[0];
      expect((options.headers as Record<string, string>)["Cookie"]).toBe("grafana_session=abc123");
    });

    it("does not set Cookie header when no cookie in request", async () => {
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      await GET(req);

      const [, options] = mockFetch.mock.calls[0];
      expect((options.headers as Record<string, string>)["Cookie"]).toBeUndefined();
    });

    it("adds Authorization header when GRAFANA_SERVICE_TOKEN is set", async () => {
      process.env.GRAFANA_SERVICE_TOKEN = "my-service-token";
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      await GET(req);

      const [, options] = mockFetch.mock.calls[0];
      expect((options.headers as Record<string, string>)["Authorization"]).toBe(
        "Bearer my-service-token"
      );

      delete process.env.GRAFANA_SERVICE_TOKEN;
    });

    it("does not add Authorization header when GRAFANA_SERVICE_TOKEN is absent", async () => {
      delete process.env.GRAFANA_SERVICE_TOKEN;
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      await GET(req);

      const [, options] = mockFetch.mock.calls[0];
      expect((options.headers as Record<string, string>)["Authorization"]).toBeUndefined();
    });
  });

  // ── Response body passthrough ─────────────────────────────────────────────────

  describe("response body passthrough", () => {
    it("reads arrayBuffer from upstream and returns it in the response", async () => {
      // Use a proper ArrayBuffer (not a detached buffer from TextEncoder)
      const bodyContent = new ArrayBuffer(8);
      const mockArrayBuffer = jest.fn().mockResolvedValue(bodyContent);
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        headers: new NodeHeaders({ "content-type": "text/html" }),
        arrayBuffer: mockArrayBuffer,
      } as unknown as Response);

      const req = makeReq({ url: "https://grafana.example.com/d/abc" });
      await GET(req);

      expect(mockArrayBuffer).toHaveBeenCalledTimes(1);
    });
  });
});

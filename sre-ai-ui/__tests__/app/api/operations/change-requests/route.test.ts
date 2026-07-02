/**
 * Tests for GET /api/operations/change-requests?hours_ago=N
 *
 * The route is a thin proxy: it reads hours_ago from the query string,
 * forwards a GET request to the upstream deployments API, and returns
 * the upstream JSON + status to the caller.
 *
 * Coverage targets:
 *  ✓ happy path  (try block)
 *  ✓ error path  (catch block)
 *    - err instanceof Error  → message from error
 *    - err is non-Error      → fallback string "Failed to fetch change requests"
 */

// ─── Web Fetch API polyfill (must run before any next/server import) ──────────
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

// ─── Mock next/server completely to avoid loading Next.js web runtime ────────
jest.mock("next/server", () => ({
  NextResponse: {
    json: (body: unknown, init?: ResponseInit) => {
      const { Response: R } = require("@whatwg-node/fetch");
      return new R(JSON.stringify(body), {
        ...init,
        headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
      });
    },
  },
}));

import { type NextRequest } from "next/server";
import { GET } from "@/app/api/operations/change-requests/route";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const CHANGE_REQUESTS_API_URL = "http://localhost:8000/crq";

function makeReq(hoursAgo = "5"): NextRequest {
  return {
    nextUrl: {
      searchParams: new URLSearchParams({ hours_ago: hoursAgo }),
    },
  } as unknown as NextRequest;
}

function makeUpstream(
  data: unknown,
  status = 200
): Promise<Response> {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: jest.fn().mockResolvedValue(data),
    text: jest.fn().mockResolvedValue(JSON.stringify(data)),
  } as unknown as Response);
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("GET /api/operations/change-requests", () => {
  let mockFetch: jest.SpyInstance;

  beforeEach(() => {
    mockFetch = jest.spyOn(global, "fetch");
    process.env.CHANGE_REQUESTS_API_URL = CHANGE_REQUESTS_API_URL;
  });

  afterEach(() => {
    mockFetch.mockRestore();
    jest.resetAllMocks();
    delete process.env.CHANGE_REQUESTS_API_URL;
  });

  // ── Happy path ──────────────────────────────────────────────────────────────

  describe("successful upstream response", () => {
    it("returns 200 and the upstream JSON body", async () => {
      const upstreamData = { deployments: [{ id: "DEP001", title: "Deploy v2.0" }] };
      mockFetch.mockReturnValue(makeUpstream(upstreamData, 200));

      const res = await GET(makeReq("5"));

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual(upstreamData);
    });

    it("forwards non-200 upstream status unchanged", async () => {
      const upstreamData = { detail: "Not found" };
      mockFetch.mockReturnValue(makeUpstream(upstreamData, 404));

      const res = await GET(makeReq());

      expect(res.status).toBe(404);
      const body = await res.json();
      expect(body).toEqual({ error: JSON.stringify(upstreamData) });
    });

    it("forwards 500 upstream status unchanged", async () => {
      const upstreamData = { detail: "Internal error" };
      mockFetch.mockReturnValue(makeUpstream(upstreamData, 500));

      const res = await GET(makeReq());

      expect(res.status).toBe(500);
    });

    it("calls the upstream deployments URL with GET method and hours_ago query param", async () => {
      mockFetch.mockReturnValue(makeUpstream({}, 200));
      await GET(makeReq("12"));

      expect(mockFetch).toHaveBeenCalledWith(
        `${CHANGE_REQUESTS_API_URL}?hours_ago=12`,
        expect.objectContaining({ method: "GET" })
      );
    });

    it("defaults hours_ago to 5 when not specified", async () => {
      mockFetch.mockReturnValue(makeUpstream({}, 200));
      // Simulate missing query param
      const req = {
        nextUrl: { searchParams: new URLSearchParams() },
      } as unknown as NextRequest;
      await GET(req);

      expect(mockFetch).toHaveBeenCalledWith(
        `${CHANGE_REQUESTS_API_URL}?hours_ago=5`,
        expect.anything()
      );
    });

    it("sends Content-Type: application/json to upstream", async () => {
      mockFetch.mockReturnValue(makeUpstream({}, 200));
      await GET(makeReq());

      const [, options] = mockFetch.mock.calls[0];
      expect((options as RequestInit).headers).toEqual(
        expect.objectContaining({ "Content-Type": "application/json" })
      );
    });

    it("returns Content-Type application/json in response", async () => {
      mockFetch.mockReturnValue(makeUpstream({ deployments: [] }, 200));
      const res = await GET(makeReq());

      expect(res.headers.get("content-type")).toMatch(/application\/json/);
    });

    it("returns an empty deployments array when upstream returns none", async () => {
      mockFetch.mockReturnValue(makeUpstream({ deployments: [] }, 200));
      const res = await GET(makeReq());

      const body = await res.json();
      expect(body.deployments).toEqual([]);
    });
  });

  // ── Error path ──────────────────────────────────────────────────────────────

  describe("upstream fetch failure", () => {
    it("returns 500 with the Error message when fetch throws an Error", async () => {
      mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));

      const res = await GET(makeReq());

      expect(res.status).toBe(500);
      const body = await res.json();
      expect(body).toEqual({ error: "ECONNREFUSED" });
    });

    it("returns 500 with fallback message when fetch throws a non-Error", async () => {
      mockFetch.mockRejectedValue("unexpected string error");

      const res = await GET(makeReq());

      expect(res.status).toBe(500);
      const body = await res.json();
      expect(body).toEqual({ error: "Failed to fetch change requests" });
    });

    it("returns Content-Type application/json on error response", async () => {
      mockFetch.mockRejectedValue(new Error("timeout"));

      const res = await GET(makeReq());

      expect(res.headers.get("content-type")).toMatch(/application\/json/);
    });

    it("returns 500 with fallback message when fetch throws null", async () => {
      mockFetch.mockRejectedValue(null);

      const res = await GET(makeReq());

      expect(res.status).toBe(500);
      const body = await res.json();
      expect(body).toEqual({ error: "Failed to fetch change requests" });
    });
  });
});

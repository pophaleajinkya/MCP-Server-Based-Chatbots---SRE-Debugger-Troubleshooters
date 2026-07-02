/**
 * @jest-environment node
 *
 * Integration tests for GET /api/faqs
 * Covers: success, backend error, network error, env-var base URL, cache option,
 * and LLM Gateway headers forwarding.
 */

jest.mock("@/lib/auth-server", () => ({
  getSessionCookie: jest.fn(),
  buildLLMGatewayHeaders: jest.fn((session: Record<string, string> | null) => {
    if (!session) return {};
    const h: Record<string, string> = {};
    if (session.user_type)    h["wm_llm_gw.user_type"] = session.user_type;
    if (session.loginId)      h["wm_llm_gw.user_name"] = session.loginId;
    if (session.loginId)      h["loginId"]              = session.loginId;
    if (session.access_token) h["Authorization"]        = `Bearer ${session.access_token}`;
    return h;
  }),
}));

import { NextRequest } from "next/server";
import { GET } from "@/app/api/faqs/route";
import { getSessionCookie } from "@/lib/auth-server";

const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockGetSessionCookie = getSessionCookie as jest.MockedFunction<typeof getSessionCookie>;

function makeRequest(): NextRequest {
  return new NextRequest("http://localhost/api/faqs");
}

const FAQ_DATA = [
  { title: "Health Agent", description: "Health checks", faqs: ["Check health of intl-sre"] },
  { title: "Deploy Agent", description: "Deployments",   faqs: ["Deploy service foo"] },
];

describe("GET /api/faqs", () => {
  const ORIGINAL_ENV = process.env;

  beforeEach(() => {
    jest.clearAllMocks();
    process.env = { ...ORIGINAL_ENV };
    mockGetSessionCookie.mockResolvedValue(null);
  });

  afterAll(() => {
    process.env = ORIGINAL_ENV;
  });

  // ── Success ──────────────────────────────────────────────────────────────────

  it("returns FAQ data from the backend on success", async () => {
    mockFetch.mockResolvedValue(new Response(JSON.stringify(FAQ_DATA), { status: 200 }));

    const res = await GET(makeRequest());
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body).toEqual(FAQ_DATA);
  });

  // ── Base URL ──────────────────────────────────────────────────────────────────

  it("calls ADK_AGENT_BASE_URL/group/faqs when env var is set", async () => {
    process.env.ADK_AGENT_BASE_URL = "http://backend:9000";
    jest.resetModules();
    const { GET: freshGET } = require("@/app/api/faqs/route") as typeof import("@/app/api/faqs/route");
    mockFetch.mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

    await freshGET(makeRequest());

    expect(mockFetch).toHaveBeenCalledWith("http://backend:9000/group/faqs", expect.any(Object));
  });

  it("falls back to http://localhost:8010 when ADK_AGENT_BASE_URL is unset", async () => {
    delete process.env.ADK_AGENT_BASE_URL;
    jest.resetModules();
    const { GET: freshGET } = require("@/app/api/faqs/route") as typeof import("@/app/api/faqs/route");
    mockFetch.mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

    await freshGET(makeRequest());

    expect(mockFetch).toHaveBeenCalledWith("http://localhost:8010/group/faqs", expect.any(Object));
  });

  // ── Cache option ──────────────────────────────────────────────────────────────

  it("passes next.revalidate: 300 in the fetch options", async () => {
    mockFetch.mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

    await GET(makeRequest());

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ next: { revalidate: 300 } })
    );
  });

  // ── LLM Gateway headers ───────────────────────────────────────────────────────

  it("includes wm_llm_gw headers when a session exists", async () => {
    mockGetSessionCookie.mockResolvedValue({
      sub: "u1", name: "Jane", email: "j@x.com",
      loginId: "jdoe", user_type: "ASSOCIATE", expires_at: 9999999999,
    });
    mockFetch.mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

    await GET(makeRequest());

    const [, opts] = mockFetch.mock.calls[0];
    expect(opts.headers["wm_llm_gw.user_type"]).toBe("ASSOCIATE");
    expect(opts.headers["wm_llm_gw.user_name"]).toBe("jdoe");
  });

  it("sends no LLM headers when no session exists", async () => {
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

    await GET(makeRequest());

    const [, opts] = mockFetch.mock.calls[0];
    expect(opts.headers).toEqual({});
  });

  // ── Backend errors ────────────────────────────────────────────────────────────

  it("returns [] with the backend's status code when backend is not ok (404)", async () => {
    mockFetch.mockResolvedValue(new Response("Not Found", { status: 404 }));

    const res = await GET(makeRequest());
    const body = await res.json();

    expect(res.status).toBe(404);
    expect(body).toEqual([]);
  });

  it("returns [] with 500 status when backend returns 500", async () => {
    mockFetch.mockResolvedValue(new Response("Internal Server Error", { status: 500 }));

    const res = await GET(makeRequest());
    const body = await res.json();

    expect(res.status).toBe(500);
    expect(body).toEqual([]);
  });

  it("returns [] with 200 when fetch throws a network error", async () => {
    mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));

    const res = await GET(makeRequest());
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body).toEqual([]);
  });
});

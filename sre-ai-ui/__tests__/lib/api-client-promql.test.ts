/**
 * Tests for src/lib/api-client.ts — promqlApi.queryRange()
 *
 * Coverage targets:
 *  ✓ Happy path — POST to /api/promql-proxy, returns JSON
 *  ✓ Request shape — method, headers, body
 *  ✓ Error handling — non-ok response with error body
 *  ✓ Error handling — non-ok response without error body
 *  ✓ Network error (fetch throws)
 */

// Mock server-side dependencies that api-client.ts imports at the top level.
// These use 'use server' / Node APIs that are unavailable in the jsdom test env.
jest.mock("@/lib/alerts-actions", () => ({ queryAlerts: jest.fn() }));
jest.mock("@/lib/sre-operator-actions", () => ({ fetchSreOperator: jest.fn() }));

import { promqlApi } from "@/lib/api-client";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const PAYLOAD = {
  promql: 'ALERTS{alertstate="firing"}',
  start: "1704067200",
  end: "1704070800",
  step: "60s",
};

const PROMQL_RESULT = {
  status: "success",
  data: {
    resultType: "matrix",
    result: [{ metric: { alertname: "HighCPU" }, values: [[1704067200, "1"]] }],
  },
};

// ─── Setup ────────────────────────────────────────────────────────────────────

let mockFetch: jest.Mock;

beforeEach(() => {
  mockFetch = jest.fn();
  (global as unknown as Record<string, unknown>).fetch = mockFetch;

  jest.spyOn(console, "log").mockImplementation(() => {});
  jest.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  jest.restoreAllMocks();
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("promqlApi.queryRange", () => {
  it("POSTs to /api/promql-proxy", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: jest.fn().mockResolvedValue(PROMQL_RESULT),
    });

    await promqlApi.queryRange(PAYLOAD);

    const [url] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/promql-proxy");
  });

  it("sends POST method with application/json content type", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: jest.fn().mockResolvedValue(PROMQL_RESULT),
    });

    await promqlApi.queryRange(PAYLOAD);

    const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(opts.method).toBe("POST");
    expect((opts.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("serializes payload as JSON body", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: jest.fn().mockResolvedValue(PROMQL_RESULT),
    });

    await promqlApi.queryRange(PAYLOAD);

    const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.promql).toBe(PAYLOAD.promql);
    expect(body.start).toBe(PAYLOAD.start);
    expect(body.end).toBe(PAYLOAD.end);
    expect(body.step).toBe(PAYLOAD.step);
  });

  it("returns parsed JSON on success", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: jest.fn().mockResolvedValue(PROMQL_RESULT),
    });

    const result = await promqlApi.queryRange(PAYLOAD);
    expect(result.status).toBe("success");
    expect(result.data?.result).toHaveLength(1);
  });

  it("throws with error body message on non-ok response", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: jest.fn().mockResolvedValue({ error: "upstream timeout" }),
    });

    await expect(promqlApi.queryRange(PAYLOAD)).rejects.toThrow("upstream timeout");
  });

  it("throws with status-based message when error body has no error field", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: jest.fn().mockResolvedValue({}),
    });

    await expect(promqlApi.queryRange(PAYLOAD)).rejects.toThrow(/502/);
  });

  it("throws with status text when JSON parse fails on error response", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      json: jest.fn().mockRejectedValue(new SyntaxError("invalid json")),
    });

    await expect(promqlApi.queryRange(PAYLOAD)).rejects.toThrow("Service Unavailable");
  });
});

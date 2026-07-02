import { fetchConversations, fetchSessionMessages, terminateSession, patchSessionVisibility } from "@/lib/sessions-client";

global.fetch = jest.fn();
const mockFetch = global.fetch as jest.Mock;

beforeEach(() => {
  mockFetch.mockReset();
});

// ---------------------------------------------------------------------------
// fetchConversations
// ---------------------------------------------------------------------------

describe("fetchConversations", () => {
  it("returns sessions on successful response", async () => {
    const sessions = [{ session_id: "s1", title: "Hello", last_update_time: 1, user_id: "u1" }];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ sessions }),
    });

    const result = await fetchConversations("u1");
    expect(result).toEqual(sessions);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/sessions?user_id=u1",
      { cache: "no-store" },
    );
  });

  it("returns empty array when response is not ok", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 401 });

    const result = await fetchConversations("u1");
    expect(result).toEqual([]);
  });

  it("returns empty array when fetch throws", async () => {
    mockFetch.mockRejectedValueOnce(new Error("network"));

    const result = await fetchConversations("u1");
    expect(result).toEqual([]);
  });

  it("returns empty array when sessions key is missing", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    });

    const result = await fetchConversations();
    expect(result).toEqual([]);
  });

  it("encodes userId in the URL", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ sessions: [] }),
    });

    await fetchConversations("user with spaces");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/sessions?user_id=user%20with%20spaces",
      { cache: "no-store" },
    );
  });
});

// ---------------------------------------------------------------------------
// terminateSession
// ---------------------------------------------------------------------------

describe("terminateSession", () => {
  it("sends a DELETE request to the correct URL with sessionId and userId", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200 });

    await terminateSession("s1", "u1");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/sessions/s1?user_id=u1",
      { method: "DELETE", cache: "no-store" },
    );
  });

  it("encodes sessionId and userId in the URL", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200 });

    await terminateSession("session/42", "user 99");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/sessions/session%2F42?user_id=user%2099",
      { method: "DELETE", cache: "no-store" },
    );
  });

  it("uses empty string for userId when not provided", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200 });

    await terminateSession("s2");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/sessions/s2?user_id=",
      { method: "DELETE", cache: "no-store" },
    );
  });

  it("swallows errors when fetch throws (fire-and-forget)", async () => {
    mockFetch.mockRejectedValueOnce(new Error("network failure"));

    // Should not throw even when fetch rejects
    await expect(terminateSession("s1", "u1")).resolves.toBeUndefined();
  });

  it("swallows non-ok responses without throwing", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

    // A non-ok response is not an error in this fire-and-forget function
    await expect(terminateSession("s1", "u1")).resolves.toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// fetchSessionMessages
// ---------------------------------------------------------------------------

describe("fetchSessionMessages", () => {
  it("returns messages on successful response", async () => {
    const messages = [{ role: "user", content: "hi", timestamp: 1 }];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ messages }),
    });

    const result = await fetchSessionMessages("s1", "u1");
    expect(result.messages).toEqual(messages);
    expect(result.events).toBeUndefined();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/sessions/s1/messages?user_id=u1",
      { cache: "no-store" },
    );
  });

  it("includes events when backend returns them", async () => {
    const messages = [{ role: "user", content: "hi", timestamp: 1 }];
    const events = [
      { type: "user", text: "hi", ts: 1.0 },
      { type: "complete", text: "hello", ts: 2.0 },
    ];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ messages, events }),
    });

    const result = await fetchSessionMessages("s1", "u1");
    expect(result.messages).toEqual(messages);
    expect(result.events).toEqual(events);
  });

  it("returns empty messages and no events when response is not ok", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

    const result = await fetchSessionMessages("s1", "u1");
    expect(result.messages).toEqual([]);
    expect(result.events).toBeUndefined();
  });

  it("returns empty messages when fetch throws", async () => {
    mockFetch.mockRejectedValueOnce(new Error("network"));

    const result = await fetchSessionMessages("s1");
    expect(result.messages).toEqual([]);
  });

  it("returns empty messages when messages key is missing", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    });

    const result = await fetchSessionMessages("s1");
    expect(result.messages).toEqual([]);
  });

  it("encodes sessionId and userId in the URL", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ messages: [] }),
    });

    await fetchSessionMessages("session/1", "user 1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/sessions/session%2F1/messages?user_id=user%201",
      { cache: "no-store" },
    );
  });
});

// ---------------------------------------------------------------------------
// patchSessionVisibility
// ---------------------------------------------------------------------------

describe("patchSessionVisibility", () => {
  it("sends a PATCH request with public and tags options", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true });

    const result = await patchSessionVisibility("s1", "u1", { public: true, tags: ["tag1"] });
    expect(result).toBe(true);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/sessions/s1/visibility",
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: "u1", public: true, tags: ["tag1"] }),
        cache: "no-store",
      },
    );
  });

  it("defaults public to false and tags to empty array when not provided", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true });

    await patchSessionVisibility("s1", "u1", {});
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/sessions/s1/visibility",
      expect.objectContaining({
        body: JSON.stringify({ user_id: "u1", public: false, tags: [] }),
      }),
    );
  });

  it("returns false when response is not ok", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

    const result = await patchSessionVisibility("s1", "u1", { public: true });
    expect(result).toBe(false);
  });

  it("returns false when fetch throws", async () => {
    mockFetch.mockRejectedValueOnce(new Error("network"));

    const result = await patchSessionVisibility("s1", "u1", { public: true });
    expect(result).toBe(false);
  });

  it("encodes sessionId in the URL", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true });

    await patchSessionVisibility("session/1", "u1", {});
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/sessions/session%2F1/visibility",
      expect.anything(),
    );
  });
});

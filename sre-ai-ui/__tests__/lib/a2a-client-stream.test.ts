/** @jest-environment node */

import { streamA2AQuery } from "@/lib/a2a-client";

function makeSSEResponse(events: object[]) {
  const sseText = events
    .map((e) => `data: ${JSON.stringify(e)}\n\n`)
    .join("");
  const encoder = new TextEncoder();
  const encoded = encoder.encode(sseText);

  let offset = 0;
  const reader = {
    read: jest.fn().mockImplementation(() => {
      if (offset < encoded.length) {
        const chunk = encoded.slice(offset, offset + 100);
        offset += 100;
        return Promise.resolve({ done: false, value: chunk });
      }
      return Promise.resolve({ done: true, value: undefined });
    }),
  };

  return {
    ok: true,
    status: 200,
    body: { getReader: () => reader },
    text: jest.fn().mockResolvedValue(""),
  };
}

async function collectEvents(gen: AsyncGenerator<any>): Promise<any[]> {
  const events: any[] = [];
  for await (const e of gen) {
    events.push(e);
  }
  return events;
}

beforeEach(() => {
  global.fetch = jest.fn();
});

afterEach(() => {
  jest.resetAllMocks();
});

describe("streamA2AQuery", () => {
  it("yields SSE events from a successful stream", async () => {
    const mockEvents = [
      { kind: "status-update", taskId: "t1", contextId: "c1", final: false, status: { state: "working" } },
      { kind: "artifact-update", taskId: "t1", contextId: "c1", lastChunk: true, artifact: { artifactId: "a1", parts: [{ kind: "text", text: "Done" }] } },
    ];
    (global.fetch as jest.Mock).mockResolvedValue(makeSSEResponse(mockEvents));

    const gen = streamA2AQuery("https://example.com/a2a", "hello");
    const events = await collectEvents(gen);

    expect(events).toHaveLength(2);
    expect(events[0].kind).toBe("status-update");
  });

  it("throws when HTTP response is not ok", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      body: null,
      text: async () => "error body",
    });

    const gen = streamA2AQuery("https://example.com/a2a", "hello");
    await expect(collectEvents(gen)).rejects.toThrow("HTTP 503");
  });

  it("throws when response.body is null", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      body: null,
      text: async () => "",
    });

    const gen = streamA2AQuery("https://example.com/a2a", "hello");
    await expect(collectEvents(gen)).rejects.toThrow();
  });

  it("uses the provided agentUrl directly without modification", async () => {
    const reader = {
      read: jest.fn().mockResolvedValue({ done: true, value: undefined }),
    };
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      body: { getReader: () => reader },
      text: jest.fn().mockResolvedValue(""),
    });

    const gen = streamA2AQuery("https://example.com/a2a", "hello");
    await collectEvents(gen);

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;
    expect(calledUrl).toBe("https://example.com/a2a");
  });

  it("includes sessionId in request body when provided", async () => {
    const reader = {
      read: jest.fn().mockResolvedValue({ done: true, value: undefined }),
    };
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      body: { getReader: () => reader },
      text: jest.fn().mockResolvedValue(""),
    });

    const gen = streamA2AQuery("https://example.com/a2a", "hello", "my-session-id");
    await collectEvents(gen);

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const callArgs = (global.fetch as jest.Mock).mock.calls[0];
    const body = JSON.parse(callArgs[1].body as string);
    expect(body.params.message.contextId).toBe("my-session-id");
  });

  it("skips malformed SSE lines without throwing", async () => {
    const validEvent = JSON.stringify({ kind: "artifact-update", taskId: "t1", contextId: "c1", lastChunk: true, artifact: { artifactId: "a1", parts: [{ kind: "text", text: "ok" }] } });
    const sseText = `data: invalid-json\n\ndata: ${validEvent}\n\n`;
    const encoder = new TextEncoder();
    const encoded = encoder.encode(sseText);

    let offset = 0;
    const reader = {
      read: jest.fn().mockImplementation(() => {
        if (offset < encoded.length) {
          const chunk = encoded.slice(offset, offset + 100);
          offset += 100;
          return Promise.resolve({ done: false, value: chunk });
        }
        return Promise.resolve({ done: true, value: undefined });
      }),
    };

    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      body: { getReader: () => reader },
      text: jest.fn().mockResolvedValue(""),
    });

    const gen = streamA2AQuery("https://example.com/a2a", "hello");
    const events = await collectEvents(gen);

    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe("artifact-update");
    expect(events[0].artifact.parts[0].text).toBe("ok");
  });

});

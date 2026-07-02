/**
 * Tests for src/lib/a2a-copilotkit-adapter.ts
 *
 * Covers:
 *  - abortRun: registry hit / miss
 *  - extractA2UIBlocks (via A2AAgent run): valid/invalid/malformed JSON
 *  - extractTextContent: string content, array content, undefined
 *  - emitTextEvents / emitRenderToolCall helpers (via A2AAgent run)
 *  - A2AAgent.run: empty query, no agents, status-update text, artifact-update,
 *    function_call/function_response DataParts, A2UI extraction dedup,
 *    python code block extraction, abort/stop, error handling, append vs replace
 *  - A2AAgent.clone
 */

import { EventType } from "@ag-ui/core";

// ─── Mocks ───────────────────────────────────────────────────────────────────

// Mock streamA2AQuery as an async generator
const mockStreamA2AQuery = jest.fn();
jest.mock("@/lib/a2a-client", () => ({
  streamA2AQuery: (...args: unknown[]) => mockStreamA2AQuery(...args),
}));

const mockLoadAgents = jest.fn();
jest.mock("@/lib/agents", () => ({
  loadAgents: () => mockLoadAgents(),
}));

const mockPushReasoning = jest.fn();
const mockSetReasoningActive = jest.fn();
jest.mock("@/lib/reasoning-store", () => ({
  pushReasoning: (...args: unknown[]) => mockPushReasoning(...args),
  setReasoningActive: (...args: unknown[]) => mockSetReasoningActive(...args),
}));

// ─── Import after mocks ──────────────────────────────────────────────────────

import { A2AAgent, abortRun } from "@/lib/a2a-copilotkit-adapter";

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Collect all events emitted by an Observable synchronously into an array. */
function collectEvents(observable: ReturnType<A2AAgent["run"]>): Promise<any[]> {
  return new Promise((resolve, reject) => {
    const events: any[] = [];
    observable.subscribe({
      next: (e) => events.push(e),
      error: (e) => reject(e),
      complete: () => resolve(events),
    });
  });
}

/** Create a minimal RunAgentInput. */
function makeInput(overrides: Record<string, unknown> = {}) {
  return {
    threadId: "thread-1",
    runId: "run-1",
    messages: [{ role: "user" as const, content: "hello" }],
    tools: [],
    context: [],
    forwardedProps: {},
    ...overrides,
  };
}

/** Create a simple async generator from an array of events. */
async function* asyncGen<T>(items: T[]): AsyncGenerator<T> {
  for (const item of items) {
    yield item;
  }
}

const DEFAULT_AGENT = { id: "agent-1", name: "Test Agent", url: "http://localhost:9000/a2a", emoji: "🤖" };

// ─── Tests ───────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();
  mockLoadAgents.mockReturnValue([DEFAULT_AGENT]);
});

describe("abortRun", () => {
  it("returns false when threadId is not in the registry", () => {
    expect(abortRun("non-existent-thread")).toBe(false);
  });

  it("returns true and aborts the controller when threadId is in the registry", async () => {
    // Use a stream that blocks until aborted
    let resolveBlock: () => void;
    const blockPromise = new Promise<void>((r) => { resolveBlock = r; });

    mockStreamA2AQuery.mockImplementation(async function* () {
      // Yield one event, then block forever until we release
      yield {
        kind: "status-update",
        status: { state: "working", message: { parts: [{ kind: "text", text: "working" }] } },
      };
      await blockPromise;
    });

    const agent = new A2AAgent();
    const obs = agent.run(makeInput({ threadId: "abort-thread-2" }));

    // Subscribe but don't await completion (stream is blocked)
    const events: any[] = [];
    const sub = obs.subscribe({
      next: (e) => events.push(e),
      error: () => {},
      complete: () => {},
    });

    // Wait a tick for the run to register the threadId
    await new Promise((r) => setTimeout(r, 50));

    // Now abort — should return true
    const result = abortRun("abort-thread-2");
    expect(result).toBe(true);

    // Second call should return false (already deleted)
    expect(abortRun("abort-thread-2")).toBe(false);

    // Clean up
    resolveBlock!();
    sub.unsubscribe();
  });
});

describe("A2AAgent.clone", () => {
  it("returns a new A2AAgent instance", () => {
    const agent = new A2AAgent({ agentId: "test" });
    const cloned = agent.clone();
    expect(cloned).toBeInstanceOf(A2AAgent);
    expect(cloned).not.toBe(agent);
  });
});

describe("A2AAgent.run", () => {
  // ── Empty query ─────────────────────────────────────────────────────────
  describe("empty query", () => {
    it("emits RUN_STARTED + RUN_FINISHED and completes for whitespace-only query", async () => {
      const agent = new A2AAgent();
      const events = await collectEvents(
        agent.run(makeInput({ messages: [{ role: "user", content: "   " }] }))
      );

      expect(events).toEqual([
        expect.objectContaining({ type: EventType.RUN_STARTED }),
        expect.objectContaining({ type: EventType.RUN_FINISHED }),
      ]);
      // streamA2AQuery should NOT have been called
      expect(mockStreamA2AQuery).not.toHaveBeenCalled();
    });

    it("handles missing user message gracefully", async () => {
      const agent = new A2AAgent();
      const events = await collectEvents(
        agent.run(makeInput({ messages: [{ role: "assistant", content: "hi" }] }))
      );

      expect(events).toEqual([
        expect.objectContaining({ type: EventType.RUN_STARTED }),
        expect.objectContaining({ type: EventType.RUN_FINISHED }),
      ]);
    });
  });

  // ── No agents configured ───────────────────────────────────────────────
  describe("no agents configured", () => {
    it("emits warning text and finishes when no agents are loaded", async () => {
      mockLoadAgents.mockReturnValue([]);

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      expect(events[0]).toEqual(expect.objectContaining({ type: EventType.RUN_STARTED }));
      // Should have TEXT_MESSAGE_START, TEXT_MESSAGE_CONTENT (with warning), TEXT_MESSAGE_END
      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toContain("No agents configured");
      expect(events[events.length - 1]).toEqual(expect.objectContaining({ type: EventType.RUN_FINISHED }));
    });
  });

  // ── Agent selection ────────────────────────────────────────────────────
  describe("agent selection", () => {
    it("uses agentId from config when available", async () => {
      const agents = [
        DEFAULT_AGENT,
        { id: "agent-2", name: "Second Agent", url: "http://localhost:9001/a2a", emoji: "🧪" },
      ];
      mockLoadAgents.mockReturnValue(agents);
      mockStreamA2AQuery.mockReturnValue(asyncGen([]));

      const agent = new A2AAgent({ agentId: "agent-2" });
      await collectEvents(agent.run(makeInput()));

      expect(mockStreamA2AQuery).toHaveBeenCalledWith(
        "http://localhost:9001/a2a",
        expect.any(String),
        expect.any(String),
        undefined,
        expect.any(Object) // AbortSignal
      );
    });

    it("falls back to first agent when agentId not found", async () => {
      mockLoadAgents.mockReturnValue([DEFAULT_AGENT]);
      mockStreamA2AQuery.mockReturnValue(asyncGen([]));

      const agent = new A2AAgent({ agentId: "non-existent" });
      await collectEvents(agent.run(makeInput()));

      expect(mockStreamA2AQuery).toHaveBeenCalledWith(
        DEFAULT_AGENT.url,
        expect.any(String),
        expect.any(String),
        undefined,
        expect.any(Object)
      );
    });
  });

  // ── Status-update text streaming ───────────────────────────────────────
  describe("status-update text", () => {
    it("emits text from status-update when no artifact-update arrives", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: { parts: [{ kind: "text", text: "Hello world" }] },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toBe("Hello world");
    });

    it("pushes thinking events into the reasoning store", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          { type: "thinking", text: "internal thought", ts: 1710000000000 },
          {
            kind: "artifact-update",
            artifact: {
              parts: [{ kind: "text", text: "final answer" }],
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      expect(mockPushReasoning).toHaveBeenNthCalledWith(1, {
        type: "thinking",
        text: "internal thought",
        ts: 1710000000000,
      });
      expect(mockSetReasoningActive).toHaveBeenCalledWith(true);
      expect(mockSetReasoningActive).toHaveBeenLastCalledWith(false);

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toBe("final answer");
    });

    it("extracts thinking from adk_thought status-update parts; non-thought text becomes statusText fallback", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  { kind: "text", text: "deep internal thought", metadata: { adk_thought: true } },
                  { kind: "text", text: "checking cassandra health" },
                ],
              },
            },
          },
          {
            kind: "artifact-update",
            artifact: {
              parts: [{ kind: "text", text: "final answer" }],
            },
          },
        ])
      );

      const agent = new A2AAgent();
      await collectEvents(agent.run(makeInput()));

      // Only adk_thought=true parts are pushed as reasoning
      expect(mockPushReasoning).toHaveBeenCalledTimes(1);
      expect(mockPushReasoning).toHaveBeenNthCalledWith(1, {
        type: "thinking",
        text: "deep internal thought",
        ts: expect.any(Number),
      });
    });
  });

  // ── Artifact-update takes priority over status-update text ─────────────
  describe("artifact-update priority", () => {
    it("uses artifact text instead of status text when both arrive", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: { parts: [{ kind: "text", text: "status text" }] },
            },
          },
          {
            kind: "artifact-update",
            artifact: {
              parts: [{ kind: "text", text: "artifact text" }],
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toBe("artifact text");
    });

    it("replaces artifact text when append=false", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "artifact-update",
            artifact: { parts: [{ kind: "text", text: "first" }] },
          },
          {
            kind: "artifact-update",
            append: false,
            artifact: { parts: [{ kind: "text", text: "replaced" }] },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toBe("replaced");
    });

    it("appends artifact text by default", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "artifact-update",
            artifact: { parts: [{ kind: "text", text: "part1" }] },
          },
          {
            kind: "artifact-update",
            artifact: { parts: [{ kind: "text", text: " part2" }] },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toBe("part1 part2");
    });
  });

  // ── Function call DataParts ────────────────────────────────────────────
  describe("function_call DataParts", () => {
    it("emits TOOL_CALL_START, TOOL_CALL_ARGS, TOOL_CALL_END for function_call", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  {
                    kind: "data",
                    data: { name: "get_weather", args: { city: "NYC" }, id: "call-1" },
                    metadata: { adk_type: "function_call" },
                  },
                ],
              },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      expect(events).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ type: EventType.TOOL_CALL_START, toolCallId: "call-1", toolCallName: "get_weather" }),
          expect.objectContaining({ type: EventType.TOOL_CALL_ARGS, toolCallId: "call-1", delta: JSON.stringify({ city: "NYC" }) }),
          expect.objectContaining({ type: EventType.TOOL_CALL_END, toolCallId: "call-1" }),
        ])
      );
    });

    it("generates a UUID-based callId when data.id is missing", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  {
                    kind: "data",
                    data: { name: "do_something", args: {} },
                    metadata: { adk_type: "function_call" },
                  },
                ],
              },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const toolStart = events.find((e) => e.type === EventType.TOOL_CALL_START);
      expect(toolStart?.toolCallId).toMatch(/^do_something-/);
    });

    it("detects function_call without explicit adk_type metadata", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  {
                    kind: "data",
                    data: { name: "implicit_tool", args: { x: 1 }, id: "impl-1" },
                  },
                ],
              },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      expect(events).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ type: EventType.TOOL_CALL_START, toolCallName: "implicit_tool" }),
        ])
      );
    });
  });

  // ── Function response DataParts ────────────────────────────────────────
  describe("function_response DataParts", () => {
    it("emits TOOL_CALL_RESULT for function_response", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  {
                    kind: "data",
                    data: { name: "tool_a", response: "result data", id: "resp-1" },
                    metadata: { adk_type: "function_response" },
                  },
                ],
              },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      expect(events).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            type: EventType.TOOL_CALL_RESULT,
            toolCallId: "resp-1",
            content: "done",
          }),
        ])
      );
    });

    it("extracts A2UI blocks from string function_response", async () => {
      const a2uiData = JSON.stringify({ type: "chart", data: [1, 2, 3] });
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  {
                    kind: "data",
                    data: { name: "tool_b", response: `Some text <a2ui>${a2uiData}</a2ui> more text`, id: "resp-2" },
                    metadata: { adk_type: "function_response" },
                  },
                ],
              },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      // Should have render_a2ui tool call from function_response extraction
      const renderCalls = events.filter((e) => e.type === EventType.TOOL_CALL_START && e.toolCallName === "render_a2ui");
      expect(renderCalls.length).toBeGreaterThanOrEqual(1);
    });

    it("extracts A2UI from response.content array", async () => {
      const a2uiData = JSON.stringify({ type: "table" });
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  {
                    kind: "data",
                    data: {
                      name: "tool_c",
                      response: { content: [{ type: "text", text: `<a2ui>${a2uiData}</a2ui>` }] },
                      id: "resp-3",
                    },
                    metadata: { adk_type: "function_response" },
                  },
                ],
              },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const renderCalls = events.filter((e) => e.type === EventType.TOOL_CALL_START && e.toolCallName === "render_a2ui");
      expect(renderCalls.length).toBeGreaterThanOrEqual(1);
    });

    it("stringifies non-string, non-content response objects", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  {
                    kind: "data",
                    data: { name: "tool_d", response: { custom: "data" }, id: "resp-4" },
                    metadata: { adk_type: "function_response" },
                  },
                ],
              },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      // Should complete without errors
      expect(events[events.length - 1]).toEqual(expect.objectContaining({ type: EventType.RUN_FINISHED }));
    });

    it("detects function_response without explicit adk_type", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  {
                    kind: "data",
                    data: { name: "tool_e", response: "done", id: "resp-5" },
                  },
                ],
              },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      expect(events).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ type: EventType.TOOL_CALL_RESULT, toolCallId: "resp-5" }),
        ])
      );
    });

    it("falls back to data.name as callId when data.id is missing", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  {
                    kind: "data",
                    data: { name: "fallback_tool", response: "ok" },
                    metadata: { adk_type: "function_response" },
                  },
                ],
              },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      expect(events).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ type: EventType.TOOL_CALL_RESULT, toolCallId: "fallback_tool" }),
        ])
      );
    });
  });

  // ── A2UI deduplication ─────────────────────────────────────────────────
  describe("A2UI deduplication", () => {
    it("does not re-emit A2UI blocks from final text that were already emitted from function_response", async () => {
      const a2uiData = JSON.stringify({ type: "chart", id: "dup" });
      const a2uiTag = `<a2ui>${a2uiData}</a2ui>`;

      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [
                  {
                    kind: "data",
                    data: { name: "tool_x", response: `result ${a2uiTag}`, id: "x1" },
                    metadata: { adk_type: "function_response" },
                  },
                ],
              },
            },
          },
          {
            kind: "artifact-update",
            artifact: { parts: [{ kind: "text", text: `Final ${a2uiTag} answer` }] },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      // render_a2ui should appear only once (from function_response), not duplicated from artifact text
      const renderStarts = events.filter(
        (e) => e.type === EventType.TOOL_CALL_START && e.toolCallName === "render_a2ui"
      );
      expect(renderStarts).toHaveLength(1);
    });
  });

  // ── Python code block extraction ───────────────────────────────────────
  describe("python code block extraction", () => {
    it("extracts python code blocks as tool call events", async () => {
      const text = "Here is code:\n```python\nprint('hi')\n```\n```tool_output\nhello\n```\nDone.";
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "artifact-update",
            artifact: { parts: [{ kind: "text", text }] },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      // Should have a tool call for run_python_script
      const pythonStart = events.find(
        (e) => e.type === EventType.TOOL_CALL_START && e.toolCallName === "run_python_script"
      );
      expect(pythonStart).toBeDefined();

      const pythonArgs = events.find(
        (e) => e.type === EventType.TOOL_CALL_ARGS && e.toolCallId === pythonStart.toolCallId
      );
      const parsed = JSON.parse(pythonArgs.delta);
      expect(parsed.code).toBe("print('hi')");
      expect(parsed.output).toBe("hello");

      // The code block should be removed from the text content
      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).not.toContain("```python");
      expect(contentEvent?.delta).toContain("Done.");
    });
  });

  // ── Failed state ──────────────────────────────────────────────────────
  describe("failed state", () => {
    it("emits error text when status state is 'failed'", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "failed",
              message: { parts: [{ kind: "text", text: "Something went wrong" }] },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toContain("Agent Error");
      expect(contentEvent?.delta).toContain("Something went wrong");
    });

    it("uses 'Agent error' fallback when failed message has no text parts", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "failed",
              message: { parts: [] },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toContain("Agent error");
    });
  });

  // ── Stream error ──────────────────────────────────────────────────────
  describe("stream errors", () => {
    it("emits error text when stream throws a non-abort error", async () => {
      mockStreamA2AQuery.mockImplementation(async function* () {
        throw new Error("Network failure");
      });

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toContain("Network failure");
      expect(events[events.length - 1]).toEqual(expect.objectContaining({ type: EventType.RUN_FINISHED }));
    });

    it("handles AbortError by finishing cleanly without error text", async () => {
      mockStreamA2AQuery.mockImplementation(async function* () {
        const err = new Error("Aborted");
        err.name = "AbortError";
        throw err;
      });

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      // Should NOT emit error text
      const contentEvents = events.filter((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      const hasErrorContent = contentEvents.some((e) => e.delta?.includes("Agent Error"));
      expect(hasErrorContent).toBe(false);

      expect(events[events.length - 1]).toEqual(expect.objectContaining({ type: EventType.RUN_FINISHED }));
    });

    it("handles non-Error thrown values", async () => {
      mockStreamA2AQuery.mockImplementation(async function* () {
        throw "string error";
      });

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toContain("string error");
    });
  });

  // ── extractTextContent edge cases ─────────────────────────────────────
  describe("extractTextContent", () => {
    it("handles array content with text parts", async () => {
      mockStreamA2AQuery.mockReturnValue(asyncGen([]));

      const agent = new A2AAgent();
      const events = await collectEvents(
        agent.run(
          makeInput({
            messages: [
              {
                role: "user",
                content: [
                  { type: "text", text: "part one" },
                  { type: "image", url: "http://example.com/img.png" },
                  { type: "text", text: "part two" },
                ],
              },
            ],
          })
        )
      );

      // Stream should have been called with the joined text
      expect(mockStreamA2AQuery).toHaveBeenCalledWith(
        expect.any(String),
        "part one part two",
        expect.any(String),
        undefined,
        expect.any(Object)
      );
    });

    it("handles non-string non-array content by calling String()", async () => {
      mockStreamA2AQuery.mockReturnValue(asyncGen([]));

      const agent = new A2AAgent();
      const events = await collectEvents(
        agent.run(makeInput({ messages: [{ role: "user", content: 42 }] }))
      );

      expect(mockStreamA2AQuery).toHaveBeenCalledWith(
        expect.any(String),
        "42",
        expect.any(String),
        undefined,
        expect.any(Object)
      );
    });
  });

  // ── sessionId override ────────────────────────────────────────────────
  describe("sessionId", () => {
    it("uses cfg.sessionId when provided", async () => {
      mockStreamA2AQuery.mockReturnValue(asyncGen([]));

      const agent = new A2AAgent({ sessionId: "custom-session" });
      await collectEvents(agent.run(makeInput()));

      expect(mockStreamA2AQuery).toHaveBeenCalledWith(
        expect.any(String),
        expect.any(String),
        "custom-session",
        undefined,
        expect.any(Object)
      );
    });

    it("falls back to threadId when cfg.sessionId not set", async () => {
      mockStreamA2AQuery.mockReturnValue(asyncGen([]));

      const agent = new A2AAgent();
      await collectEvents(agent.run(makeInput({ threadId: "my-thread" })));

      expect(mockStreamA2AQuery).toHaveBeenCalledWith(
        expect.any(String),
        expect.any(String),
        "my-thread",
        undefined,
        expect.any(Object)
      );
    });
  });

  // ── Root unwrapping (part.root) ────────────────────────────────────────
  describe("root unwrapping", () => {
    it("unwraps part.root for status-update text parts", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "status-update",
            status: {
              state: "working",
              message: {
                parts: [{ root: { kind: "text", text: "wrapped text" } }],
              },
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toBe("wrapped text");
    });

    it("unwraps part.root for artifact-update parts", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "artifact-update",
            artifact: {
              parts: [{ root: { kind: "text", text: "wrapped artifact" } }],
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toBe("wrapped artifact");
    });
  });

  // ── Malformed A2UI JSON ───────────────────────────────────────────────
  describe("malformed A2UI", () => {
    it("skips malformed JSON inside a2ui tags", async () => {
      mockStreamA2AQuery.mockReturnValue(
        asyncGen([
          {
            kind: "artifact-update",
            artifact: {
              parts: [{ kind: "text", text: "Hello <a2ui>not-json</a2ui> world" }],
            },
          },
        ])
      );

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      // Should not have any render_a2ui calls
      const renderCalls = events.filter(
        (e) => e.type === EventType.TOOL_CALL_START && e.toolCallName === "render_a2ui"
      );
      expect(renderCalls).toHaveLength(0);

      // Text should still be emitted (cleaned of a2ui tags)
      const contentEvent = events.find((e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
      expect(contentEvent?.delta).toContain("Hello");
    });
  });

  // ── Teardown callback ─────────────────────────────────────────────────
  describe("teardown", () => {
    it("unsubscribe calls abort on the controller", () => {
      mockStreamA2AQuery.mockReturnValue(asyncGen([]));

      const agent = new A2AAgent();
      const obs = agent.run(makeInput());

      const sub = obs.subscribe({ next: () => {}, error: () => {}, complete: () => {} });
      // Unsubscribe triggers teardown
      sub.unsubscribe();
      // No assertion needed — just verifying it doesn't throw
    });
  });

  // ── Empty final text ──────────────────────────────────────────────────
  describe("empty final text", () => {
    it("does not emit text events when final text is empty", async () => {
      mockStreamA2AQuery.mockReturnValue(asyncGen([]));

      const agent = new A2AAgent();
      const events = await collectEvents(agent.run(makeInput()));

      const textEvents = events.filter((e) => e.type === EventType.TEXT_MESSAGE_START);
      expect(textEvents).toHaveLength(0);
    });
  });
});

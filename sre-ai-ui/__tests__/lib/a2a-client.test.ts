import { extractTaskText, sendA2AQuery } from "@/lib/a2a-client";
import type { A2ATask } from "@/types";
import type { UserContext } from "@/lib/a2a-client";

// ---------------------------------------------------------------------------
// Global fetch mock
// ---------------------------------------------------------------------------

global.fetch = jest.fn();
const mockFetch = global.fetch as jest.Mock;

// ---------------------------------------------------------------------------
// Helper: fake timers so polling tests run without real delays
// ---------------------------------------------------------------------------

beforeEach(() => {
  mockFetch.mockReset();
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
});

// ---------------------------------------------------------------------------
// Helper factories
// ---------------------------------------------------------------------------

function makeA2AResponse(task: Partial<A2ATask> & { status: A2ATask["status"] }) {
  return {
    jsonrpc: "2.0" as const,
    id: 1,
    result: {
      id: task.id ?? "task-123",
      status: task.status,
      artifacts: task.artifacts,
      history: task.history,
    } as A2ATask,
  };
}

function makeOkFetch(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  };
}

function makeErrorFetch(status: number, statusText: string) {
  return {
    ok: false,
    status,
    statusText,
    json: async () => ({}),
  };
}

// ---------------------------------------------------------------------------
// extractTaskText
// ---------------------------------------------------------------------------

describe("extractTaskText", () => {
  describe("text from task.status.message.parts", () => {
    it("returns the text part from status.message", () => {
      const task: A2ATask = {
        id: "t1",
        status: {
          state: "completed",
          message: {
            role: "agent",
            parts: [{ type: "text", text: "Status message text" }],
          },
        },
      };

      expect(extractTaskText(task)).toBe("Status message text");
    });

    it("ignores non-text parts in status.message", () => {
      const task: A2ATask = {
        id: "t1",
        status: {
          state: "completed",
          message: {
            role: "agent",
            parts: [{ type: "data", data: { key: "value" } }],
          },
        },
      };

      // Data parts are ignored; no artifacts or history -> fallback message
      expect(extractTaskText(task)).toBe("No response received from agent.");
    });

    it("ignores status.message parts with empty text string", () => {
      const task: A2ATask = {
        id: "t1",
        status: {
          state: "completed",
          message: {
            role: "agent",
            parts: [{ type: "text", text: "" }],
          },
        },
      };

      expect(extractTaskText(task)).toBe("No response received from agent.");
    });
  });

  describe("text from task.artifacts[0].parts", () => {
    it("returns the text part from the first artifact", () => {
      const task: A2ATask = {
        id: "t1",
        status: { state: "completed" },
        artifacts: [
          { parts: [{ type: "text", text: "Artifact text" }] },
        ],
      };

      expect(extractTaskText(task)).toBe("Artifact text");
    });

    it("collects text from all artifacts, not just the first", () => {
      const task: A2ATask = {
        id: "t1",
        status: { state: "completed" },
        artifacts: [
          { parts: [{ type: "text", text: "First artifact" }] },
          { parts: [{ type: "text", text: "Second artifact" }] },
        ],
      };

      expect(extractTaskText(task)).toBe("First artifact\n\nSecond artifact");
    });

    it("ignores non-text parts inside artifacts", () => {
      const task: A2ATask = {
        id: "t1",
        status: { state: "completed" },
        artifacts: [
          { parts: [{ type: "data", data: {} }] },
        ],
      };

      expect(extractTaskText(task)).toBe("No response received from agent.");
    });
  });

  describe("text from last agent message in task.history", () => {
    it("returns text from the last agent message when status and artifacts are empty", () => {
      const task: A2ATask = {
        id: "t1",
        status: { state: "completed" },
        history: [
          { role: "user", parts: [{ type: "text", text: "User question" }] },
          { role: "agent", parts: [{ type: "text", text: "First agent reply" }] },
          { role: "agent", parts: [{ type: "text", text: "Last agent reply" }] },
        ],
      };

      expect(extractTaskText(task)).toBe("Last agent reply");
    });

    it("skips user messages when searching history for agent text", () => {
      const task: A2ATask = {
        id: "t1",
        status: { state: "completed" },
        history: [
          { role: "user", parts: [{ type: "text", text: "User question" }] },
        ],
      };

      // No agent messages in history -> fallback
      expect(extractTaskText(task)).toBe("No response received from agent.");
    });

    it("does not use history when status.message already has text", () => {
      const task: A2ATask = {
        id: "t1",
        status: {
          state: "completed",
          message: {
            role: "agent",
            parts: [{ type: "text", text: "Status wins" }],
          },
        },
        history: [
          { role: "agent", parts: [{ type: "text", text: "History text" }] },
        ],
      };

      // History is only used when parts is still empty after status + artifacts
      expect(extractTaskText(task)).toBe("Status wins");
    });
  });

  describe("fallback when all sources are empty", () => {
    it("returns the sentinel string when no text is anywhere", () => {
      const task: A2ATask = {
        id: "t1",
        status: { state: "completed" },
      };

      expect(extractTaskText(task)).toBe("No response received from agent.");
    });

    it("returns sentinel when history is an empty array", () => {
      const task: A2ATask = {
        id: "t1",
        status: { state: "completed" },
        history: [],
      };

      expect(extractTaskText(task)).toBe("No response received from agent.");
    });
  });

  describe("concatenation of multiple text parts", () => {
    it("joins multiple status.message parts with double newline", () => {
      const task: A2ATask = {
        id: "t1",
        status: {
          state: "completed",
          message: {
            role: "agent",
            parts: [
              { type: "text", text: "Part one" },
              { type: "text", text: "Part two" },
            ],
          },
        },
      };

      expect(extractTaskText(task)).toBe("Part one\n\nPart two");
    });

    it("joins status message parts and artifact parts with double newline", () => {
      const task: A2ATask = {
        id: "t1",
        status: {
          state: "completed",
          message: {
            role: "agent",
            parts: [{ type: "text", text: "Status part" }],
          },
        },
        artifacts: [
          { parts: [{ type: "text", text: "Artifact part" }] },
        ],
      };

      expect(extractTaskText(task)).toBe("Status part\n\nArtifact part");
    });

    it("joins multiple artifact text parts with double newline", () => {
      const task: A2ATask = {
        id: "t1",
        status: { state: "completed" },
        artifacts: [
          {
            parts: [
              { type: "text", text: "Alpha" },
              { type: "text", text: "Beta" },
            ],
          },
        ],
      };

      expect(extractTaskText(task)).toBe("Alpha\n\nBeta");
    });
  });
});

// ---------------------------------------------------------------------------
// sendA2AQuery – request structure
// ---------------------------------------------------------------------------

describe("sendA2AQuery", () => {
  const AGENT_URL = "https://agent.example.com/a2a";

  describe("JSON-RPC request body", () => {
    it("makes a POST to the agentUrl with the correct JSON-RPC envelope", async () => {
      mockFetch.mockResolvedValueOnce(
        makeOkFetch(
          makeA2AResponse({ status: { state: "completed" } })
        )
      );

      await sendA2AQuery(AGENT_URL, "Hello agent");

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [calledUrl, calledInit] = mockFetch.mock.calls[0];
      expect(calledUrl).toBe(AGENT_URL);
      expect(calledInit.method).toBe("POST");

      const body = JSON.parse(calledInit.body);
      expect(body.jsonrpc).toBe("2.0");
      expect(body.method).toBe("message/send");
      expect(body.id).toBe(1);
      expect(body.params.message.role).toBe("user");
      expect(body.params.message.parts).toEqual([
        { type: "text", text: "Hello agent" },
      ]);
    });

    it("sets Content-Type to application/json", async () => {
      mockFetch.mockResolvedValueOnce(
        makeOkFetch(makeA2AResponse({ status: { state: "completed" } }))
      );

      await sendA2AQuery(AGENT_URL, "Hello");

      const [, calledInit] = mockFetch.mock.calls[0];
      expect(calledInit.headers["Content-Type"]).toBe("application/json");
    });
  });

  describe("sessionId in configuration", () => {
    it("includes sessionId in params.configuration when provided", async () => {
      mockFetch.mockResolvedValueOnce(
        makeOkFetch(makeA2AResponse({ status: { state: "completed" } }))
      );

      await sendA2AQuery(AGENT_URL, "Hello", "session-abc");

      const body = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(body.params.configuration.sessionId).toBe("session-abc");
    });

    it("omits sessionId from configuration when not provided", async () => {
      mockFetch.mockResolvedValueOnce(
        makeOkFetch(makeA2AResponse({ status: { state: "completed" } }))
      );

      await sendA2AQuery(AGENT_URL, "Hello");

      const body = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(body.params.configuration).not.toHaveProperty("sessionId");
    });
  });

  describe("user identity via request headers from userCtx.loginId", () => {
    it("includes loginId in request headers when userCtx.loginId is set", async () => {
      mockFetch.mockResolvedValueOnce(
        makeOkFetch(makeA2AResponse({ status: { state: "completed" } }))
      );

      await sendA2AQuery(AGENT_URL, "Hello", undefined, { loginId: "u-42" });

      const [, calledInit] = mockFetch.mock.calls[0];
      expect(calledInit.headers["x-login-id"]).toBe("u-42");
      expect(calledInit.headers["loginId"]).toBe("u-42");
    });

    it("omits user identity headers when userCtx has no loginId", async () => {
      mockFetch.mockResolvedValueOnce(
        makeOkFetch(makeA2AResponse({ status: { state: "completed" } }))
      );

      await sendA2AQuery(AGENT_URL, "Hello", undefined, { userName: "alice" });

      const [, calledInit] = mockFetch.mock.calls[0];
      expect(calledInit.headers).not.toHaveProperty("x-login-id");
      expect(calledInit.headers).not.toHaveProperty("loginId");
    });
  });

  // ---------------------------------------------------------------------------
  // Immediate return for terminal states
  // ---------------------------------------------------------------------------

  describe("immediate return for terminal task states", () => {
    it("returns the task immediately when initial status is 'completed'", async () => {
      const completedTask = makeA2AResponse({
        status: { state: "completed" },
        artifacts: [{ parts: [{ type: "text", text: "Done" }] }],
      });

      mockFetch.mockResolvedValueOnce(makeOkFetch(completedTask));

      const result = await sendA2AQuery(AGENT_URL, "Hello");

      // Only one fetch call – no polling
      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(result.status.state).toBe("completed");
    });

    it("returns the task immediately when initial status is 'failed'", async () => {
      const failedTask = makeA2AResponse({ status: { state: "failed" } });

      mockFetch.mockResolvedValueOnce(makeOkFetch(failedTask));

      const result = await sendA2AQuery(AGENT_URL, "Hello");

      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(result.status.state).toBe("failed");
    });
  });

  // ---------------------------------------------------------------------------
  // Polling when initial state is 'working'
  // ---------------------------------------------------------------------------

  describe("polling when task is initially 'working'", () => {
    it("polls tasks/get and returns once the task reaches 'completed'", async () => {
      const workingResponse = makeA2AResponse({ status: { state: "working" } });
      const completedResponse = makeA2AResponse({
        status: { state: "completed" },
        artifacts: [{ parts: [{ type: "text", text: "Final answer" }] }],
      });

      // First call: tasks/send -> working
      mockFetch.mockResolvedValueOnce(makeOkFetch(workingResponse));
      // Second call: tasks/get -> completed
      mockFetch.mockResolvedValueOnce(
        makeOkFetch({ ...completedResponse, id: 2 })
      );

      const resultPromise = sendA2AQuery(AGENT_URL, "Hello");

      // Advance the fake timer past the poll interval
      await jest.advanceTimersByTimeAsync(1100);

      const result = await resultPromise;

      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(result.status.state).toBe("completed");

      // Verify the second call used tasks/get
      const getBody = JSON.parse(mockFetch.mock.calls[1][1].body);
      expect(getBody.method).toBe("tasks/get");
    });

    it("continues polling across multiple 'working' responses", async () => {
      const workingResponse = makeA2AResponse({ status: { state: "working" } });
      const completedResponse = makeA2AResponse({ status: { state: "completed" } });

      // tasks/send -> working
      mockFetch.mockResolvedValueOnce(makeOkFetch(workingResponse));
      // tasks/get #1 -> still working
      mockFetch.mockResolvedValueOnce(makeOkFetch({ ...workingResponse, id: 2 }));
      // tasks/get #2 -> completed
      mockFetch.mockResolvedValueOnce(makeOkFetch({ ...completedResponse, id: 2 }));

      const resultPromise = sendA2AQuery(AGENT_URL, "Hello");

      // Advance through both poll intervals
      await jest.advanceTimersByTimeAsync(2200);

      const result = await resultPromise;

      expect(mockFetch).toHaveBeenCalledTimes(3);
      expect(result.status.state).toBe("completed");
    });
  });

  // ---------------------------------------------------------------------------
  // Error handling
  // ---------------------------------------------------------------------------

  describe("error handling", () => {
    it("throws when the initial JSON-RPC response has an error field", async () => {
      const errorResponse = {
        jsonrpc: "2.0",
        id: 1,
        error: { code: -32600, message: "Invalid request" },
      };

      mockFetch.mockResolvedValueOnce(makeOkFetch(errorResponse));

      await expect(sendA2AQuery(AGENT_URL, "Hello")).rejects.toThrow(
        "A2A send error: Invalid request"
      );
    });

    it("throws when the HTTP response is non-200 (e.g. 503)", async () => {
      mockFetch.mockResolvedValueOnce(makeErrorFetch(503, "Service Unavailable"));

      // Error format: "HTTP <status> <statusText> — <url> — body: <body>"
      // makeErrorFetch does not define .text(), so body resolves to "(unreadable)"
      await expect(sendA2AQuery(AGENT_URL, "Hello")).rejects.toThrow(
        "HTTP 503 Service Unavailable"
      );
    });

    it("throws when a poll response has an error field", async () => {
      const workingResponse = makeA2AResponse({ status: { state: "working" } });
      const pollErrorResponse = {
        jsonrpc: "2.0",
        id: 2,
        error: { code: -32000, message: "Server error during poll" },
      };

      mockFetch.mockResolvedValueOnce(makeOkFetch(workingResponse));
      mockFetch.mockResolvedValueOnce(makeOkFetch(pollErrorResponse));

      // Attach the rejection handler before advancing timers so the rejection
      // is never unhandled between the throw and the assertion.
      const resultPromise = sendA2AQuery(AGENT_URL, "Hello");
      const assertion = expect(resultPromise).rejects.toThrow(
        "A2A poll error: Server error during poll"
      );

      await jest.advanceTimersByTimeAsync(1100);
      await assertion;
    });

    it("throws when a poll returns a 'canceled' task state", async () => {
      const workingResponse = makeA2AResponse({ status: { state: "working" } });
      const canceledResponse = makeA2AResponse({ status: { state: "canceled" } });

      mockFetch.mockResolvedValueOnce(makeOkFetch(workingResponse));
      mockFetch.mockResolvedValueOnce(makeOkFetch({ ...canceledResponse, id: 2 }));

      // Attach the rejection handler before advancing timers.
      const resultPromise = sendA2AQuery(AGENT_URL, "Hello");
      const assertion = expect(resultPromise).rejects.toThrow(
        "Task was canceled by the agent"
      );

      await jest.advanceTimersByTimeAsync(1100);
      await assertion;
    });
  });

  // ---------------------------------------------------------------------------
  // User context headers
  // ---------------------------------------------------------------------------

  describe("user context headers", () => {
    async function captureHeaders(userCtx?: UserContext) {
      mockFetch.mockResolvedValueOnce(
        makeOkFetch(makeA2AResponse({ status: { state: "completed" } }))
      );
      await sendA2AQuery(AGENT_URL, "Hello", undefined, userCtx);
      return mockFetch.mock.calls[0][1].headers as Record<string, string>;
    }

    it("sets wm_llm_gw.user_type from userCtx.userType", async () => {
      const headers = await captureHeaders({ userType: "associate" });
      expect(headers["wm_llm_gw.user_type"]).toBe("associate");
    });

    it("sets wm_llm_gw.user_name from userCtx.loginId (user identifier, not display name)", async () => {
      const headers = await captureHeaders({ loginId: "alice@walmart.com" });
      expect(headers["wm_llm_gw.user_name"]).toBe("alice@walmart.com");
    });

    it("sets wm_llm_gw.user_ip from userCtx.userIp", async () => {
      const headers = await captureHeaders({ userIp: "10.0.0.1" });
      expect(headers["wm_llm_gw.user_ip"]).toBe("10.0.0.1");
    });

    it("sets wm_llm_gw.user_agent from userCtx.userAgent", async () => {
      const headers = await captureHeaders({ userAgent: "Mozilla/5.0" });
      expect(headers["wm_llm_gw.user_agent"]).toBe("Mozilla/5.0");
    });

    it("sets loginId from userCtx.loginId", async () => {
      const headers = await captureHeaders({ loginId: "login-xyz" });
      expect(headers["loginId"]).toBe("login-xyz");
    });

    it("includes all user headers when every field is provided", async () => {
      const fullCtx: UserContext = {
        userId: "u-1",
        userName: "bob",
        userType: "manager",
        userAgent: "TestAgent/1.0",
        userIp: "192.168.1.1",
        loginId: "bob@example.com",
        accessToken: "dummy",
      };

      const headers = await captureHeaders(fullCtx);

      expect(headers["wm_llm_gw.user_type"]).toBe("manager");
      expect(headers["wm_llm_gw.user_name"]).toBe("bob@example.com"); // USER_NAME sourced from loginId
      expect(headers["wm_llm_gw.user_ip"]).toBe("192.168.1.1");
      expect(headers["wm_llm_gw.user_agent"]).toBe("TestAgent/1.0");
      expect(headers["loginId"]).toBe("bob@example.com");
    });

    it("sends no user-specific headers when userCtx is undefined", async () => {
      const headers = await captureHeaders(undefined);

      expect(headers).not.toHaveProperty("wm_llm_gw.user_type");
      expect(headers).not.toHaveProperty("wm_llm_gw.user_name");
      expect(headers).not.toHaveProperty("wm_llm_gw.user_ip");
      expect(headers).not.toHaveProperty("wm_llm_gw.user_agent");
      expect(headers).not.toHaveProperty("loginId");
      expect(headers).not.toHaveProperty("Authorization");
      // Content-Type is always present
      expect(headers["Content-Type"]).toBe("application/json");
    });

    it("omits individual header keys whose values are undefined", async () => {
      // Provide a partial context – only loginId is set (USER_NAME comes from loginId)
      const headers = await captureHeaders({ loginId: "carol@walmart.com" });

      expect(headers["wm_llm_gw.user_name"]).toBe("carol@walmart.com");
      expect(headers["loginId"]).toBe("carol@walmart.com");
      expect(headers).not.toHaveProperty("wm_llm_gw.user_type");
      expect(headers).not.toHaveProperty("wm_llm_gw.user_ip");
      expect(headers).not.toHaveProperty("wm_llm_gw.user_agent");
      expect(headers).not.toHaveProperty("Authorization");
    });

    it("does NOT set wm_llm_gw.user_name when only userName is provided (loginId is required)", async () => {
      const headers = await captureHeaders({ userName: "carol" });

      expect(headers).not.toHaveProperty("wm_llm_gw.user_name");
      expect(headers).not.toHaveProperty("loginId");
    });
  });
});

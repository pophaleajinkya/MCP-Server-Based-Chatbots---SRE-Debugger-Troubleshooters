/**
 * Comprehensive tests for all exported functions in chat-helpers.ts.
 * Aims for 100% line/branch coverage of src/lib/chat-helpers.ts.
 */

import { toolLabel, toolArgPreview, groupIntoTurns, buildMessagesFromEvents } from "@/lib/chat-helpers";
import type { Turn, AssistantSegment } from "@/lib/chat-helpers";
import type { SessionUiEvent } from "@/types";
import { TextMessage, ActionExecutionMessage } from "@copilotkit/runtime-client-gql";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function userMsg(content: string | unknown[], id = "u1", extra: Record<string, unknown> = {}) {
  return { role: "user", content, id, ...extra };
}

function assistantMsg(content: string, id = "a1", extra: Record<string, unknown> = {}) {
  return { role: "assistant", content, id, ...extra };
}

function actionExecMsg(name: string, args: Record<string, unknown>, id = "ae1") {
  return { type: "ActionExecutionMessage", id, name, arguments: args };
}

type UserTurn = Turn & { type: "user" };
type AssistantTurn = Turn & { type: "assistant" };

// ─── toolLabel ────────────────────────────────────────────────────────────────

describe("toolLabel", () => {
  it("returns known label for mapped tool names", () => {
    expect(toolLabel("wcnp_check_app_health")).toBe("Check App Health");
    expect(toolLabel("render_chart")).toBe("Render Chart");
    expect(toolLabel("get_mcp_prompt")).toBe("Load Workflow Guide");
  });

  it("formats unknown tool names by replacing underscores and capitalising", () => {
    expect(toolLabel("my_custom_tool")).toBe("My Custom Tool");
    expect(toolLabel("single")).toBe("Single");
  });
});

// ─── toolArgPreview ───────────────────────────────────────────────────────────

describe("toolArgPreview", () => {
  it("returns key=value pairs for simple args", () => {
    expect(toolArgPreview({ app: "foo", ns: "bar" })).toBe("app=foo  ns=bar");
  });

  it("skips keys in the skip set", () => {
    const result = toolArgPreview({ format: "json", output_format: "csv", include_details: true, clusters: ["a"], app: "myapp" });
    expect(result).toBe("app=myapp");
  });

  it("skips undefined, null, and empty string values", () => {
    expect(toolArgPreview({ a: undefined, b: null, c: "", d: "val" })).toBe("d=val");
  });

  it("limits to 3 entries", () => {
    const result = toolArgPreview({ a: "1", b: "2", c: "3", d: "4" });
    expect(result).toBe("a=1  b=2  c=3");
  });

  it("truncates long string values at 40 chars", () => {
    const longVal = "x".repeat(60);
    const result = toolArgPreview({ key: longVal });
    expect(result).toBe(`key=${"x".repeat(40)}`);
  });

  it("serialises nested objects to JSON", () => {
    const result = toolArgPreview({ data: { nested: true } });
    expect(result).toBe('data={"nested":true}');
  });

  it("serialises arrays to JSON", () => {
    const result = toolArgPreview({ items: [1, 2, 3] });
    expect(result).toBe("items=[1,2,3]");
  });

  it("returns empty string for empty args", () => {
    expect(toolArgPreview({})).toBe("");
  });
});

// ─── groupIntoTurns ───────────────────────────────────────────────────────────

describe("groupIntoTurns", () => {
  it("returns empty array for null/undefined/empty", () => {
    expect(groupIntoTurns(null)).toEqual([]);
    expect(groupIntoTurns(undefined)).toEqual([]);
    expect(groupIntoTurns([])).toEqual([]);
  });

  // --- User messages ---

  it("handles user message with string content", () => {
    const turns = groupIntoTurns([userMsg("hello")]);
    expect(turns).toHaveLength(1);
    expect(turns[0].type).toBe("user");
    expect((turns[0] as UserTurn).content).toBe("hello");
  });

  it("handles user message with array content (text parts)", () => {
    const content = [
      { type: "text", text: "part one" },
      { type: "image", url: "http://img.png" },
      { type: "text", text: "part two" },
    ];
    const turns = groupIntoTurns([userMsg(content)]);
    expect(turns).toHaveLength(1);
    expect((turns[0] as UserTurn).content).toBe("part one part two");
  });

  it("handles user message with non-string non-array content (fallback)", () => {
    const turns = groupIntoTurns([userMsg(42 as unknown as string)]);
    expect(turns).toHaveLength(1);
    expect((turns[0] as UserTurn).content).toBe("42");
  });

  it("extracts timestamp from event_ts (Unix seconds)", () => {
    const turns = groupIntoTurns([userMsg("hi", "u1", { event_ts: 1700000000 })]);
    const turn = turns[0] as UserTurn;
    expect(turn.timestamp).toEqual(new Date(1700000000 * 1000));
  });

  it("extracts timestamp from createdAt when event_ts is absent", () => {
    const date = new Date("2024-01-15T10:00:00Z");
    const turns = groupIntoTurns([userMsg("hi", "u1", { createdAt: date })]);
    const turn = turns[0] as UserTurn;
    expect(turn.timestamp).toEqual(date);
  });

  it("sets timestamp to undefined when neither event_ts nor createdAt", () => {
    const turns = groupIntoTurns([userMsg("hi")]);
    expect((turns[0] as UserTurn).timestamp).toBeUndefined();
  });

  it("attaches userId and userName from message", () => {
    const turns = groupIntoTurns([userMsg("hi", "u1", { user_id: "uid1", user_name: "Alice" })]);
    const turn = turns[0] as UserTurn;
    expect(turn.userId).toBe("uid1");
    expect(turn.userName).toBe("Alice");
  });

  // --- Skipped roles ---

  it("skips tool, system, and activity role messages", () => {
    const msgs = [
      { role: "tool", content: "result", id: "t1" },
      { role: "system", content: "sys", id: "s1" },
      { role: "activity", content: "act", id: "ac1" },
    ];
    expect(groupIntoTurns(msgs)).toEqual([]);
  });

  // --- ActionExecutionMessage ---

  it("handles render_a2ui ActionExecutionMessage", () => {
    const msg = actionExecMsg("render_a2ui", { a2ui: { component: "Chart" } });
    const turns = groupIntoTurns([msg]);
    expect(turns).toHaveLength(1);
    const asst = turns[0] as AssistantTurn;
    expect(asst.segments).toHaveLength(1);
    expect(asst.segments[0].kind).toBe("a2ui");
    expect((asst.segments[0] as { kind: "a2ui"; data: unknown }).data).toEqual({ component: "Chart" });
  });

  it("handles run_python_script ActionExecutionMessage", () => {
    const msg = actionExecMsg("run_python_script", { code: "print(1)", output: "1" });
    const turns = groupIntoTurns([msg]);
    const asst = turns[0] as AssistantTurn;
    expect(asst.segments).toHaveLength(1);
    expect(asst.segments[0].kind).toBe("code");
    const seg = asst.segments[0] as { kind: "code"; code: string; output: string };
    expect(seg.code).toBe("print(1)");
    expect(seg.output).toBe("1");
  });

  it("handles generic MCP tool ActionExecutionMessage", () => {
    const msg = actionExecMsg("wcnp_check_app_health", { app: "myapp" });
    const turns = groupIntoTurns([msg]);
    const asst = turns[0] as AssistantTurn;
    expect(asst.segments).toHaveLength(1);
    expect(asst.segments[0].kind).toBe("tool");
    const seg = asst.segments[0] as { kind: "tool"; name: string; args: Record<string, unknown> };
    expect(seg.name).toBe("wcnp_check_app_health");
    expect(seg.args).toEqual({ app: "myapp" });
  });

  it("ignores ActionExecutionMessage with render_a2ui but no a2ui in args", () => {
    const msg = actionExecMsg("render_a2ui", { other: "data" });
    const turns = groupIntoTurns([msg]);
    const asst = turns[0] as AssistantTurn;
    expect(asst.segments).toHaveLength(0);
  });

  it("handles ActionExecutionMessage with no name", () => {
    const msg = { type: "ActionExecutionMessage", id: "ae1", arguments: {} };
    const turns = groupIntoTurns([msg]);
    // Should still create an assistant turn but no segments (name is undefined)
    const asst = turns[0] as AssistantTurn;
    expect(asst.segments).toHaveLength(0);
  });

  it("handles run_python_script with missing code/output args", () => {
    const msg = actionExecMsg("run_python_script", {});
    const turns = groupIntoTurns([msg]);
    const seg = (turns[0] as AssistantTurn).segments[0] as { kind: "code"; code: string; output: string };
    expect(seg.code).toBe("");
    expect(seg.output).toBe("");
  });

  // --- Assistant messages ---

  it("groups consecutive assistant messages into one turn", () => {
    const msgs = [
      assistantMsg("Hello", "a1"),
      assistantMsg("World", "a2"),
    ];
    const turns = groupIntoTurns(msgs);
    expect(turns).toHaveLength(1);
    const asst = turns[0] as AssistantTurn;
    expect(asst.segments).toHaveLength(2);
    expect((asst.segments[0] as { kind: "text"; content: string }).content).toBe("Hello");
    expect((asst.segments[1] as { kind: "text"; content: string }).content).toBe("World");
  });

  it("skips empty assistant content", () => {
    const turns = groupIntoTurns([assistantMsg("", "a1")]);
    expect(turns).toHaveLength(1);
    const asst = turns[0] as AssistantTurn;
    expect(asst.segments).toHaveLength(0);
  });

  it("flushes assistant turn when user message follows", () => {
    const msgs = [
      assistantMsg("response"),
      userMsg("question"),
    ];
    const turns = groupIntoTurns(msgs);
    expect(turns).toHaveLength(2);
    expect(turns[0].type).toBe("assistant");
    expect(turns[1].type).toBe("user");
  });

  // --- Assistant toolCalls ---

  it("handles assistant toolCalls with render_a2ui", () => {
    const msg = {
      role: "assistant",
      id: "a1",
      content: "",
      toolCalls: [{
        id: "tc1",
        function: { name: "render_a2ui", arguments: JSON.stringify({ a2ui: { chart: true } }) },
      }],
    };
    const turns = groupIntoTurns([msg]);
    const asst = turns[0] as AssistantTurn;
    const a2uiSeg = asst.segments.find(s => s.kind === "a2ui");
    expect(a2uiSeg).toBeDefined();
    expect((a2uiSeg as { kind: "a2ui"; data: unknown }).data).toEqual({ chart: true });
  });

  it("handles assistant toolCalls with run_python_script", () => {
    const msg = {
      role: "assistant",
      id: "a1",
      content: "",
      toolCalls: [{
        id: "tc1",
        function: { name: "run_python_script", arguments: JSON.stringify({ code: "x=1", output: "done" }) },
      }],
    };
    const turns = groupIntoTurns([msg]);
    const asst = turns[0] as AssistantTurn;
    const codeSeg = asst.segments.find(s => s.kind === "code") as { kind: "code"; code: string; output: string };
    expect(codeSeg.code).toBe("x=1");
    expect(codeSeg.output).toBe("done");
  });

  it("handles assistant toolCalls with generic MCP tool", () => {
    const msg = {
      role: "assistant",
      id: "a1",
      content: "",
      toolCalls: [{
        id: "tc1",
        function: { name: "wcnp_query_prometheus", arguments: JSON.stringify({ query: "up" }) },
      }],
    };
    const turns = groupIntoTurns([msg]);
    const asst = turns[0] as AssistantTurn;
    const toolSeg = asst.segments.find(s => s.kind === "tool") as { kind: "tool"; name: string; args: Record<string, unknown> };
    expect(toolSeg.name).toBe("wcnp_query_prometheus");
    expect(toolSeg.args).toEqual({ query: "up" });
  });

  it("skips toolCall with malformed JSON arguments", () => {
    const msg = {
      role: "assistant",
      id: "a1",
      content: "text",
      toolCalls: [{
        id: "tc1",
        function: { name: "some_tool", arguments: "NOT_JSON{{{" },
      }],
    };
    const turns = groupIntoTurns([msg]);
    const asst = turns[0] as AssistantTurn;
    // Only the text segment, no tool segment
    expect(asst.segments).toHaveLength(1);
    expect(asst.segments[0].kind).toBe("text");
  });

  it("handles render_a2ui toolCall without a2ui key in args", () => {
    const msg = {
      role: "assistant",
      id: "a1",
      content: "",
      toolCalls: [{
        id: "tc1",
        function: { name: "render_a2ui", arguments: JSON.stringify({ other: "stuff" }) },
      }],
    };
    const turns = groupIntoTurns([msg]);
    const asst = turns[0] as AssistantTurn;
    expect(asst.segments.filter(s => s.kind === "a2ui")).toHaveLength(0);
  });

  it("handles toolCall with empty arguments string", () => {
    const msg = {
      role: "assistant",
      id: "a1",
      content: "",
      toolCalls: [{
        id: "tc1",
        function: { name: "some_tool", arguments: "" },
      }],
    };
    const turns = groupIntoTurns([msg]);
    const asst = turns[0] as AssistantTurn;
    const toolSeg = asst.segments.find(s => s.kind === "tool");
    expect(toolSeg).toBeDefined();
  });

  it("skips toolCall with no name", () => {
    const msg = {
      role: "assistant",
      id: "a1",
      content: "",
      toolCalls: [{
        id: "tc1",
        function: { name: "", arguments: "{}" },
      }],
    };
    const turns = groupIntoTurns([msg]);
    const asst = turns[0] as AssistantTurn;
    expect(asst.segments).toHaveLength(0);
  });

  // --- Mixed scenario ---

  it("handles a full conversation with mixed message types", () => {
    const msgs = [
      userMsg("Hello"),
      assistantMsg("Hi there"),
      actionExecMsg("wcnp_check_app_health", { app: "myapp" }),
      userMsg("Thanks", "u2"),
    ];
    const turns = groupIntoTurns(msgs);
    expect(turns).toHaveLength(3);
    expect(turns[0].type).toBe("user");
    expect(turns[1].type).toBe("assistant");
    expect(turns[2].type).toBe("user");
    // The assistant turn should have text + tool segments
    const asst = turns[1] as AssistantTurn;
    expect(asst.segments).toHaveLength(2);
  });
});

// ─── buildMessagesFromEvents ──────────────────────────────────────────────────

describe("buildMessagesFromEvents", () => {
  it("converts user events to TextMessages with metadata", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1700000000, text: "hello", user_id: "u1", user_name: "Alice" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(1);
    expect(TextMessage).toHaveBeenCalledWith(expect.objectContaining({
      role: "user",
      content: "hello",
    }));
    const meta = msgs[0] as unknown as Record<string, unknown>;
    expect(meta["user_id"]).toBe("u1");
    expect(meta["user_name"]).toBe("Alice");
    expect(meta["event_ts"]).toBe(1700000000);
  });

  it("converts complete events to assistant TextMessages", () => {
    const events: SessionUiEvent[] = [
      { type: "complete", ts: 1, text: "response text" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(1);
    expect(TextMessage).toHaveBeenCalledWith(expect.objectContaining({
      role: "assistant",
      content: "response text",
    }));
  });

  it("skips complete events with empty text", () => {
    const events: SessionUiEvent[] = [
      { type: "complete", ts: 1, text: "" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(0);
  });

  it("converts artifact-update events to assistant messages", () => {
    const events: SessionUiEvent[] = [
      { type: "artifact-update", ts: 1, text: "artifact content", kind: "artifact-update" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(1);
    expect(TextMessage).toHaveBeenCalledWith(expect.objectContaining({
      role: "assistant",
      content: "artifact content",
    }));
  });

  it("buffers status-update text and flushes at end", () => {
    const events: SessionUiEvent[] = [
      { type: "status-update", ts: 1, text: "first update", kind: "status-update" },
      { type: "status-update", ts: 2, text: "second update", kind: "status-update" },
    ];
    const msgs = buildMessagesFromEvents(events);
    // Only the last status-update text should be flushed
    expect(msgs).toHaveLength(1);
    expect(TextMessage).toHaveBeenCalledWith(expect.objectContaining({
      content: "second update",
    }));
  });

  it("flushes status-update buffer before user messages", () => {
    const events: SessionUiEvent[] = [
      { type: "status-update", ts: 1, text: "status", kind: "status-update" },
      { type: "user", ts: 2, text: "question" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(2);
    // First should be the flushed status, second the user
  });

  it("flushes status-update buffer then emits complete event", () => {
    const events: SessionUiEvent[] = [
      { type: "status-update", ts: 1, text: "buffered", kind: "status-update" },
      { type: "complete", ts: 2, text: "authoritative" },
    ];
    const msgs = buildMessagesFromEvents(events);
    // flushStatusBuf emits the buffered text, then complete emits its own
    expect(msgs).toHaveLength(2);
    expect(TextMessage).toHaveBeenLastCalledWith(expect.objectContaining({
      content: "authoritative",
    }));
  });

  it("flushes status-update buffer before artifact-update", () => {
    const events: SessionUiEvent[] = [
      { type: "status-update", ts: 1, text: "buffered", kind: "status-update" },
      { type: "artifact-update", ts: 2, text: "artifact", kind: "artifact-update" },
    ];
    const msgs = buildMessagesFromEvents(events);
    // buffered status flushed, then artifact
    expect(msgs).toHaveLength(2);
  });

  it("converts progress events to ActionExecutionMessages", () => {
    const events: SessionUiEvent[] = [
      { type: "progress", ts: 1, tool: "wcnp_check_app_health", status: "running", args: { app: "myapp" } },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(1);
    expect(ActionExecutionMessage).toHaveBeenCalledWith(expect.objectContaining({
      name: "wcnp_check_app_health",
      arguments: { app: "myapp" },
    }));
  });

  it("handles progress event with no args", () => {
    const events: SessionUiEvent[] = [
      { type: "progress", ts: 1, tool: "some_tool", status: "running" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(1);
    expect(ActionExecutionMessage).toHaveBeenCalledWith(expect.objectContaining({
      arguments: {},
    }));
  });

  it("ignores graph events", () => {
    const events: SessionUiEvent[] = [
      { type: "graph", ts: 1 },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(0);
  });

  it("renders error events as assistant messages with warning prefix", () => {
    const events: SessionUiEvent[] = [
      { type: "error", ts: 1, message: "something failed" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(1);
    expect(msgs[0].role).toBe("assistant");
    expect(msgs[0].content).toBe("⚠️ something failed");
  });

  it("extracts <a2ui> blocks from complete event text", () => {
    const a2uiData = JSON.stringify({ component: "Chart", props: {} });
    const text = `Some intro text <a2ui>${a2uiData}</a2ui> more text`;
    const events: SessionUiEvent[] = [
      { type: "complete", ts: 1, text },
    ];
    const msgs = buildMessagesFromEvents(events);
    // Should produce: ActionExecutionMessage for a2ui + TextMessage for remaining text
    expect(msgs).toHaveLength(2);
    expect(ActionExecutionMessage).toHaveBeenCalledWith(expect.objectContaining({
      name: "render_a2ui",
      arguments: { a2ui: { component: "Chart", props: {} } },
    }));
  });

  it("handles <a2ui> blocks with malformed JSON gracefully", () => {
    const text = `text <a2ui>NOT_VALID_JSON</a2ui> more text`;
    const events: SessionUiEvent[] = [
      { type: "complete", ts: 1, text },
    ];
    // Should not throw; malformed a2ui block skipped, text still emitted
    const msgs = buildMessagesFromEvents(events);
    expect(msgs.length).toBeGreaterThanOrEqual(1);
  });

  it("handles user event without user_id, user_name, or ts", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 0, text: "hi" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(1);
    const meta = msgs[0] as unknown as Record<string, unknown>;
    // user_id and user_name should not be set
    expect(meta["user_id"]).toBeUndefined();
    expect(meta["user_name"]).toBeUndefined();
  });

  it("handles a full session replay with mixed events", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "check my app", user_id: "u1", user_name: "Bob" },
      { type: "progress", ts: 2, tool: "wcnp_check_app_health", status: "running", args: { app: "myapp" } },
      { type: "complete", ts: 3, text: "Your app is healthy." },
      { type: "user", ts: 4, text: "thanks" },
      { type: "status-update", ts: 5, text: "processing", kind: "status-update" },
    ];
    const msgs = buildMessagesFromEvents(events);
    // user + progress + complete + user + flushed status
    expect(msgs).toHaveLength(5);
  });

  it("handles status-update with empty text (does not flush)", () => {
    const events: SessionUiEvent[] = [
      { type: "status-update", ts: 1, text: "", kind: "status-update" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(0);
  });

  it("handles artifact-update with no text (skipped)", () => {
    const events: SessionUiEvent[] = [
      { type: "artifact-update", ts: 1, kind: "artifact-update" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(0);
  });

  it("handles progress event without tool (skipped)", () => {
    const events: SessionUiEvent[] = [
      { type: "progress", ts: 1, status: "running" },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(0);
  });

  it("handles user event with no text", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1 },
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs).toHaveLength(1);
    expect(TextMessage).toHaveBeenCalledWith(expect.objectContaining({
      content: "",
    }));
  });

  it("handles complete event with no text", () => {
    const events: SessionUiEvent[] = [
      { type: "complete", ts: 1 },
    ];
    const msgs = buildMessagesFromEvents(events);
    // flushAssistant("") returns early due to !text.trim()
    expect(msgs).toHaveLength(0);
  });

  it("extracts multiple <a2ui> blocks from same text", () => {
    const block1 = JSON.stringify({ type: "chart1" });
    const block2 = JSON.stringify({ type: "chart2" });
    const text = `intro <a2ui>${block1}</a2ui> middle <a2ui>${block2}</a2ui> end`;
    const events: SessionUiEvent[] = [
      { type: "complete", ts: 1, text },
    ];
    const msgs = buildMessagesFromEvents(events);
    // 2 ActionExecutionMessages + 1 TextMessage for remaining text
    expect(msgs).toHaveLength(3);
  });

  it("handles text that is only <a2ui> blocks with no remaining clean text", () => {
    const block = JSON.stringify({ type: "chart" });
    const text = `<a2ui>${block}</a2ui>`;
    const events: SessionUiEvent[] = [
      { type: "complete", ts: 1, text },
    ];
    const msgs = buildMessagesFromEvents(events);
    // Only 1 ActionExecutionMessage, no TextMessage (cleanText is empty)
    expect(msgs).toHaveLength(1);
    expect(ActionExecutionMessage).toHaveBeenCalled();
  });
});

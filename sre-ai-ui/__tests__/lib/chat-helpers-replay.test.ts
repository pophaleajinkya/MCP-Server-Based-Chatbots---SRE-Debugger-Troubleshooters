/**
 * Tests for session replay — buildMessagesFromEvents.
 *
 * Covers:
 *   1. Event ordering: thinking/progress before user → reattached to correct turn
 *   2. Chart replay: render_chart progress → render_a2ui ActionExecutionMessage
 *   3. Table replay: render_table_data progress → render_a2ui
 *   4. Multi-chart replay: render_multi_chart progress
 *   5. Thinking events: buffered after complete, emitted after next user
 *   6. Multi-turn ordering
 *   7. Edge cases: empty args, missing labels, done status, no tool
 */

import { buildMessagesFromEvents } from "@/lib/chat-helpers";
import type { SessionUiEvent } from "@/types";
import { TextMessage, ActionExecutionMessage } from "@copilotkit/runtime-client-gql";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function findByName(msgs: unknown[], name: string): unknown[] {
  return msgs.filter((m: any) => m.name === name || m.arguments?.type === name);
}

function msgTypes(msgs: unknown[]): string[] {
  return msgs.map((m: any) => {
    if (m.role === "user") return "user";
    if (m.role === "assistant") return "assistant";
    if (m.name === "render_a2ui") return "render_a2ui";
    if (m.name === "emit_reasoning") return "emit_reasoning";
    if (m.name) return `tool:${m.name}`;
    return "unknown";
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// 1. Chart Replay (render_chart → render_a2ui)
// ═══════════════════════════════════════════════════════════════════════════════

describe("buildMessagesFromEvents – chart replay", () => {
  it("converts render_chart progress to render_a2ui ActionExecutionMessage", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "show chart" },
      {
        type: "progress", ts: 2, tool: "render_chart", status: "running",
        args: {
          title: "Memory p90", chart_type: "line",
          labels: ["Day 1", "Day 2"],
          datasets: [{ label: "eus2", data: [86.4, 86.5] }],
        },
      },
      { type: "complete", ts: 3, text: "Here is the chart." },
    ];
    const msgs = buildMessagesFromEvents(events);

    // Should have: user + tool chip + render_a2ui + complete text
    const a2uiMsgs = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2uiMsgs.length).toBe(1);

    const args = (a2uiMsgs[0] as any).arguments;
    expect(args.a2ui).toBeDefined();
    expect(args.a2ui[0].component).toBe("Chart");
    expect(args.a2ui[0].chartType).toBe("line");
    expect(args.a2ui[0].title).toBe("Memory p90");
    expect(args.a2ui[0].xAxis.labels).toEqual(["Day 1", "Day 2"]);
    expect(args.a2ui[0].series[0].label).toBe("eus2");
    expect(args.a2ui[0].series[0].data).toEqual([86.4, 86.5]);
  });

  it("also emits the tool chip alongside the a2ui block", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "show chart" },
      {
        type: "progress", ts: 2, tool: "render_chart", status: "running",
        args: { labels: ["a"], datasets: [{ label: "x", data: [1] }] },
      },
      { type: "complete", ts: 3, text: "Done." },
    ];
    const msgs = buildMessagesFromEvents(events);
    const chipMsgs = msgs.filter((m: any) => m.name === "render_chart");
    expect(chipMsgs.length).toBe(1);
  });

  it("uses xAxis.labels when labels is missing", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_chart", status: "running",
        args: {
          chartType: "bar",
          xAxis: { labels: ["Mon", "Tue"] },
          series: [{ name: "mem", data: [80, 82] }],
        },
      },
      { type: "complete", ts: 3, text: "Done" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(1);
    expect((a2ui[0] as any).arguments.a2ui[0].xAxis.labels).toEqual(["Mon", "Tue"]);
  });

  it("skips chart a2ui when labels array is empty", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_chart", status: "running",
        args: { labels: [], datasets: [] },
      },
      { type: "complete", ts: 3, text: "Done" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(0);
    // But the chip should still be there
    const chip = msgs.filter((m: any) => m.name === "render_chart");
    expect(chip.length).toBe(1);
  });

  it("uses chartType field when chart_type is absent", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_chart", status: "running",
        args: { chartType: "bar", labels: ["a"], datasets: [{ label: "x", data: [1] }] },
      },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(1);
    expect((a2ui[0] as any).arguments.a2ui[0].chartType).toBe("bar");
  });

  it("defaults chartType to 'line' when neither field present", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_chart", status: "running",
        args: { labels: ["a"], datasets: [{ label: "x", data: [1] }] },
      },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect((a2ui[0] as any).arguments.a2ui[0].chartType).toBe("line");
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 2. Multi-chart replay
// ═══════════════════════════════════════════════════════════════════════════════

describe("buildMessagesFromEvents – render_multi_chart replay", () => {
  it("converts render_multi_chart with charts array to multiple a2ui chart blocks", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_multi_chart", status: "running",
        args: {
          charts: [
            { title: "Chart 1", labels: ["a", "b"], datasets: [{ label: "s1", data: [1, 2] }] },
            { title: "Chart 2", labels: ["c", "d"], datasets: [{ label: "s2", data: [3, 4] }] },
          ],
        },
      },
      { type: "complete", ts: 3, text: "Done" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(1);
    const blocks = (a2ui[0] as any).arguments.a2ui;
    expect(blocks.length).toBe(2);
    expect(blocks[0].title).toBe("Chart 1");
    expect(blocks[1].title).toBe("Chart 2");
  });

  it("filters out charts with empty labels from multi_chart", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_multi_chart", status: "running",
        args: {
          charts: [
            { title: "Valid", labels: ["a"], datasets: [{ label: "s", data: [1] }] },
            { title: "Empty", labels: [], datasets: [] },
          ],
        },
      },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(1);
    expect((a2ui[0] as any).arguments.a2ui.length).toBe(1);
    expect((a2ui[0] as any).arguments.a2ui[0].title).toBe("Valid");
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 3. Table replay
// ═══════════════════════════════════════════════════════════════════════════════

describe("buildMessagesFromEvents – render_table_data replay", () => {
  it("converts render_table_data progress to render_a2ui Table block", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_table_data", status: "running",
        args: {
          columns: ["Name", "Status"],
          rows: [["app1", "healthy"], ["app2", "degraded"]],
        },
      },
      { type: "complete", ts: 3, text: "Table above" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(1);
    const block = (a2ui[0] as any).arguments.a2ui[0];
    expect(block.component).toBe("Table");
    expect(block.columns).toEqual(["Name", "Status"]);
    expect(block.rows).toEqual([["app1", "healthy"], ["app2", "degraded"]]);
  });

  it("skips table a2ui when columns and rows are both empty", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_table_data", status: "running",
        args: { columns: [], rows: [] },
      },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(0);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 4. Thinking/Progress ordering (the core ordering fix)
// ═══════════════════════════════════════════════════════════════════════════════

describe("buildMessagesFromEvents – event ordering", () => {
  it("reattaches orphaned thinking events before user to the correct turn", () => {
    // Simulates the race: thinking written to Redis BEFORE user message
    // (old bug). buildMessagesFromEvents buffers them and emits after user.
    const events: SessionUiEvent[] = [
      // Turn 1
      { type: "user", ts: 1, text: "Q1" },
      { type: "complete", ts: 2, text: "A1" },
      // Orphaned: thinking arrived before user in Redis
      { type: "thinking", ts: 3, text: "analyzing..." },
      // Turn 2 user arrives after thinking
      { type: "user", ts: 4, text: "Q2" },
      { type: "complete", ts: 5, text: "A2" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const types = msgTypes(msgs);
    // thinking should appear AFTER Q2 user, not before it
    const userQ2Idx = types.indexOf("user", types.indexOf("assistant") + 1);
    const thinkingIdx = types.indexOf("emit_reasoning");
    expect(thinkingIdx).toBeGreaterThan(userQ2Idx);
  });

  it("reattaches orphaned progress events before user to the correct turn", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "Q1" },
      { type: "complete", ts: 2, text: "A1" },
      { type: "progress", ts: 3, tool: "render_chart", status: "running",
        args: { labels: ["a"], datasets: [{ label: "x", data: [1] }] } },
      { type: "user", ts: 4, text: "Q2 followup" },
      { type: "complete", ts: 5, text: "A2" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const types = msgTypes(msgs);

    const userQ2Idx = msgs.findIndex((m: any) => m.role === "user" && m.content === "Q2 followup");
    const chartChipIdx = msgs.findIndex((m: any) => m.name === "render_chart");
    expect(chartChipIdx).toBeGreaterThan(userQ2Idx);
  });

  it("thinking within a turn appears before complete", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "Q1" },
      { type: "thinking", ts: 2, text: "hmm" },
      { type: "complete", ts: 3, text: "A1" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const types = msgTypes(msgs);
    const thinkIdx = types.indexOf("emit_reasoning");
    const assistIdx = types.indexOf("assistant");
    expect(thinkIdx).toBeLessThan(assistIdx);
  });

  it("progress within a turn appears before complete", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "Q1" },
      { type: "progress", ts: 2, tool: "wcnp_check_app_health", status: "running", args: { app: "x" } },
      { type: "complete", ts: 3, text: "A1" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const chipIdx = msgs.findIndex((m: any) => m.name === "wcnp_check_app_health");
    const assistIdx = msgs.findIndex((m: any) => (m as any).role === "assistant");
    expect(chipIdx).toBeLessThan(assistIdx);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 5. Multi-turn full scenario
// ═══════════════════════════════════════════════════════════════════════════════

describe("buildMessagesFromEvents – multi-turn scenario", () => {
  it("replays the exact user-reported bug scenario", () => {
    // The user's scenario:
    // Turn 1: "Check health of namespace unified-promise-discovery"
    // Turn 2: "trend graph memory p90..."
    // After refresh — turn 2 should appear with chart
    const events: SessionUiEvent[] = [
      // Turn 1
      { type: "user", ts: 1, text: "Check health of namespace unified-promise-discovery" },
      { type: "thinking", ts: 2, text: "I need to check health metrics" },
      {
        type: "progress", ts: 3, tool: "wcnp_check_app_health", status: "running",
        args: { namespace: "unified-promise-discovery", apps: ["unifiedpromise-prod-tg2"] },
      },
      { type: "complete", ts: 4, text: "⚠ App Memory — p90 at 86.4–86.5%..." },

      // Turn 2 (follow-up)
      { type: "user", ts: 5, text: "trend graph p90 at 86.4-86.5% on both clusters" },
      { type: "thinking", ts: 6, text: "Let me render a chart for memory trend" },
      {
        type: "progress", ts: 7, tool: "render_chart", status: "running",
        args: {
          title: "Memory p90 — 19-Day Window",
          chart_type: "line",
          labels: ["Apr 3", "Apr 6", "Apr 9", "Apr 12", "Apr 15", "Apr 18"],
          datasets: [
            { label: "eus2-prod-a54", data: [86.2, 86.3, 86.4, 86.4, 86.4, 86.4] },
            { label: "scus-prod-a78", data: [86.3, 86.4, 86.5, 86.5, 86.5, 86.5] },
          ],
        },
      },
      { type: "complete", ts: 8, text: "Memory Trend Analysis — 19-Day Window\n\nThe chart confirms..." },
    ];

    const msgs = buildMessagesFromEvents(events);

    // Turn 2 user message must exist
    const turn2User = msgs.find((m: any) => m.role === "user" && (m.content as string)?.includes("trend graph"));
    expect(turn2User).toBeDefined();

    // Chart a2ui block must exist
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBeGreaterThanOrEqual(1);
    const chartBlock = (a2ui[0] as any).arguments.a2ui[0];
    expect(chartBlock.component).toBe("Chart");
    expect(chartBlock.series.length).toBe(2);

    // Complete text must exist
    const completeText = msgs.filter((m: any) => m.role === "assistant" && (m.content as string)?.includes("Memory Trend"));
    expect(completeText.length).toBe(1);
  });

  it("handles three turns with charts in each", () => {
    const mkChart = (label: string) => ({
      type: "progress" as const, ts: 0, tool: "render_chart", status: "running" as const,
      args: { title: label, labels: ["a"], datasets: [{ label: "s", data: [1] }] },
    });
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "Q1" },
      mkChart("Chart 1"),
      { type: "complete", ts: 2, text: "A1" },
      { type: "user", ts: 3, text: "Q2" },
      mkChart("Chart 2"),
      { type: "complete", ts: 4, text: "A2" },
      { type: "user", ts: 5, text: "Q3" },
      mkChart("Chart 3"),
      { type: "complete", ts: 6, text: "A3" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2uiBlocks = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2uiBlocks.length).toBe(3);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 6. Done status skipped
// ═══════════════════════════════════════════════════════════════════════════════

describe("buildMessagesFromEvents – progress done status", () => {
  it("skips progress events with status=done", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      { type: "progress", ts: 2, tool: "render_chart", status: "done", args: {} },
      { type: "complete", ts: 3, text: "Done" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const chips = msgs.filter((m: any) => m.name === "render_chart");
    expect(chips.length).toBe(0);
  });

  it("renders running but not done for the same tool", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_chart", status: "running",
        args: { labels: ["a"], datasets: [{ label: "x", data: [1] }] },
      },
      { type: "progress", ts: 3, tool: "render_chart", status: "done", args: {} },
      { type: "complete", ts: 4, text: "Done" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const chips = msgs.filter((m: any) => m.name === "render_chart");
    expect(chips.length).toBe(1);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(1);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 7. Non-render tools are not converted
// ═══════════════════════════════════════════════════════════════════════════════

describe("buildMessagesFromEvents – non-render tools", () => {
  it("does not convert generic tool progress to render_a2ui", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      { type: "progress", ts: 2, tool: "wcnp_check_app_health", status: "running", args: { app: "x" } },
      { type: "complete", ts: 3, text: "Done" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(0);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 8. Edge cases
// ═══════════════════════════════════════════════════════════════════════════════

describe("buildMessagesFromEvents – edge cases", () => {
  it("handles empty events array", () => {
    const msgs = buildMessagesFromEvents([]);
    expect(msgs).toHaveLength(0);
  });

  it("handles render_chart with missing datasets key", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_chart", status: "running",
        args: { labels: ["a"], series: [{ name: "s", data: [1] }] },
      },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(1);
    expect((a2ui[0] as any).arguments.a2ui[0].series[0].label).toBe("s");
  });

  it("handles render_chart with undefined args", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      { type: "progress", ts: 2, tool: "render_chart", status: "running" },
    ];
    const msgs = buildMessagesFromEvents(events);
    // Should not throw, chip emitted, no a2ui (no labels)
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(0);
  });

  it("handles thinking event with empty text", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      { type: "thinking", ts: 2, text: "" },
      { type: "complete", ts: 3, text: "A" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const reasoning = msgs.filter((m: any) => m.name === "emit_reasoning");
    expect(reasoning.length).toBe(0);
  });

  it("handles thinking event with whitespace-only text", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      { type: "thinking", ts: 2, text: "   " },
      { type: "complete", ts: 3, text: "A" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const reasoning = msgs.filter((m: any) => m.name === "emit_reasoning");
    expect(reasoning.length).toBe(0);
  });

  it("handles render_multi_chart with missing charts key", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      { type: "progress", ts: 2, tool: "render_multi_chart", status: "running", args: {} },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(0);
  });

  it("handles render_table_data with only columns (no rows)", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "q" },
      {
        type: "progress", ts: 2, tool: "render_table_data", status: "running",
        args: { columns: ["A", "B"] },
      },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(1);
    expect((a2ui[0] as any).arguments.a2ui[0].component).toBe("Table");
  });

  it("orphaned events at start (before any user) are buffered", () => {
    const events: SessionUiEvent[] = [
      { type: "thinking", ts: 1, text: "orphan thought" },
      { type: "progress", ts: 2, tool: "some_tool", status: "running", args: {} },
      { type: "user", ts: 3, text: "Q1" },
      { type: "complete", ts: 4, text: "A1" },
    ];
    const msgs = buildMessagesFromEvents(events);
    // Orphaned events should appear AFTER user message
    const userIdx = msgs.findIndex((m: any) => m.role === "user");
    const thinkIdx = msgs.findIndex((m: any) => m.name === "emit_reasoning");
    const toolIdx = msgs.findIndex((m: any) => m.name === "some_tool");
    expect(thinkIdx).toBeGreaterThan(userIdx);
    expect(toolIdx).toBeGreaterThan(userIdx);
  });

  it("trailing intermediate events without complete are still emitted", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "Q1" },
      { type: "thinking", ts: 2, text: "analyzing" },
      { type: "progress", ts: 3, tool: "check_health", status: "running", args: {} },
      // No complete event (mid-stream)
    ];
    const msgs = buildMessagesFromEvents(events);
    expect(msgs.length).toBe(3); // user + thinking + progress
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 9. Multi-turn conversation replay scenarios
// ═══════════════════════════════════════════════════════════════════════════════

describe("buildMessagesFromEvents – multi-turn conversations", () => {
  it("five sequential Q&A turns produce correct message count", () => {
    const events: SessionUiEvent[] = [];
    for (let i = 0; i < 5; i++) {
      events.push({ type: "user", ts: i * 3 + 1, text: `Q${i}` });
      events.push({ type: "thinking", ts: i * 3 + 2, text: `thinking ${i}` });
      events.push({ type: "complete", ts: i * 3 + 3, text: `A${i}` });
    }
    const msgs = buildMessagesFromEvents(events);
    const users = msgs.filter((m: any) => m.role === "user");
    const assistants = msgs.filter((m: any) => m.role === "assistant");
    expect(users.length).toBe(5);
    expect(assistants.length).toBe(5);
  });

  it("multi-turn with charts in alternating turns", () => {
    const events: SessionUiEvent[] = [
      // Turn 1: no chart
      { type: "user", ts: 1, text: "check health" },
      { type: "progress", ts: 2, tool: "wcnp_check_app_health", status: "running", args: {} },
      { type: "complete", ts: 3, text: "App is healthy" },
      // Turn 2: with chart
      { type: "user", ts: 4, text: "show trend" },
      {
        type: "progress", ts: 5, tool: "render_chart", status: "running",
        args: { labels: ["a", "b"], datasets: [{ label: "s", data: [1, 2] }] },
      },
      { type: "complete", ts: 6, text: "Chart above" },
      // Turn 3: no chart
      { type: "user", ts: 7, text: "summarize" },
      { type: "complete", ts: 8, text: "Summary done" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(1); // only turn 2 has chart
    const users = msgs.filter((m: any) => m.role === "user");
    expect(users.length).toBe(3);
  });

  it("multi-turn where each turn has a different render tool", () => {
    const events: SessionUiEvent[] = [
      // Turn 1: render_chart
      { type: "user", ts: 1, text: "Q1" },
      {
        type: "progress", ts: 2, tool: "render_chart", status: "running",
        args: { title: "Chart1", labels: ["x"], datasets: [{ label: "s", data: [1] }] },
      },
      { type: "complete", ts: 3, text: "A1" },
      // Turn 2: render_table_data
      { type: "user", ts: 4, text: "Q2" },
      {
        type: "progress", ts: 5, tool: "render_table_data", status: "running",
        args: { columns: ["Name"], rows: [["app1"]] },
      },
      { type: "complete", ts: 6, text: "A2" },
      // Turn 3: render_multi_chart
      { type: "user", ts: 7, text: "Q3" },
      {
        type: "progress", ts: 8, tool: "render_multi_chart", status: "running",
        args: {
          charts: [
            { title: "C1", labels: ["a"], datasets: [{ label: "s", data: [1] }] },
            { title: "C2", labels: ["b"], datasets: [{ label: "s", data: [2] }] },
          ],
        },
      },
      { type: "complete", ts: 9, text: "A3" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(3); // chart, table, multi_chart
    // Verify types
    expect((a2ui[0] as any).arguments.a2ui[0].component).toBe("Chart");
    expect((a2ui[1] as any).arguments.a2ui[0].component).toBe("Table");
    expect((a2ui[2] as any).arguments.a2ui.length).toBe(2); // two charts
  });

  it("turn with tool call + chart + table all in sequence", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "full report" },
      { type: "thinking", ts: 2, text: "gathering data" },
      { type: "progress", ts: 3, tool: "wcnp_check_app_health", status: "running", args: {} },
      {
        type: "progress", ts: 4, tool: "render_chart", status: "running",
        args: { title: "Memory", labels: ["a"], datasets: [{ label: "s", data: [1] }] },
      },
      {
        type: "progress", ts: 5, tool: "render_table_data", status: "running",
        args: { columns: ["App", "Status"], rows: [["myapp", "ok"]] },
      },
      { type: "complete", ts: 6, text: "Report complete" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(2); // chart + table (health check is not a render tool)
    const chips = msgs.filter((m: any) => m.name && m.name !== "render_a2ui" && m.name !== "emit_reasoning");
    expect(chips.length).toBe(3); // all 3 tools get chips
  });

  it("thinking events across turns are isolated to their turn", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "Q1" },
      { type: "thinking", ts: 2, text: "thought for Q1" },
      { type: "complete", ts: 3, text: "A1" },
      { type: "user", ts: 4, text: "Q2" },
      { type: "thinking", ts: 5, text: "thought for Q2" },
      { type: "complete", ts: 6, text: "A2" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const reasoning = msgs.filter((m: any) => m.name === "emit_reasoning");
    expect(reasoning.length).toBe(2);
    // First reasoning appears before first assistant, second before second
    const firstReasonIdx = msgs.indexOf(reasoning[0]);
    const firstAssistIdx = msgs.findIndex((m: any) => m.role === "assistant");
    const secondReasonIdx = msgs.indexOf(reasoning[1]);
    const secondAssistIdx = msgs.findIndex((m: any, i: number) => m.role === "assistant" && i > firstAssistIdx);
    expect(firstReasonIdx).toBeLessThan(firstAssistIdx);
    expect(secondReasonIdx).toBeLessThan(secondAssistIdx);
    expect(secondReasonIdx).toBeGreaterThan(firstAssistIdx);
  });

  it("four turns: only turn 2 and 4 have thinking, all have complete", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "Q1" },
      { type: "complete", ts: 2, text: "A1" },
      { type: "user", ts: 3, text: "Q2" },
      { type: "thinking", ts: 4, text: "hmm Q2" },
      { type: "complete", ts: 5, text: "A2" },
      { type: "user", ts: 6, text: "Q3" },
      { type: "complete", ts: 7, text: "A3" },
      { type: "user", ts: 8, text: "Q4" },
      { type: "thinking", ts: 9, text: "hmm Q4" },
      { type: "complete", ts: 10, text: "A4" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const users = msgs.filter((m: any) => m.role === "user");
    const assistants = msgs.filter((m: any) => m.role === "assistant");
    const reasoning = msgs.filter((m: any) => m.name === "emit_reasoning");
    expect(users.length).toBe(4);
    expect(assistants.length).toBe(4);
    expect(reasoning.length).toBe(2);
  });

  it("multi-turn with mixed render_chart running + done pairs", () => {
    const events: SessionUiEvent[] = [
      // Turn 1
      { type: "user", ts: 1, text: "Q1" },
      {
        type: "progress", ts: 2, tool: "render_chart", status: "running",
        args: { title: "C1", labels: ["a"], datasets: [{ label: "s", data: [1] }] },
      },
      { type: "progress", ts: 3, tool: "render_chart", status: "done", args: {} },
      { type: "complete", ts: 4, text: "A1" },
      // Turn 2
      { type: "user", ts: 5, text: "Q2" },
      {
        type: "progress", ts: 6, tool: "render_chart", status: "running",
        args: { title: "C2", labels: ["b"], datasets: [{ label: "s2", data: [2] }] },
      },
      { type: "progress", ts: 7, tool: "render_chart", status: "done", args: {} },
      { type: "complete", ts: 8, text: "A2" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const a2ui = msgs.filter((m: any) => m.name === "render_a2ui");
    expect(a2ui.length).toBe(2); // one per turn, done events skipped
    expect((a2ui[0] as any).arguments.a2ui[0].title).toBe("C1");
    expect((a2ui[1] as any).arguments.a2ui[0].title).toBe("C2");
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 9. Mid-processing refresh (incomplete turn handling)
// ═══════════════════════════════════════════════════════════════════════════════

describe("buildMessagesFromEvents – mid-processing refresh", () => {
  it("emits follow-up turn intermediate events after last complete (no USER2 yet)", () => {
    // Scenario: refresh while follow-up is processing — USER2 not yet written
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "check health" },
      { type: "thinking", ts: 2, text: "analyzing..." },
      { type: "progress", ts: 3, tool: "wcnp_check_app_health", status: "running", args: { app: "foo" } },
      { type: "complete", ts: 4, text: "Health report: all good" },
      // Follow-up turn in progress — no USER event written yet
      { type: "thinking", ts: 5, text: "next analysis..." },
      { type: "progress", ts: 6, tool: "wcnp_query_prometheus", status: "running", args: { query: "up" } },
    ];
    const msgs = buildMessagesFromEvents(events);
    const types = msgTypes(msgs);
    // Turn 1 is complete. Follow-up turn's intermediate events are flushed
    // so the user sees progress chips while polling waits for completion.
    expect(types).toEqual([
      "user",
      "emit_reasoning",
      "tool:wcnp_check_app_health",
      "assistant",
      "emit_reasoning",
      "tool:wcnp_query_prometheus",
    ]);
  });

  it("keeps in-progress turn events when USER exists but no COMPLETE", () => {
    // Scenario: refresh mid-processing but USER2 WAS written (eager write worked)
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "check health" },
      { type: "complete", ts: 2, text: "Health report" },
      { type: "user", ts: 3, text: "show trends" },
      { type: "thinking", ts: 4, text: "fetching data..." },
      { type: "progress", ts: 5, tool: "wcnp_query_prometheus", status: "running", args: {} },
    ];
    const msgs = buildMessagesFromEvents(events);
    const types = msgTypes(msgs);
    // Both turns should appear — turn 2 has user + in-progress events
    expect(types).toEqual([
      "user",
      "assistant",
      "user",
      "emit_reasoning",
      "tool:wcnp_query_prometheus",
    ]);
  });

  it("drops orphaned status-update text after last complete", () => {
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "Q1" },
      { type: "complete", ts: 2, text: "A1" },
      // Orphaned status-update from an incomplete next turn
      { type: "status-update", ts: 3, text: "partial response from turn 2" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const types = msgTypes(msgs);
    expect(types).toEqual(["user", "assistant"]);
  });

  it("still flushes status-update for legacy sessions (no complete events)", () => {
    // Legacy session: only status-update, no complete events
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "old question" },
      { type: "status-update", ts: 2, text: "old answer" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const types = msgTypes(msgs);
    expect(types).toEqual(["user", "assistant"]);
    expect((msgs[1] as any).content).toBe("old answer");
  });

  it("handles carry-over correctly when thinking arrives before USER2", () => {
    // Race: thinking for turn 2 arrives before its USER event
    const events: SessionUiEvent[] = [
      { type: "user", ts: 1, text: "Q1" },
      { type: "complete", ts: 2, text: "A1" },
      { type: "thinking", ts: 3, text: "early thinking for turn 2" },
      { type: "user", ts: 4, text: "Q2" },
      { type: "complete", ts: 5, text: "A2" },
    ];
    const msgs = buildMessagesFromEvents(events);
    const types = msgTypes(msgs);
    // Thinking should carry over to turn 2 (after USER Q2), not merge with turn 1
    expect(types).toEqual([
      "user",             // Q1
      "assistant",        // A1
      "user",             // Q2
      "emit_reasoning",   // carried-over thinking
      "assistant",        // A2
    ]);
  });

  it("emits orphaned intermediate events when no user and no complete exist", () => {
    // Mid-processing refresh: backend has thinking + progress but the user
    // event hasn't been written yet. These should be visible so the UI can
    // show progress chips while polling.
    const events: SessionUiEvent[] = [
      { type: "thinking", ts: 1, text: "orphan" },
      { type: "progress", ts: 2, tool: "some_tool", status: "running", args: {} },
    ];
    const msgs = buildMessagesFromEvents(events);
    const types = msgTypes(msgs);
    expect(types).toEqual(["emit_reasoning", "tool:some_tool"]);
  });
});

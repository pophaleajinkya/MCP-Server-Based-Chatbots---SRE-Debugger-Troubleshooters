/**
 * Pure helper functions extracted from ChatInterface.tsx so they can be
 * independently unit-tested with full branch coverage.
 */

import { TextMessage, ActionExecutionMessage, MessageRole } from "@copilotkit/runtime-client-gql";
import type { SessionUiEvent } from "@/types";

// ─── Types ────────────────────────────────────────────────────────────────────

// Human-readable labels for known MCP tool names
const TOOL_LABELS: Record<string, string> = {
  wcnp_check_app_health:       "Check App Health",
  wcnp_check_namespace_health: "Check Namespace Health",
  wcnp_analyze:                "Analyze Health",
  wcnp_get_app_clusters:       "Get App Clusters",
  wcnp_list_deployments:       "List Deployments",
  wcnp_query_prometheus:       "Query Prometheus",
  wcnp_check_url_health:       "Check URL Health",
  wcnp_check_grafana_url_health: "Check Grafana URL",
  wcnp_chart:                  "Render Chart",
  wcnp_episode_chart:          "Render Episode Chart",
  render_chart:                "Render Chart",
  render_multi_chart:          "Render Multi-Chart",
  get_mcp_prompt:              "Load Workflow Guide",
};

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Key args to show in the tool chip (at most 3) */
export function toolArgPreview(args: Record<string, unknown>): string {
  const skip = new Set(["format", "output_format", "include_details", "clusters"]);
  const entries = Object.entries(args)
    .filter(([k, v]) => !skip.has(k) && v !== undefined && v !== "" && v !== null)
    .slice(0, 3);
  return entries.map(([k, v]) => {
    // Serialize nested objects/arrays to JSON instead of showing "[object Object]"
    const str = typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
    return `${k}=${str.slice(0, 40)}`;
  }).join("  ");
}

// Re-export ReasoningEntry from the canonical source for backward compat
/** A single reasoning/thinking entry */
export interface ReasoningEntry {
  type: "thinking" | "reasoning";
  text: string;
  ts: number;
}

/** A normalised segment inside an assistant turn */
export type AssistantSegment =
  | { kind: "text"; id: string; content: string }
  | { kind: "a2ui"; id: string; data: unknown }
  | { kind: "tool"; id: string; name: string; args: Record<string, unknown> }
  /** Python code execution block — code written by LLM + stdout output */
  | { kind: "code"; id: string; code: string; output: string }
  /** Reasoning/thinking stream — kept for type compatibility but no longer populated */
  | { kind: "reasoning"; id: string; entries: ReasoningEntry[] };

/** A single conversation turn (user or grouped assistant) */
export type Turn =
  | { type: "user"; id: string; content: string; timestamp?: Date; userId?: string; userName?: string }
  | { type: "assistant"; id: string; segments: AssistantSegment[]; isStreaming: boolean };

// ─── groupIntoTurns ───────────────────────────────────────────────────────────

/**
 * Groups AG-UI messages (from useCopilotChatInternal) into clean user/assistant turns.
 *
 * AG-UI message shapes:
 *   UserMessage:      { role: "user",      content: string }
 *   AssistantMessage: { role: "assistant",  content?: string, toolCalls?: ToolCall[] }
 *   ToolMessage:      { role: "tool",       toolCallId, content }  ← skipped (result ack)
 */
export function groupIntoTurns(messages: unknown[] | undefined | null): Turn[] {
  if (!Array.isArray(messages) || messages.length === 0) return [];
  const turns: Turn[] = [];
  let currentAsst: (Turn & { type: "assistant" }) | null = null;

  function flush() {
    if (currentAsst) {
      turns.push(currentAsst);
      currentAsst = null;
    }
  }

  for (const raw of messages) {
    const msg = raw as Record<string, unknown>;
    const role = msg["role"] as string | undefined;
    const msgType = msg["type"] as string | undefined;

    // Handle ActionExecutionMessage (from setMessages replay path AND live CopilotKit messages).
    // These have type="ActionExecutionMessage", name, arguments — no role/toolCalls.
    if (msgType === "ActionExecutionMessage") {
      const name = msg["name"] as string | undefined;
      const args = msg["arguments"] as Record<string, unknown> | undefined;
      if (!currentAsst) {
        currentAsst = { type: "assistant", id: String(msg["id"] ?? crypto.randomUUID()), segments: [], isStreaming: false };
      }
      if (name === "render_a2ui" && args?.a2ui) {
        currentAsst.segments.push({ kind: "a2ui", id: String(msg["id"] ?? crypto.randomUUID()), data: args.a2ui });
      } else if (name === "emit_reasoning" && args) {
        // Consolidate consecutive thinking entries into a SINGLE reasoning
        // segment (ChatGPT-style: one collapsible "Thought for Xs" block).
        const rType = (args.type as string) ?? "thinking";
        const rText = (args.text as string) ?? "";
        const rTs = typeof args.ts === "number" ? args.ts : Date.now();
        if (rText.trim()) {
          const lastSeg = currentAsst.segments[currentAsst.segments.length - 1];
          if (lastSeg && lastSeg.kind === "reasoning") {
            // Append to existing reasoning block
            lastSeg.entries.push({ type: rType as "thinking" | "reasoning", text: rText.trim(), ts: rTs });
          } else {
            // First reasoning entry — create new block
            currentAsst.segments.push({
              kind: "reasoning",
              id: String(msg["id"] ?? crypto.randomUUID()),
              entries: [{ type: rType as "thinking" | "reasoning", text: rText.trim(), ts: rTs }],
            });
          }
        }
      } else if (name === "run_python_script") {
        // Python code execution — render as dedicated CodeExecutionBlock
        currentAsst.segments.push({
          kind:   "code",
          id:     String(msg["id"] ?? crypto.randomUUID()),
          code:   String(args?.code   ?? ""),
          output: String(args?.output ?? ""),
        });
      } else if (name && name !== "render_a2ui") {
        // MCP tool call — show as progress chip (spinner during stream, checkmark when done)
        currentAsst.segments.push({
          kind: "tool",
          id:   String(msg["id"] ?? crypto.randomUUID()),
          name,
          args: (args ?? {}) as Record<string, unknown>,
        });
      }
      continue;
    }

    // Skip tool result messages (they're internal acks for TOOL_CALL_RESULT events)
    if (role === "tool" || role === "system" || role === "activity") continue;

    if (role === "user") {
      flush();
      const content = msg["content"];
      const text =
        typeof content === "string"
          ? content
          : Array.isArray(content)
          ? (content as Array<{ type?: string; text?: string }>)
              .filter((p) => p.type === "text")
              .map((p) => p.text ?? "")
              .join(" ")
          : String(content ?? "");
      // Build timestamp: prefer event_ts (stored Unix seconds) then createdAt
      const eventTs  = msg["event_ts"] as number | undefined;
      const createdAt = msg["createdAt"] as Date | string | undefined;
      const timestamp = eventTs
        ? new Date(eventTs * 1000)
        : createdAt ? new Date(createdAt) : undefined;

      // Strip context blocks injected by ViewContext so they don't appear
      // in the user's chat bubble (context is for the LLM only).
      // Uses unique markers (__SRE_VIEW_CTX__) to avoid stripping user-typed text.
      const displayText = text
        .replace(/__SRE_VIEW_CTX_START__[\s\S]*?__SRE_VIEW_CTX_END__\s*/g, "")
        .trim();

      turns.push({
        type: "user",
        id: String(msg["id"] ?? crypto.randomUUID()),
        content: displayText,
        timestamp,
        userId:   (msg as any)["user_id"] as string | undefined,
        userName: ((msg as any)["user_name"] || (msg as any)["userName"]) as string | undefined,
      });
      continue;
    }

    if (role === "assistant") {
      if (!currentAsst) {
        currentAsst = {
          type: "assistant",
          id: String(msg["id"] ?? crypto.randomUUID()),
          segments: [],
          isStreaming: false,
        };
      }

      // Text content
      const content = String(msg["content"] ?? "").trim();
      if (content) {
        currentAsst.segments.push({ kind: "text", id: String(msg["id"]), content });
      }

      // Tool calls: only render_a2ui is handled — all other tool calls are native AG-UI events
      const toolCalls = msg["toolCalls"] as Array<{
        id: string;
        function: { name: string; arguments: string };
      }> | undefined;

      if (Array.isArray(toolCalls)) {
        for (const tc of toolCalls) {
          const toolName = tc?.function?.name;
          try {
            const args = JSON.parse(tc.function.arguments || "{}");
            if (toolName === "render_a2ui") {
              if (args.a2ui) {
                currentAsst.segments.push({ kind: "a2ui", id: tc.id, data: args.a2ui });
              }
            } else if (toolName === "emit_reasoning") {
              // Consolidate into single reasoning block per turn
              const rType = (args.type as string) ?? "thinking";
              const rText = (args.text as string) ?? "";
              const rTs = typeof args.ts === "number" ? args.ts : Date.now();
              if (rText.trim()) {
                const lastSeg = currentAsst.segments[currentAsst.segments.length - 1];
                if (lastSeg && lastSeg.kind === "reasoning") {
                  lastSeg.entries.push({ type: rType as "thinking" | "reasoning", text: rText.trim(), ts: rTs });
                } else {
                  currentAsst.segments.push({
                    kind: "reasoning",
                    id: tc.id,
                    entries: [{ type: rType as "thinking" | "reasoning", text: rText.trim(), ts: rTs }],
                  });
                }
              }
            } else if (toolName === "run_python_script") {
              currentAsst.segments.push({
                kind:   "code",
                id:     tc.id,
                code:   String(args.code   ?? ""),
                output: String(args.output ?? ""),
              });
            } else if (toolName) {
              // MCP tool call — show progress chip
              currentAsst.segments.push({ kind: "tool", id: tc.id, name: toolName, args });
            }
          } catch {
            // malformed args — skip
          }
        }
      }
    }
  }

  flush();
  return turns;
}

// ─── buildMessagesFromEvents ──────────────────────────────────────────────────

// ─── A2UI tag extractor (for replay) ─────────────────────────────────────────

function _extractA2UIForReplay(text: string): { cleanText: string; a2uiBlocks: unknown[] } {
  const blocks: unknown[] = [];
  let cleanText = text;
  try {
    const regex = /<a2ui>([\s\S]*?)<\/a2ui>/g;
    let match;
    while ((match = regex.exec(text)) !== null) {
      try { blocks.push(JSON.parse(match[1].trim())); } catch { /* skip malformed */ }
    }
    if (blocks.length > 0) cleanText = text.replace(regex, "").trim();
  } catch { /* return original on any error */ }
  return { cleanText, a2uiBlocks: blocks };
}

/**
 * Rebuilds CopilotKit messages from the stored UI event log for session replay.
 *
 * Handles:
 *  - user TextMessages
 *  - artifact-update / complete → extracts <a2ui> blocks as ActionExecutionMessage(render_a2ui)
 *    then emits remaining markdown text as TextMessage
 */
export function buildMessagesFromEvents(events: SessionUiEvent[]): (TextMessage | ActionExecutionMessage)[] {
  const msgs: (TextMessage | ActionExecutionMessage)[] = [];

  // Deterministic ID generator: same events → same IDs → React skips re-mount.
  // This prevents visual flicker when the poll rebuilds messages from the same
  // (or appended) event list.  IDs are unique within one call because the
  // counter is monotonically increasing.
  let _idSeq = 0;
  const stableId = () => `evt-${_idSeq++}`;

  const flushAssistant = (text: string) => {
    if (!text.trim()) return;
    // Extract A2UI blocks — stored raw in artifact-update text — and replay them
    // as ActionExecutionMessages so A2UIRenderer re-renders them on page refresh.
    const { cleanText, a2uiBlocks } = _extractA2UIForReplay(text);
    for (const block of a2uiBlocks) {
      msgs.push(new ActionExecutionMessage({
        id: stableId(),
        name: "render_a2ui",
        arguments: { a2ui: block },
      }));
    }
    if (cleanText.trim()) {
      msgs.push(new TextMessage({ id: stableId(), role: MessageRole.Assistant, content: cleanText }));
    }
  };

  // Accumulate status-update chunks between user messages.
  // New sessions write a single "complete" event via the after_agent hook.
  // Older sessions (pre-fix) only have "status-update" events; we collect them
  // and emit the last non-empty one as the assistant response.
  let statusTextBuf = "";

  const flushStatusBuf = () => {
    if (statusTextBuf.trim()) {
      flushAssistant(statusTextBuf);
      statusTextBuf = "";
    }
  };

  // Buffer intermediate events (reasoning, progress) and emit them only when
  // we know they belong to the CURRENT turn. Without buffering, events that
  // arrive after a "complete" but before the next "user" get attached to the
  // previous assistant turn during groupIntoTurns().
  let pendingIntermediate: (TextMessage | ActionExecutionMessage)[] = [];
  // Track whether we've seen a "complete" since the last "user" — once set,
  // subsequent intermediate events belong to the NEXT turn.
  // Starts TRUE so orphaned thinking/progress events at the TOP of the list
  // (before the first "user") are buffered and emitted after the user message.
  // This handles the backend race where thinking/progress are rpush'd before
  // the user event (user text extracted late in _after_agent).
  let turnComplete = true;

  const flushPending = () => {
    for (const m of pendingIntermediate) msgs.push(m);
    pendingIntermediate = [];
  };

  for (const ev of events) {
    if (ev.type === "user") {
      // Flush any buffered status-update text before starting a new user turn
      flushStatusBuf();
      // Any pending intermediate events after the previous "complete" belong
      // to THIS turn — emit them AFTER the user message so groupIntoTurns()
      // places them in the new assistant turn.
      const carryOver = pendingIntermediate;
      pendingIntermediate = [];
      turnComplete = false;

      const msg = new TextMessage({ id: stableId(), role: MessageRole.User, content: ev.text ?? "" });
      const meta = msg as unknown as Record<string, unknown>;
      // Attach user identity + timestamp for display in shared/multi-user sessions
      if (ev.user_id)   meta["user_id"]   = ev.user_id;
      if (ev.user_name) meta["user_name"] = ev.user_name;
      if (ev.ts)        meta["event_ts"]  = ev.ts;   // Unix seconds from Redis
      msgs.push(msg);

      // Now emit carried-over intermediate events (they belong to this new turn)
      for (const m of carryOver) msgs.push(m);
    } else if (ev.type === "complete") {
      flushStatusBuf(); // discard any status-update buf — complete is authoritative
      // Emit any pending intermediate events BEFORE the complete text —
      // they are part of THIS turn (reasoning → tool calls → final answer).
      flushPending();
      flushAssistant(ev.text ?? "");
      turnComplete = true;
    } else if (ev.type === "artifact-update" && ev.text) {
      flushStatusBuf();
      flushPending();
      flushAssistant(ev.text);
      turnComplete = true;
    } else if (ev.type === "error") {
      // Agent/LLM error — render as an assistant message so the user sees it.
      // Counts as turn completion (same as "complete").
      flushStatusBuf();
      flushPending();
      const errorText = ev.text || ev.message || "An error occurred while processing your request.";
      flushAssistant(`⚠️ ${errorText}`);
      turnComplete = true;
    } else if (ev.type === "status-update" && ev.text) {
      // Buffer the latest non-empty status-update text — used only when no
      // "complete" or "artifact-update" event exists (pre-fix sessions).
      statusTextBuf = ev.text;
    } else if (ev.type === "thinking") {
      // Replay genuine thinking events only — "reasoning" type was deprecated
      // (it contained non-thought LLM text that shouldn't appear in the panel).
      const rText = (ev.text ?? "").trim();
      if (rText) {
        const m = new ActionExecutionMessage({
          id: stableId(),
          name: "emit_reasoning",
          arguments: { type: "thinking", text: rText, ts: ev.ts ?? Date.now() },
        });
        if (turnComplete) {
          // After "complete" — these belong to the NEXT turn; buffer them.
          pendingIntermediate.push(m);
        } else {
          msgs.push(m);
        }
      }
    } else if (ev.type === "progress" && ev.tool) {
      // Replay MCP tool-call progress chips (both A2A and legacy runner paths).
      // Only "running" events create a chip — "done" events are implicit (no spinner).
      if (ev.status === "done") continue;
      const toolName = String(ev.tool);
      const toolArgs = (ev.args ?? {}) as Record<string, unknown>;

      // ── Convert render_* tool calls to A2UI blocks for visual replay ──
      // During live streaming, the adapter intercepts these and emits A2UI.
      // On replay, we must do the same conversion so charts/tables render.
      const renderMsgs: ActionExecutionMessage[] = [];

      if (toolName === "render_chart" || toolName === "render_multi_chart") {
        const rawCharts: Record<string, unknown>[] =
          toolName === "render_multi_chart"
            ? ((toolArgs.charts ?? []) as Record<string, unknown>[])
            : [toolArgs];
        const a2uiBlocks = rawCharts
          .filter((c) => c && ((c.labels as unknown[]) ?? (c.xAxis as Record<string, unknown>)?.labels ?? []).length > 0)
          .map((c, i) => ({
            id: `chart-replay-${stableId()}-${i}`,
            component: "Chart",
            chartType: c.chart_type ?? c.chartType ?? "line",
            title: c.title ?? c.metric ?? toolArgs.title ?? "",
            xAxis: { labels: c.labels ?? (c.xAxis as Record<string, unknown>)?.labels ?? [] },
            series: ((c.datasets ?? c.series ?? []) as Record<string, unknown>[]).map((d) => ({
              label: d.label ?? d.name ?? "",
              data: d.data ?? [],
            })),
          }));
        if (a2uiBlocks.length > 0) {
          renderMsgs.push(new ActionExecutionMessage({
            id: stableId(),
            name: "render_a2ui",
            arguments: { a2ui: a2uiBlocks },
          }));
        }
      } else if (toolName === "render_table_data") {
        const columns = (toolArgs.columns ?? []) as string[];
        const rows = (toolArgs.rows ?? []) as unknown[][];
        if (columns.length > 0 || rows.length > 0) {
          renderMsgs.push(new ActionExecutionMessage({
            id: stableId(),
            name: "render_a2ui",
            arguments: { a2ui: [{ id: `table-replay-${stableId()}`, component: "Table", columns, rows }] },
          }));
        }
      }

      // Always emit the chip (collapsed tool-call indicator)
      const m = new ActionExecutionMessage({
        id:        stableId(),
        name:      toolName,
        arguments: toolArgs,
      });
      if (turnComplete) {
        pendingIntermediate.push(m, ...renderMsgs);
      } else {
        msgs.push(m, ...renderMsgs);
      }
    }
    // graph (legacy chart) events are not needed for visual replay
  }
  // Flush remaining buffers when appropriate:
  // 1. Turn is open (user exists but no complete yet) → flush everything
  // 2. No user AND no complete events at all — only intermediate events exist
  //    (mid-processing refresh where the backend hasn't written the user event yet).
  //    Flush so progress chips / thinking are visible while polling.
  // 3. turnComplete is true but pendingIntermediate is non-empty — a follow-up
  //    turn has started (thinking/progress after the last complete) but its
  //    user+complete haven't been written yet. Flush so the progress chips
  //    are visible while the poll waits for the turn to finish.
  //
  // Do NOT flush when turnComplete is true AND pending is empty AND we've seen
  // at least one complete (nothing meaningful to flush).
  const hasAnyUser = events.some(e => e.type === "user");
  const hasAnyComplete = events.some(e => e.type === "complete" || e.type === "artifact-update" || e.type === "error");
  if (!turnComplete || (!hasAnyUser && !hasAnyComplete) || pendingIntermediate.length > 0) {
    flushStatusBuf();
    flushPending();
  }

  return msgs;
}

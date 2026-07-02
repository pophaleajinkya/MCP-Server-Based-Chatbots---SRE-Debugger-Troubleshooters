import { AbstractAgent } from "@ag-ui/client";
import { EventType, type RunAgentInput, type BaseEvent } from "@ag-ui/core";
import { Observable } from "rxjs";
import { streamA2AQuery, type UserContext, type A2AStreamEvent } from "./a2a-client";
import { loadAgents } from "./agents";
import { createLogger } from "./logger";
import { pushReasoning, setReasoningActive } from "./reasoning-store";
const log = createLogger('a2a-copilotkit-adapter.ts');


interface A2AAgentConfig {
  agentId?: string;
  sessionId?: string;
  userCtx?: UserContext;
}

// ─── Run registry ─────────────────────────────────────────────────────────────
const runRegistry = new Map<string, AbortController>();

/** Called by the copilotkit route when an agent/stop request arrives. */
export function abortRun(threadId: string): boolean {
  const ctrl = runRegistry.get(threadId);
  if (!ctrl) return false;
  ctrl.abort();
  runRegistry.delete(threadId);
  return true;
}

// ─── A2UI tag detection ───────────────────────────────────────────────────────

const A2UI_OPEN = "<a2ui>";
const A2UI_CLOSE = "</a2ui>";

function extractA2UIBlocks(text: string): { cleanText: string; a2uiBlocks: unknown[] } {
  const blocks: unknown[] = [];
  let cleanText = text;
  try {
    const regex = new RegExp(`${escapeRegex(A2UI_OPEN)}(.*?)${escapeRegex(A2UI_CLOSE)}`, "gs");
    let match;
    while ((match = regex.exec(text)) !== null) {
      try {
        const parsed = JSON.parse(match[1].trim());
        blocks.push(parsed);
      } catch { /* malformed A2UI JSON — skip this block */ }
    }
    if (blocks.length > 0) {
      cleanText = text.replace(regex, "").trim();
    }
  } catch (err) {
    // Regex or replace failure — return original text unmodified
    log.warn("[extractA2UIBlocks] Unexpected error:", err);
    return { cleanText: text, a2uiBlocks: [] };
  }
  return { cleanText, a2uiBlocks: blocks };
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Legacy graph extraction removed — A2UI v0.9 handles all chart/table/grafana rendering

/**
 * AG-UI AbstractAgent that bridges the standard A2A protocol to AG-UI events.
 *
 * Handles:
 * - Incremental text streaming from artifact-update events
 * - Native TOOL_CALL events from MCP function_call/function_response DataParts
 * - A2UI v0.9 block detection and rendering (extracted from tool responses and final text)
 * - Error handling and abort/stop support
 */
export class A2AAgent extends AbstractAgent {
  constructor(private cfg: A2AAgentConfig = {}) {
    super({ description: "A2A ADK agent bridge" });
  }

  run(input: RunAgentInput): Observable<BaseEvent> {
    return new Observable<BaseEvent>((subscriber) => {
      const { threadId, runId } = input;

      const controller = new AbortController();
      runRegistry.set(threadId, controller);

      const lastUserMsg = [...input.messages]
        .reverse()
        .find((m) => m.role === "user");

      const query = extractTextContent(lastUserMsg);

      subscriber.next({ type: EventType.RUN_STARTED, threadId, runId });

      if (!query.trim()) {
        subscriber.next({ type: EventType.RUN_FINISHED, threadId, runId });
        subscriber.complete();
        return;
      }

      const agents = loadAgents();
      const agent = this.cfg.agentId
        ? (agents.find((a) => a.id === this.cfg.agentId) ?? agents[0])
        : agents[0];

      if (!agent) {
        emitTextEvents(subscriber, "⚠️ No agents configured. Set ADK_AGENTS in .env.local.");
        subscriber.next({ type: EventType.RUN_FINISHED, threadId, runId });
        subscriber.complete();
        return;
      }

      const sessionId = this.cfg.sessionId ?? threadId;

      // NOTE: Do NOT reset reasoning here — handleSend() already calls
      // clearReasoning() + setReasoningActive(true).  Resetting here creates
      // a race: reasoning goes inactive before the first event arrives.

      (async () => {
        let statusText  = "";   // accumulated from status-update text parts (streaming)
        let artifactText = "";  // from artifact-update (authoritative final response)
        const emittedReasoningKeys = new Set<string>();
        // Deduplicate A2UI blocks: the same block can appear in both function_response
        // text and the accumulated finalText — emit each unique block only once.
        const emittedA2UIKeys = new Set<string>();

        try {
          let eventCount = 0;

          for await (const event of streamA2AQuery(
            agent.url,
            query.trim(),
            sessionId,
            this.cfg.userCtx,
            controller.signal
          )) {
            eventCount++;

            if ("kind" in event && event.kind === "status-update") {
              const state = event.status.state;
              const message = event.status.message;

              if (state === "working" && message?.parts) {
                for (const part of message.parts) {
                  const root = (part as any).root ?? part;

                  // Accumulate status-update text as a fallback — used only when
                  // no artifact-update arrives (artifact-update takes priority).
                  if (root.kind === "text" && root.text) {
                    const partMeta = root.metadata ?? {};
                    const isThought = partMeta["adk_thought"] === true;

                    // Only genuine thinking blocks (adk_thought=true) go into the
                    // reasoning panel.  Non-thought text is the LLM's response
                    // content (markdown, <a2ui> blocks, etc.) — NOT reasoning.
                    if (isThought) {
                      const textTrimmed = root.text.trim();
                      if (textTrimmed) {
                        const reasoningKey = `thinking:${textTrimmed}`;
                        if (!emittedReasoningKeys.has(reasoningKey)) {
                          emittedReasoningKeys.add(reasoningKey);
                          setReasoningActive(true);
                          pushReasoning({ type: "thinking", text: textTrimmed, ts: Date.now() });
                          emitRenderToolCall(subscriber, "emit_reasoning", {
                            type: "thinking",
                            text: textTrimmed,
                          });
                        }
                      }
                    } else {
                      // Accumulate non-thought text for fallback final response
                      statusText += root.text;
                    }
                  }

                  // DataPart with function_call — emit native TOOL_CALL_START/ARGS/END
                  if (root.kind === "data" && root.data?.name && root.data?.args !== undefined) {
                    const meta = root.metadata ?? {};
                    const metaType = meta["adk_type"] ?? "";
                    if (metaType === "function_call" || (!metaType && root.data.name && root.data.args !== undefined)) {
                      const name = root.data.name as string;
                      // Prefer the ADK-assigned id; fall back to a UUID so parallel
                      // calls to the same tool get distinct toolCallId values.
                      const callId = root.data.id || `${name}-${crypto.randomUUID()}`;
                      subscriber.next({ type: EventType.TOOL_CALL_START, toolCallId: callId, toolCallName: name });
                      subscriber.next({ type: EventType.TOOL_CALL_ARGS, toolCallId: callId, delta: JSON.stringify(root.data.args ?? {}) });
                      subscriber.next({ type: EventType.TOOL_CALL_END, toolCallId: callId });

                      // ── Render tool interception ──────────────────────────────────────
                      // The A2A path goes through ADK's native server (not run_agent_with_events),
                      // so runner.py's type:"graph" events are never emitted in production.
                      // We intercept render_* function_call args HERE and convert to A2UI blocks.

                      const args = root.data.args as Record<string, any>;

                      // render_chart / render_multi_chart → A2UI Chart blocks
                      if (name === "render_chart" || name === "render_multi_chart") {
                        const rawCharts: any[] =
                          name === "render_multi_chart"
                            ? (args.charts ?? [])
                            : [args];

                        const a2uiBlocks: unknown[] = rawCharts
                          .filter((c: any) => c && (c.labels ?? c.xAxis?.labels ?? []).length > 0)
                          .map((c: any, i: number) => ({
                            id: `chart-fcall-${callId}-${i}`,
                            component: "Chart",
                            chartType: c.chart_type ?? c.chartType ?? "line",
                            title: c.title ?? c.metric ?? args.title ?? "",
                            xAxis: { labels: c.labels ?? c.xAxis?.labels ?? [] },
                            series: (c.datasets ?? c.series ?? []).map((d: any) => ({
                              label: d.label ?? d.name ?? "",
                              data: d.data ?? [],
                            })),
                          }));

                        if (a2uiBlocks.length > 0) {
                          const key = JSON.stringify(a2uiBlocks);
                          if (!emittedA2UIKeys.has(key)) {
                            emittedA2UIKeys.add(key);
                            emitRenderToolCall(subscriber, "render_a2ui", { a2ui: a2uiBlocks });
                          }
                        }
                      }

                      // render_table_data → A2UI Table block
                      if (name === "render_table_data") {
                        const columns: string[] = args.columns ?? [];
                        const rows: unknown[][] = args.rows ?? [];
                        if (columns.length > 0 || rows.length > 0) {
                          const block = {
                            id: `table-fcall-${callId}`,
                            component: "Table",
                            columns,
                            rows,
                          };
                          const key = JSON.stringify(block);
                          if (!emittedA2UIKeys.has(key)) {
                            emittedA2UIKeys.add(key);
                            emitRenderToolCall(subscriber, "render_a2ui", { a2ui: [block] });
                          }
                        }
                      }

                      // render_grafana_panel → A2UI Button linking to Grafana
                      // A2UIRenderer has no iframe component, so we surface the URL as a
                      // clickable button so the SRE can open the panel directly.
                      if (name === "render_grafana_panel") {
                        const url: string = args.url ?? "";
                        if (url) {
                          const labelId = `grafana-lbl-${callId}`;
                          const btnId   = `grafana-btn-${callId}`;
                          const block = [
                            { id: labelId, component: "Text", text: "📊 Open in Grafana →", variant: "caption" },
                            {
                              id: btnId,
                              component: "Button",
                              child: labelId,
                              variant: "secondary",
                              action: { event: { name: "open_url", data: { url } } },
                            },
                          ];
                          const key = JSON.stringify(block);
                          if (!emittedA2UIKeys.has(key)) {
                            emittedA2UIKeys.add(key);
                            emitRenderToolCall(subscriber, "render_a2ui", { a2ui: block });
                          }
                        }
                      }
                    }
                  }

                  // DataPart with function_response — emit TOOL_CALL_RESULT + extract A2UI
                  if (root.kind === "data" && root.data?.response !== undefined) {
                    const meta = root.metadata ?? {};
                    const metaType = meta["adk_type"] ?? "";
                    if (metaType === "function_response" || (!metaType && root.data.response !== undefined)) {
                      // Use ADK-provided id when available; fall back to name (same logic as function_call).
                      const callId = root.data.id || root.data.name;
                      subscriber.next({
                        type: EventType.TOOL_CALL_RESULT,
                        messageId: crypto.randomUUID(),
                        toolCallId: callId,
                        content: "done",
                      });

                      // Extract A2UI v0.9 blocks from function_response text
                      const response = root.data.response;
                      if (response) {
                        let responseText = "";
                        if (typeof response === "string") {
                          responseText = response;
                        } else if (response.content) {
                          const content = Array.isArray(response.content) ? response.content : [response.content];
                          for (const c of content) {
                            if (typeof c === "object" && c.type === "text" && c.text) {
                              responseText = c.text;
                              break;
                            }
                          }
                        } else {
                          responseText = JSON.stringify(response);
                        }
                        if (responseText) {
                          // Extract A2UI v0.9 blocks from function_response text.
                          // Register each key so the final-text pass doesn't re-emit the same block.
                          const { a2uiBlocks: respA2ui } = extractA2UIBlocks(responseText);
                          for (const block of respA2ui) {
                            const key = JSON.stringify(block);
                            if (!emittedA2UIKeys.has(key)) {
                              emittedA2UIKeys.add(key);
                              emitRenderToolCall(subscriber, "render_a2ui", { a2ui: block });
                            }
                          }
                        }
                      }
                    }
                  }
                }
              } else if (state === "failed") {
                const errorMsg = message?.parts
                  ?.map((p: any) => {
                    const root = p.root ?? p;
                    return root.kind === "text" && root.text ? root.text : "";
                  })
                  .filter(Boolean)
                  .join("\n") || "Agent error";
                emitTextEvents(subscriber, `⚠️ **Agent Error**\n\n${errorMsg}`);
              }

            } else if ("type" in event && event.type === "thinking") {
              // Only genuine thinking events — "reasoning" type is no longer emitted.
              const reasoningText = (event.text ?? "").trim();
              if (reasoningText) {
                const reasoningKey = `thinking:${reasoningText}`;
                if (emittedReasoningKeys.has(reasoningKey)) {
                  continue;
                }
                emittedReasoningKeys.add(reasoningKey);
                setReasoningActive(true);
                pushReasoning({
                  type: "thinking",
                  text: reasoningText,
                  ts: event.ts ?? Date.now(),
                });
                emitRenderToolCall(subscriber, "emit_reasoning", {
                  type: "thinking",
                  text: reasoningText,
                });
                log.debug("[A2AAgent] thinking event len=%d", reasoningText.length);
              }

            } else if ("kind" in event && event.kind === "artifact-update") {
              // artifact-update is the authoritative final response (A2A SDK 0.3).
              // Respect the `append` flag per spec: false means replace, true (default) means append.
              if (event.artifact?.parts) {
                let chunk = "";
                for (const part of event.artifact.parts) {
                  const root = (part as any).root ?? part;
                  if (root.kind === "text" && root.text) {
                    // ADK 1.28+ sends thinking parts inside artifact-update events
                    // (not only in status-update "working" events). Extract them
                    // so intermediate reasoning between tool calls is visible.
                    const partMeta = root.metadata ?? {};
                    const isThought = partMeta["adk_thought"] === true;
                    if (isThought) {
                      const textTrimmed = root.text.trim();
                      if (textTrimmed) {
                        const reasoningKey = `thinking:${textTrimmed}`;
                        if (!emittedReasoningKeys.has(reasoningKey)) {
                          emittedReasoningKeys.add(reasoningKey);
                          setReasoningActive(true);
                          pushReasoning({ type: "thinking", text: textTrimmed, ts: Date.now() });
                          emitRenderToolCall(subscriber, "emit_reasoning", {
                            type: "thinking",
                            text: textTrimmed,
                          });
                        }
                      }
                    } else {
                      chunk += root.text;
                    }
                  }
                }
                if ((event as any).append === false) {
                  artifactText = chunk;  // replace — spec says discard previous artifact text
                } else {
                  artifactText += chunk; // append (default)
                }
              }

            }
          }

          // artifact-update is authoritative — fall back to statusText only if
          // ADK sent no artifact (e.g. simple one-shot completions without streaming).
          const finalText = artifactText.trim() ? artifactText : statusText;

          // Stream ended — emit accumulated text as segments
          if (finalText.trim()) {
            // ── 1. Extract Python code execution blocks → emit as tool call events ──
            // Each ```python...``` + ```tool_output...``` pair becomes a TOOL_CALL_*
            // sequence so the UI renders a collapsible CodeExecutionBlock chip instead
            // of raw code blocks inside the text bubble.
            const codeBlockRe = /```(?:python|tool_code)\n([\s\S]*?)\n```(?:\s*```tool_output\n([\s\S]*?)\n```)?/g;
            let textAfterCode = finalText;
            let codeMatch;
            while ((codeMatch = codeBlockRe.exec(finalText)) !== null) {
              const code   = (codeMatch[1] || "").trim();
              const output = (codeMatch[2] || "").trim();
              const callId = `python-${crypto.randomUUID()}`;
              subscriber.next({ type: EventType.TOOL_CALL_START, toolCallId: callId, toolCallName: "run_python_script" });
              subscriber.next({ type: EventType.TOOL_CALL_ARGS,  toolCallId: callId, delta: JSON.stringify({ code, output }) });
              subscriber.next({ type: EventType.TOOL_CALL_END,   toolCallId: callId });
              subscriber.next({ type: EventType.TOOL_CALL_RESULT, messageId: crypto.randomUUID(), toolCallId: callId, content: "executed" });
              // Remove the matched block from the text so it is not rendered again
              textAfterCode = textAfterCode.replace(codeMatch[0], "").trim();
            }

            // ── 2. Extract A2UI blocks from remaining text ─────────────────────────
            const { cleanText, a2uiBlocks } = extractA2UIBlocks(textAfterCode);

            // Emit A2UI blocks — skip any already emitted from function_response
            for (const block of a2uiBlocks) {
              const key = JSON.stringify(block);
              if (!emittedA2UIKeys.has(key)) {
                emittedA2UIKeys.add(key);
                emitRenderToolCall(subscriber, "render_a2ui", { a2ui: block });
              }
            }

            // Emit remaining text (MarkdownRenderer handles tables natively)
            emitTextEvents(subscriber, cleanText);
          }

        } catch (err) {
          if (err instanceof Error && err.name === "AbortError") {
            setReasoningActive(false);
            subscriber.next({ type: EventType.RUN_FINISHED, threadId, runId });
            subscriber.complete();
            return;
          }
          const message = err instanceof Error ? err.message : String(err);
          log.error(`[A2AAgent] stream error agent=${agent.name} (${agent.url})`, message);
          emitTextEvents(subscriber, `⚠️ **Agent Error**\n\n${message}`);
        }

        setReasoningActive(false);
        subscriber.next({ type: EventType.RUN_FINISHED, threadId, runId });
        subscriber.complete();
      })().catch((err) => subscriber.error(err));

      return () => {
        controller.abort();
        runRegistry.delete(threadId);
      };
    });
  }

  clone(): A2AAgent {
    return new A2AAgent(this.cfg);
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function extractTextContent(msg: unknown): string {
  if (!msg) return "";
  const m = msg as { content?: unknown };
  if (typeof m.content === "string") return m.content;
  if (Array.isArray(m.content)) {
    return (m.content as Array<{ type?: string; text?: string }>)
      .filter((p) => p.type === "text")
      .map((p) => p.text ?? "")
      .join(" ");
  }
  return String(m.content ?? "");
}

function emitTextEvents(
  subscriber: { next: (e: BaseEvent) => void },
  content: string
): void {
  if (!content.trim()) return;
  const messageId = crypto.randomUUID();
  subscriber.next({ type: EventType.TEXT_MESSAGE_START, messageId, role: "assistant" });
  subscriber.next({ type: EventType.TEXT_MESSAGE_CONTENT, messageId, delta: content });
  subscriber.next({ type: EventType.TEXT_MESSAGE_END, messageId });
}

function emitRenderToolCall(
  subscriber: { next: (e: BaseEvent) => void },
  toolName: string,
  args: Record<string, unknown>
): void {
  const toolCallId = crypto.randomUUID();
  const resultMessageId = crypto.randomUUID();

  subscriber.next({
    type: EventType.TOOL_CALL_START,
    toolCallId,
    toolCallName: toolName,
  });
  subscriber.next({
    type: EventType.TOOL_CALL_ARGS,
    toolCallId,
    delta: JSON.stringify(args),
  });
  subscriber.next({ type: EventType.TOOL_CALL_END, toolCallId });
  subscriber.next({
    type: EventType.TOOL_CALL_RESULT,
    messageId: resultMessageId,
    toolCallId,
    content: "rendered",
  });
}


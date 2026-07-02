import { v4 as uuidv4 } from "uuid";
import { loggedFetch, createLogger } from "@/lib/logger";
import type {
  A2ATask,
  A2ASendRequest,
  A2AGetRequest,
  A2AResponse,
  A2AMessage,
} from "@/types";

const log = createLogger("a2a-client.ts");

// ── Standard A2A SSE event types (from a2a-sdk protocol) ──────────────────────

export interface A2AStatusUpdateEvent {
  kind: "status-update";
  taskId: string;
  contextId: string;
  final: boolean;
  status: {
    state: "submitted" | "working" | "completed" | "failed" | "canceled";
    message?: {
      kind: "message";
      messageId: string;
      role: "agent" | "user";
      parts: Array<{ kind: string; text?: string; [key: string]: unknown }>;
    };
    timestamp?: string;
  };
  metadata?: Record<string, unknown>;
}

export interface A2AArtifactUpdateEvent {
  kind: "artifact-update";
  taskId: string;
  contextId: string;
  lastChunk: boolean;
  artifact: {
    artifactId: string;
    parts: Array<{ kind: string; text?: string; [key: string]: unknown }>;
  };
}

export interface A2AThinkingEvent {
  type: "thinking";
  text: string;
  ts?: number;
}

export interface A2AReasoningEvent {
  type: "reasoning";
  text: string;
  ts?: number;
}

export type A2AStreamEvent =
  | A2AStatusUpdateEvent
  | A2AArtifactUpdateEvent
  | A2AThinkingEvent
  | A2AReasoningEvent;

const POLL_INTERVAL_MS = 1000;
const MAX_POLL_ATTEMPTS = 60;

export interface UserContext {
  userId?: string;
  userName?: string;
  userType?: string;
  userAgent?: string;
  userIp?: string;
  loginId?: string;
  accessToken?: string;
  /** IANA timezone string from the browser, e.g. "America/Los_Angeles". Used by the
   *  super agent to convert natural-language times ("10 AM") to UTC epoch ms. */
  timezone?: string;
  /** Current epoch time in milliseconds from the browser at request time.
   *  Used by the super agent to anchor relative time expressions ("2AM to 10AM")
   *  to the correct calendar day in the user's timezone. */
  currentEpochMs?: number;
}

/**
 * Sends a user query to an A2A-compatible ADK agent and polls until completion.
 */
export async function sendA2AQuery(
  agentUrl: string,
  userText: string,
  sessionId?: string,
  userCtx?: UserContext
): Promise<A2ATask> {
  const taskId = uuidv4();

  const userMessage: A2AMessage = {
    role: "user",
    parts: [{ type: "text", text: userText }],
  };

  const sendRequest: A2ASendRequest = {
    jsonrpc: "2.0",
    method: "message/send",
    id: 1,
    params: {
      message: { ...userMessage, messageId: taskId },
      configuration: {
        ...(sessionId && { sessionId }),
      },
    },
  };

  const sendRes = await fetchA2A(agentUrl, sendRequest, userCtx);

  if (sendRes.error) {
    throw new Error(`A2A send error: ${sendRes.error.message}`);
  }

  const initialTask = sendRes.result!;

  if (
    initialTask.status.state === "completed" ||
    initialTask.status.state === "failed"
  ) {
    return initialTask;
  }

  return pollTask(agentUrl, taskId, userCtx);
}

async function pollTask(agentUrl: string, taskId: string, userCtx?: UserContext): Promise<A2ATask> {
  const getRequest: A2AGetRequest = {
    jsonrpc: "2.0",
    method: "tasks/get",
    id: 2,
    params: { id: taskId },
  };
  // Note: tasks/get is still valid in a2a-sdk v0.3 for polling task status

  for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
    await sleep(POLL_INTERVAL_MS);

    const res = await fetchA2A(agentUrl, getRequest, userCtx);

    if (res.error) {
      throw new Error(`A2A poll error: ${res.error.message}`);
    }

    const task = res.result!;

    if (task.status.state === "completed" || task.status.state === "failed") {
      return task;
    }

    if (task.status.state === "canceled") {
      throw new Error("Task was canceled by the agent");
    }
  }

  throw new Error(`Task timed out after ${MAX_POLL_ATTEMPTS} seconds`);
}

function buildUserHeaders(userCtx?: UserContext): Record<string, string> {
  if (!userCtx) return {};
  const headers: Record<string, string> = {};
  if (userCtx.userType) headers["wm_llm_gw.user_type"] = userCtx.userType;
  if (userCtx.loginId) headers["wm_llm_gw.user_name"] = userCtx.loginId;
  if (userCtx.userAgent) headers["wm_llm_gw.user_agent"] = userCtx.userAgent;
  if (userCtx.userIp) headers["wm_llm_gw.user_ip"] = userCtx.userIp;
  // Send loginId in two header names so the super-agent backend can capture
  // it regardless of HTTP normalisation (some proxies lowercase header names).
  // x-login-id is the canonical form; loginId is kept for backward compat.
  if (userCtx.loginId) {
    headers["x-login-id"] = userCtx.loginId;
    headers["loginId"] = userCtx.loginId;
  }

  if (userCtx.userName)  headers["x-user-name"]     = userCtx.userName;
  if (userCtx.timezone)        headers["x-user-timezone"]     = userCtx.timezone;
  if (userCtx.currentEpochMs) headers["x-current-epoch-ms"]  = String(userCtx.currentEpochMs);
  if (userCtx.accessToken) headers["Authorization"] = `Bearer ${userCtx.accessToken}`;

  return headers;
}

async function fetchA2A(
  url: string,
  body: A2ASendRequest | A2AGetRequest,
  userCtx?: UserContext
): Promise<A2AResponse> {
  const ui = userCtx?.loginId ?? '-';

  const res = await loggedFetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildUserHeaders(userCtx),
    },
    body: JSON.stringify(body),
    ui,
    tag: "a2a-client.ts",
  });

  if (!res.ok) {
    // loggedFetch already emitted the ERROR line; read body for the thrown message
    let errBody = "";
    try {
      errBody = await res.text();
    } catch {
      errBody = "(unreadable)";
    }
    throw new Error(`HTTP ${res.status} ${res.statusText} — ${url} — body: ${errBody.slice(0, 300)}`);
  }

  return res.json() as Promise<A2AResponse>;
}

/**
 * Extracts the final text response from a completed A2A task.
 */
export function extractTaskText(task: A2ATask): string {
  const parts: string[] = [];

  if (task.status.message) {
    for (const part of task.status.message.parts) {
      if (part.type === "text" && part.text) {
        parts.push(part.text);
      }
    }
  }

  if (task.artifacts && task.artifacts.length > 0) {
    for (const artifact of task.artifacts) {
      for (const part of artifact.parts) {
        if (part.type === "text" && part.text) {
          parts.push(part.text);
        }
      }
    }
  }

  if (parts.length === 0 && task.history) {
    const agentMessages = task.history.filter((m) => m.role === "agent");
    const last = agentMessages[agentMessages.length - 1];
    if (last) {
      for (const part of last.parts) {
        if (part.type === "text" && part.text) {
          parts.push(part.text);
        }
      }
    }
  }

  return parts.join("\n\n") || "No response received from agent.";
}

/**
 * Streams a user query via standard A2A protocol (message/stream).
 *
 * ADK 1.28's A2AStarletteApplication handles this natively — SSE events
 * follow the standard A2A protocol format:
 *   kind: "status-update" — task state transitions (submitted → working → completed)
 *   kind: "artifact-update" — streamed output (text parts with the agent's answer)
 */
export async function* streamA2AQuery(
  agentUrl: string,
  userText: string,
  sessionId?: string,
  userCtx?: UserContext,
  signal?: AbortSignal
): AsyncGenerator<A2AStreamEvent> {
  const taskId = uuidv4();

  const body = {
    jsonrpc: "2.0",
    method: "message/stream",
    id: 1,
    params: {
      message: {
        role: "user",
        parts: [{ type: "text", text: userText }],
        messageId: taskId,
        // contextId is the A2A SDK 0.3 session identifier — ADK maps this directly
        // to the ADK session_id (see request_converter.py line 111).
        // Without it, ADK generates a new contextId per request → new session every time.
        ...(sessionId && { contextId: sessionId }),
      },
      configuration: {
        ...(userCtx?.userId && { acceptedOutputModes: ["text/plain"] }),
      },
    },
  };

  const ui = userCtx?.loginId ?? '-';

  // ── Retry loop for transient connection errors (super-agent restart) ──
  // Only retries "fetch failed" / ECONNREFUSED — NOT HTTP-level errors.
  const MAX_CONNECT_RETRIES = 5;
  const RETRY_DELAY_MS = 3000;
  let res: Response | undefined;

  for (let attempt = 1; attempt <= MAX_CONNECT_RETRIES; attempt++) {
    try {
      res = await loggedFetch(agentUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          ...buildUserHeaders(userCtx),
        },
        body: JSON.stringify(body),
        signal,
        ui,
        tag: "a2a-client.ts",
      });
      break; // fetch succeeded (may still be an HTTP error — handled below)
    } catch (err) {
      if (signal?.aborted) throw err;
      const msg = err instanceof Error ? err.message : String(err);
      // Only retry on connection-level failures (fetch failed, ECONNREFUSED, etc.)
      if (!/fetch failed|ECONNREFUSED|ECONNRESET|ETIMEDOUT/i.test(msg)) throw err;
      if (attempt === MAX_CONNECT_RETRIES) throw err;
      log.warn(`[streamA2AQuery] connection attempt ${attempt}/${MAX_CONNECT_RETRIES} failed (${msg}), retrying in ${RETRY_DELAY_MS}ms`);
      await sleep(RETRY_DELAY_MS);
    }
  }

  if (!res!.ok || !res!.body) {
    // loggedFetch already emitted the ERROR line
    const errText = await res!.text().catch(() => "(unreadable)");
    throw new Error(`HTTP ${res!.status} ${res!.statusText} — ${agentUrl} — ${errText.slice(0, 300)}`);
  }

  const reader = res!.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() ?? "";

    for (const chunk of parts) {
      for (const line of chunk.split(/\r?\n/)) {
        if (!line.startsWith("data:")) continue;
        const json = line.slice(5).trim();
        if (!json) continue;
        try {
          const parsed = JSON.parse(json);
          // A2A SSE events are wrapped in a JSON-RPC response envelope:
          // {"id":1, "jsonrpc":"2.0", "result": {"kind":"status-update",...}}
          const event = parsed?.result ?? parsed;
          // Standard A2A events have `kind` (status-update, artifact-update).
          // Custom thinking/reasoning events have `type` instead.
          if (event?.kind) {
            yield event as A2AStreamEvent;
          } else if (event?.type === "thinking" || event?.type === "reasoning") {
            yield event as A2AStreamEvent;
          }
        } catch {
          // ignore malformed SSE lines
        }
      }
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

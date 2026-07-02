// ─── A2A Protocol Types ────────────────────────────────────────────────────

export interface A2ATextPart {
  type: "text";
  text: string;
}

export interface A2ADataPart {
  type: "data";
  data: Record<string, unknown>;
}

export type A2APart = A2ATextPart | A2ADataPart;

export interface A2AMessage {
  role: "user" | "agent";
  parts: A2APart[];
}

export interface A2ATask {
  id: string;
  status: {
    state: "submitted" | "working" | "completed" | "failed" | "canceled";
    message?: A2AMessage;
    timestamp?: string;
  };
  artifacts?: A2AArtifact[];
  history?: A2AMessage[];
}

export interface A2AArtifact {
  name?: string;
  description?: string;
  parts: A2APart[];
  index?: number;
}

export interface A2ASendRequest {
  jsonrpc: "2.0";
  method: "message/send";
  id: number;
  params: {
    message: A2AMessage & { messageId?: string };
    configuration?: Record<string, unknown>;
  };
}

export interface A2AGetRequest {
  jsonrpc: "2.0";
  method: "tasks/get";
  id: number;
  params: { id: string };
}

export interface A2AResponse {
  jsonrpc: "2.0";
  id: number;
  result?: A2ATask;
  error?: { code: number; message: string };
}

// ─── Agent Config Types ───────────────────────────────────────────────────

export interface AgentConfig {
  id: string;
  name: string;
  url: string;
  emoji?: string;
  description?: string;
}

// ─── UI Types ─────────────────────────────────────────────────────────────

export type MessageRole = "user" | "assistant";

export interface ErrorDetail {
  error: string;
  agentId?: string;
  agentName?: string;
  agentUrl?: string;
  hint?: string;
  taskState?: string;
  stack?: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp?: Date;
  user_id?: string;
  user_name?: string;
  parsedData?: ParsedResponse;
  isStreaming?: boolean;
  error?: string;
  errorDetail?: ErrorDetail;
}

export interface ParsedResponse {
  text: string;
}

// ─── Session / Conversation Types ─────────────────────────────────────────

export interface Conversation {
  session_id: string;
  title: string;
  last_update_time: number;
  user_id: string;
  shared_by?: string;
  permission?: "read" | "write" | "admin";
  public?: boolean;        // true = visible to all users in Public section
  tags?: string[];         // custom labels e.g. ["Alert", "Incident-123"]
}

export interface SessionMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

/** A single entry in the UI event log stored per session in Redis.
 *  Used to replay session history on page refresh.
 *  Standard A2A event types (status-update / artifact-update) are primary.
 *  Legacy types (progress, graph, complete) are kept read-only for
 *  backward-compatible replay of existing session histories.
 *
 *  "injection" events are pushed by external subsystems (openclaw monitoring
 *  loops, alertmanager, deployment agents) via super-agent's generic
 *  POST /sessions/{id}/inject_message endpoint. Their payload is a
 *  Markdown `content` string — super-agent does not parse it. */
export interface SessionUiEvent {
  type:
    | "user"
    | "complete"
    | "error"
    | "artifact-update"
    | "status-update"
    | "progress"
    | "graph"
    | "injection"
    | "thinking"
    | "reasoning";
  ts: number;
  text?: string;
  message?: string;
  kind?: "status-update" | "artifact-update";
  taskId?: string;
  contextId?: string;
  // User identity — set on "user" type events for multi-participant sessions
  user_id?: string;
  user_name?: string;
  // Progress event fields (tool call in-progress, from legacy runner path)
  tool?: string;
  call_id?: string;
  label?: string;
  status?: "running" | "done";
  args?: Record<string, unknown>;
  // Injection event — markdown content pushed via inject_message endpoint.
  // Producers self-identify inside the markdown (e.g. "## openclaw monitoring
  // update for INC-..."), super-agent is payload-agnostic.
  content?: string;
}

/** Decoded injection event with a real Date — what the chat UI actually
 *  consumes. Both the replay path (from /sessions/{id}/messages `events` array)
 *  and the live SSE path (from /sessions/{id}/events/subscribe) emit this
 *  normalised shape. */
export interface InjectionEvent {
  id: string;
  content: string;
  timestamp: Date;
  /** Producer self-identifier (e.g. "openclaw/sre-triage") parsed from the
   *  sidecar HTML comment marker on the first line of `content`. Optional —
   *  legacy producers without the marker won't set this. */
  source?: string;
  /** Free-form tags from the sidecar marker (e.g. ["alert:INC123",
   *  "kind:verdict_change", "verdict:false_positive"]). Used for UI filtering
   *  / badge rendering. */
  tags?: string[];
}

/** UI live-stream connection state for an active SSE subscription.
 *  Surfaced by `subscribeToSessionEvents` so ChatInterface can render
 *  a status badge — the user always knows whether they're seeing live
 *  observations or a stale snapshot. */
export type SessionStreamStatus =
  | "connecting"
  | "live"
  | "reconnecting"
  | "offline";

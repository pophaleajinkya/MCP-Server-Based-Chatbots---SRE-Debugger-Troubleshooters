import type {
  Conversation,
  InjectionEvent,
  SessionMessage,
  SessionStreamStatus,
  SessionUiEvent,
} from "@/types";

export async function fetchConversations(userId = ""): Promise<Conversation[]> {
  try {
    const res = await fetch(`/api/sessions?user_id=${encodeURIComponent(userId)}`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.sessions ?? [];
  } catch {
    return [];
  }
}

export interface SessionHistory {
  messages: SessionMessage[];
  /** Present for sessions created after the event-sourcing upgrade.
   *  When available, the UI replays these directly for exact visual fidelity. */
  events?: SessionUiEvent[];
  /** Out-of-band injection events (e.g. openclaw monitoring updates)
   *  already pulled out of `events` and normalised — ChatInterface renders
   *  them as inline cards interleaved with the chat turns. */
  injections?: InjectionEvent[];
}

/**
 * Best-effort session termination — marks the session as ended in the backend
 * store (Redis via ADK). Fire-and-forget: errors are swallowed so a failed
 * termination never blocks the UI.
 */
export async function terminateSession(sessionId: string, userId = ""): Promise<void> {
  try {
    await fetch(
      `/api/sessions/${encodeURIComponent(sessionId)}?user_id=${encodeURIComponent(userId)}`,
      { method: "DELETE", cache: "no-store" }
    );
  } catch {
    // best-effort — ignore errors
  }
}

/** Make a session public (visible to all) and/or attach custom tags. */
export async function patchSessionVisibility(
  sessionId: string,
  userId: string,
  opts: { public?: boolean; tags?: string[] }
): Promise<boolean> {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/visibility`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, public: opts.public ?? false, tags: opts.tags ?? [] }),
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function fetchSessionMessages(
  sessionId: string,
  userId = ""
): Promise<SessionHistory> {
  try {
    const res = await fetch(
      `/api/sessions/${encodeURIComponent(sessionId)}/messages?user_id=${encodeURIComponent(userId)}`,
      { cache: "no-store" }
    );
    if (!res.ok) return { messages: [] };
    const data = await res.json();
    const events = data.events as SessionUiEvent[] | undefined;
    return {
      messages: data.messages ?? [],
      events,
      injections: events ? extractInjectionsFromEvents(events) : undefined,
    };
  } catch {
    return { messages: [] };
  }
}

// ─── Injection events (out-of-band observations) ─────────────────────────────

/**
 * Parse the sidecar HTML-comment marker out of an injected markdown payload.
 *
 * Marker format (always on the FIRST line, by convention enforced by producers
 * such as the openclaw plugin's lifecycleRoute.ts):
 *
 *   <!--sre-meta:source=openclaw/sre-triage;tags=alert:INC123,kind:verdict_change-->
 *
 * Returns:
 *   - `content` with the marker line stripped (so the rendered card never
 *     shows the comment, even if a future MarkdownRenderer enables rehypeRaw).
 *   - `source` and `tags` populated when present; both are optional so
 *     legacy producers keep working.
 *
 * This is the workaround for super-agent's `inject_message` accepting only
 * `content: string`. Once super-agent gains native sidecar fields, this parser
 * can be removed and the producers can stop emitting the marker.
 */
const SIDECAR_RE = /^\s*<!--\s*sre-meta:([^>]*?)-->\s*\n?/;

export function parseSidecarMeta(content: string): {
  content: string;
  source?: string;
  tags?: string[];
} {
  const m = content.match(SIDECAR_RE);
  if (!m) return { content };
  const stripped = content.slice(m[0].length);
  // Body looks like: "source=openclaw/sre-triage;tags=alert:X,kind:Y"
  const fields = m[1].split(";").map((s) => s.trim()).filter(Boolean);
  let source: string | undefined;
  let tags: string[] | undefined;
  for (const f of fields) {
    const eq = f.indexOf("=");
    if (eq < 0) continue;
    const k = f.slice(0, eq).trim().toLowerCase();
    const v = f.slice(eq + 1).trim();
    if (!v) continue;
    if (k === "source") {
      source = v;
    } else if (k === "tags") {
      tags = v
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
    }
  }
  return { content: stripped, source, tags };
}

/**
 * Normalise injection events out of the raw replay event log.
 * Producers (openclaw, alertmanager, etc.) write these via super-agent's
 * POST /sessions/{id}/inject_message — super-agent stores them in
 * Redis (`agent:ui_events`) alongside user/assistant events so they
 * survive a page refresh. The rendered chat keeps them visually
 * distinct (see InjectionCard).
 */
export function extractInjectionsFromEvents(
  events: SessionUiEvent[]
): InjectionEvent[] {
  const out: InjectionEvent[] = [];
  for (let i = 0; i < events.length; i++) {
    const ev = events[i];
    if (ev.type !== "injection") continue;
    const raw = ev.content ?? ev.text ?? "";
    if (!raw.trim()) continue;
    const { content, source, tags } = parseSidecarMeta(raw);
    out.push({
      id: `inj-replay-${ev.ts}-${i}`,
      content,
      source,
      tags,
      // super-agent stores `ts` in Unix seconds (float). Guard against
      // ms-precision timestamps too so we don't silently render 1970 dates.
      timestamp: new Date(ev.ts > 1e12 ? ev.ts : ev.ts * 1000),
    });
  }
  return out;
}

/**
 * Open a live SSE subscription to the super-agent event stream (proxied
 * through /api/sessions/{id}/events/subscribe). `onInjection` fires for
 * every new injection event. Returns a disposer — call it on unmount or
 * when the active session changes to close the EventSource cleanly.
 *
 * The Next.js proxy attaches Walmart LLM Gateway headers server-side,
 * so the browser never sees bearer tokens or loginId.
 *
 * `onStatusChange` (optional) fires whenever the underlying EventSource
 * transitions between "connecting" → "live" → "reconnecting" → "offline".
 * The transitions are debounced ~400ms on the "reconnecting" side so a
 * sub-second blip doesn't flash the badge — common on EventSource which
 * auto-retries every 3s by default.
 */
export function subscribeToSessionEvents(
  sessionId: string,
  onInjection: (event: InjectionEvent) => void,
  opts?: {
    userId?: string;
    onError?: (err: Event) => void;
    onStatusChange?: (status: SessionStreamStatus) => void;
  }
): () => void {
  if (typeof window === "undefined") return () => {};
  if (!sessionId) return () => {};

  const qs = opts?.userId
    ? `?user_id=${encodeURIComponent(opts.userId)}`
    : "";
  const url = `/api/sessions/${encodeURIComponent(sessionId)}/events/subscribe${qs}`;
  const es = new EventSource(url, { withCredentials: true });

  // ── Status tracking ───────────────────────────────────────────────────────
  // Track last emitted status so we don't fire identical updates back-to-back.
  let lastStatus: SessionStreamStatus | null = null;
  let pendingDebounce: ReturnType<typeof setTimeout> | null = null;

  const emitStatus = (next: SessionStreamStatus, debounceMs = 0) => {
    if (!opts?.onStatusChange) return;
    if (pendingDebounce) {
      clearTimeout(pendingDebounce);
      pendingDebounce = null;
    }
    const fire = () => {
      if (next === lastStatus) return;
      lastStatus = next;
      opts.onStatusChange?.(next);
    };
    if (debounceMs > 0) {
      pendingDebounce = setTimeout(fire, debounceMs);
    } else {
      fire();
    }
  };

  // Initial state — EventSource starts in CONNECTING (readyState 0).
  emitStatus("connecting");

  // ── Frame handling ────────────────────────────────────────────────────────
  // We don't dictate super-agent's event name — it emits plain `data: {...}`
  // frames which show up under the default `message` event. Producers on
  // the super-agent side can still emit named events (e.g. `event: injection`)
  // without breaking this default handler.
  const handler = (e: MessageEvent) => {
    try {
      const rawFrame = JSON.parse(e.data) as SessionUiEvent;
      if (rawFrame?.type !== "injection") return;
      const rawContent = rawFrame.content ?? rawFrame.text ?? "";
      if (!rawContent.trim()) return;
      const { content, source, tags } = parseSidecarMeta(rawContent);
      onInjection({
        id: `inj-live-${rawFrame.ts ?? Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        content,
        source,
        tags,
        timestamp: rawFrame.ts
          ? new Date(rawFrame.ts > 1e12 ? rawFrame.ts : rawFrame.ts * 1000)
          : new Date(),
      });
    } catch {
      // Unknown / malformed frame — ignore (keeps the stream resilient
      // to future event types added on the super-agent side).
    }
  };

  const onOpen = () => emitStatus("live");
  const onErr = (err: Event) => {
    // EventSource readyState semantics:
    //   0 (CONNECTING) → browser is auto-reconnecting after a transient drop
    //   2 (CLOSED)     → terminal error (server returned non-2xx, etc.)
    if (es.readyState === EventSource.CLOSED) {
      emitStatus("offline");
    } else {
      // Debounce — most "errors" recover within ~3s under EventSource's
      // built-in retry. Don't flash "Reconnecting…" for sub-second blips.
      emitStatus("reconnecting", 400);
    }
    if (opts?.onError) opts.onError(err);
  };

  es.addEventListener("message", handler);
  es.addEventListener("injection", handler); // also accept named `injection` events
  es.addEventListener("open", onOpen);
  es.addEventListener("error", onErr);

  return () => {
    if (pendingDebounce) {
      clearTimeout(pendingDebounce);
      pendingDebounce = null;
    }
    es.removeEventListener("message", handler);
    es.removeEventListener("injection", handler);
    es.removeEventListener("open", onOpen);
    es.removeEventListener("error", onErr);
    es.close();
    // Caller-initiated dispose — no need to fire "offline" here.
  };
}

"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { CopilotKit, useCopilotChatInternal } from "@copilotkit/react-core";
import { TextMessage, ActionExecutionMessage, MessageRole } from "@copilotkit/runtime-client-gql";
import { useConversations } from "@/hooks/useConversations";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { useViewContext } from "@/contexts/ViewContext";
import { fetchSessionMessages, subscribeToSessionEvents } from "@/lib/sessions-client";
import { groupIntoTurns, buildMessagesFromEvents, toolLabel, toolArgPreview } from "@/lib/chat-helpers";
import type { Turn, AssistantSegment } from "@/lib/chat-helpers";
import { formatDistanceToNow } from "date-fns";
import { MessageItem, CopyButton } from "./MessageItem";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { A2UIRenderer } from "./A2UIRenderer";
import { ChatInput } from "./ChatInput";
import { AgentSelector } from "./AgentSelector";
import { Sidebar } from "./Sidebar";
import { HowToPanel } from "./HowToPanel";
import { AlertRetryScheduler } from "./AlertRetryScheduler";
import { InjectionCard } from "./InjectionCard";
import { ReasoningStream } from "./reasoning/ReasoningStream";
import { useReasoningEntries } from "@/lib/reasoning-store-hook";
import { clearReasoning, pushReasoning, setReasoningActive } from "@/lib/reasoning-store";
import type { AgentConfig, InjectionEvent, SessionStreamStatus, SessionUiEvent } from "@/types";

// Re-export for any consumers that import Turn/AssistantSegment from here
export type { Turn, AssistantSegment };

function extractAlertId(text: string): string | null {
  const incMatch = text.match(/\bINC\d{7,}\b/);
  if (incMatch) return incMatch[0];
  
  const genericMatch = text.match(/\b(?:alert_id|alert id|alert)[\s:=]+([A-Za-z0-9_-]+)/i);
  if (genericMatch && genericMatch[1]) {
    // Avoid matching small generic words if possible, but return whatever follows "alert"
    return genericMatch[1];
  }
  
  return null;
}

// ─── Inner chat area (needs CopilotKit context) ───────────────────────────────

interface ChatAreaProps {
  activeAgent: AgentConfig | null;
  activeSessionId: string;
  userId: string;
  userName?: string;
  agentsLoading?: boolean;
  onFirstMessage: (title: string) => void;
  onMessageComplete: () => void;
  prefillValue?: string;
  onPrefillConsumed?: () => void;
  isAlertSession?: boolean;
}

function CopilotChatArea({ activeAgent, activeSessionId, userId, userName, _isReadOnly, agentsLoading = false, onFirstMessage, onMessageComplete, prefillValue, onPrefillConsumed, isAlertSession }: ChatAreaProps & { _isReadOnly?: boolean; agentsLoading?: boolean }) {
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const { getContextSummary } = useViewContext();

  // useCopilotChatInternal gives us AG-UI `messages` + `sendMessage` + `setMessages`
  const { messages, sendMessage, stopGeneration, isLoading, setMessages } = useCopilotChatInternal();

  // Stabilize setMessages in a ref so it doesn't re-trigger history fetch on every render
  const setMessagesRef = useRef(setMessages);
  setMessagesRef.current = setMessages; // update ref synchronously on every render (no effect needed)

  const isFirstMessage = useRef(true);
  const prevLoading = useRef(false);
  const unmountedRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  // Track whether initial history has loaded — use instant scroll for history, smooth for live messages
  const historyLoadedRef = useRef(false);

  // Polling ref — tracks an active setInterval when a turn is still in-progress
  // after page refresh (user count > complete count in Redis events).
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const POLL_INTERVAL_MS = 10_000;
  const MAX_POLL_DURATION_MS = 2 * 60 * 1000; // safety cap: stop polling after 2 minutes

  // True while the poll loop is active — drives the streaming placeholder in the UI
  // so the user sees the chat is still working after a mid-processing refresh.
  const [isPolling, setIsPolling] = useState(false);

  // Track the event count from the last poll so we can skip re-rendering when
  // nothing changed.  This prevents the reasoning panel expand→collapse flicker
  // that happens when replayEvents() is called with identical data.
  const lastPollEventCountRef = useRef<number>(0);

  // Per-round timestamps: one entry per user→AI exchange, added on send, completed on finish
  const [roundTimes, setRoundTimes] = useState<Array<{ sentAt: Date; completedAt?: Date }>>([]);

  // Out-of-band "injection" events — producers (openclaw monitoring loops,
  // alertmanager, etc.) push these via super-agent's /sessions/{id}/inject_message.
  // Kept in a separate state rather than CopilotKit's message store so they
  // never pollute the LLM conversation history or tool-call replay.
  const [injections, setInjections] = useState<InjectionEvent[]>([]);

  // Live SSE connection status for the out-of-band observation stream.
  // Surfaced in the chat as a tiny badge so the user always knows whether
  // the openclaw monitoring loop is delivering live updates or whether
  // they're looking at a stale snapshot. Resets on session switch.
  const [liveStatus, setLiveStatus] = useState<SessionStreamStatus>("connecting");
  const { entries: reasoningEntries, isActive: reasoningIsActive } = useReasoningEntries();



  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
    };
  }, []);

  // ── Load session history using CopilotKit-native TextMessage + setMessages ──
  // If the last turn is incomplete (user count > complete count), starts polling
  // Redis every POLL_INTERVAL_MS to pick up new events until the turn finishes.
  useEffect(() => {
    setHistoryLoading(true);
    // Assume continuation immediately so a message sent before history resolves
    // never triggers onFirstMessage (title-overwrite) on an existing conversation.
    // Corrected to true below only if the session turns out to be brand-new.
    isFirstMessage.current = false;

    let cancelled = false;

    // Stop any active poll from a previous session
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    lastPollEventCountRef.current = 0;

    // Reset injections when switching sessions so stale observations from a
    // previous conversation don't leak into the new chat. Also reset the
    // live-status badge so the new session starts in "connecting" state until
    // the SSE handshake completes.
    setInjections([]);
    setLiveStatus("connecting");
    clearReasoning();

    /** Check whether the event list has an open turn.
     *  Case 1: more USER events than terminal events (COMPLETE/ARTIFACT-UPDATE/ERROR)
     *  Case 2: intermediate events (thinking/progress/status-update) exist but
     *          NO user and NO complete yet — the backend is working but hasn't
     *          written the user event yet (it arrives via _after_event/after_agent).
     *  Case 3: intermediate events exist AFTER the last terminal event — a
     *          follow-up turn has started but hasn't finished yet. */
    function hasIncompleteTurn(events: SessionUiEvent[]): boolean {
      let users = 0;
      let completes = 0;
      let hasIntermediate = false;
      let lastTerminalIdx = -1;
      for (let i = 0; i < events.length; i++) {
        const ev = events[i];
        if (ev.type === "user") users++;
        else if (ev.type === "complete" || ev.type === "artifact-update" || ev.type === "error") {
          completes++;
          lastTerminalIdx = i;
        }
        else if (ev.type === "thinking" || ev.type === "progress" || ev.type === "status-update" || ev.type === "reasoning") hasIntermediate = true;
      }
      // Unbalanced user/complete counts
      if (users > completes) return true;
      // No user event yet but intermediate events exist with no complete — still processing
      if (hasIntermediate && completes === 0) return true;
      // Intermediate events exist AFTER the last complete — follow-up turn started
      // but backend hasn't written user+complete for it yet.
      if (lastTerminalIdx >= 0 && lastTerminalIdx < events.length - 1) {
        for (let j = lastTerminalIdx + 1; j < events.length; j++) {
          const ev = events[j];
          if (ev.type === "thinking" || ev.type === "progress" || ev.type === "status-update" || ev.type === "reasoning") {
            return true;
          }
        }
      }
      return false;
    }

    /** Replay events into CopilotKit messages + reasoning panel. */
    function replayEvents(events: SessionUiEvent[]) {
      clearReasoning();
      const reasoningEvents = events.filter(
        (
          event
        ): event is typeof event & { type: "thinking" | "reasoning"; text: string } =>
          (event.type === "thinking" || event.type === "reasoning") && !!event.text?.trim()
      );
      if (reasoningEvents.length > 0) {
        for (const event of reasoningEvents) {
          pushReasoning({
            type: event.type,
            text: event.text.trim(),
            ts: event.ts > 1e12 ? event.ts : event.ts * 1000,
          });
        }
      }
      // Keep reasoning panel active only while turn is still in-progress
      setReasoningActive(hasIncompleteTurn(events));
      setMessagesRef.current(buildMessagesFromEvents(events));
    }

    async function loadHistory() {
      try {
        const { messages: sessionMsgs, events, injections: replayInjections } =
          await fetchSessionMessages(activeSessionId, userId);
        if (cancelled) return;

        // Seed injection state from the persisted event log so a page
        // refresh restores previous openclaw observations in-place.
        if (replayInjections?.length) {
          setInjections(replayInjections);
        }

        const isEmpty = sessionMsgs.length === 0 && !events?.length;
        if (isEmpty) {
          isFirstMessage.current = true;
          return;
        }

        // Event-sourced replay (exact visual fidelity)
        if (events?.length) {
          // Set isPolling BEFORE replayEvents — CopilotKit's setMessages may
          // trigger a synchronous render; isPolling must already be true so
          // the streaming indicator shows on the very first paint.
          const turnOpen = hasIncompleteTurn(events);
          if (turnOpen) setIsPolling(true);

          replayEvents(events);
          lastPollEventCountRef.current = events.length;

          // ── Polling: if the last turn is still in-progress, poll Redis
          // until the backend writes a "complete" event. This handles the
          // mid-processing page refresh case where the SSE stream died but
          // the backend is still working.
          if (turnOpen) {
            const pollStart = Date.now();
            let pollInFlight = false; // guard against overlapping fetches
            pollRef.current = setInterval(async () => {
              // Safety cap — stop polling after MAX_POLL_DURATION_MS
              if (Date.now() - pollStart > MAX_POLL_DURATION_MS) {
                if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                setIsPolling(false);
                setReasoningActive(false);
                return;
              }
              // Skip if previous poll fetch is still in-flight
              if (pollInFlight) return;
              pollInFlight = true;
              try {
                const fresh = await fetchSessionMessages(activeSessionId, userId);
                if (cancelled || !fresh.events?.length) return;

                // Skip replay if events haven't changed — avoids the
                // reasoning panel expand→collapse flicker on every poll cycle.
                if (fresh.events.length === lastPollEventCountRef.current) return;

                // ── Incremental update: only push NEW reasoning entries ──
                // Avoids clearReasoning() → re-push-all flicker.
                const prevCount = lastPollEventCountRef.current;
                lastPollEventCountRef.current = fresh.events.length;

                const newEvents = fresh.events.slice(prevCount);
                const newReasoningEvents = newEvents.filter(
                  (ev: SessionUiEvent): ev is SessionUiEvent & { type: "thinking" | "reasoning"; text: string } =>
                    (ev.type === "thinking" || ev.type === "reasoning") && !!ev.text?.trim()
                );
                for (const ev of newReasoningEvents) {
                  pushReasoning({
                    type: ev.type,
                    text: ev.text.trim(),
                    ts: ev.ts > 1e12 ? ev.ts : ev.ts * 1000,
                  });
                }

                // Rebuild messages from ALL events — stable IDs in
                // buildMessagesFromEvents prevent React from re-mounting
                // unchanged messages.
                setReasoningActive(hasIncompleteTurn(fresh.events));
                setMessagesRef.current(buildMessagesFromEvents(fresh.events));

                // Merge any new injections from the fresh fetch
                if (fresh.injections?.length) {
                  setInjections(fresh.injections);
                }

                // Turn completed → stop polling + refresh sidebar
                if (!hasIncompleteTurn(fresh.events)) {
                  if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                  setIsPolling(false);
                  setReasoningActive(false);
                  if (!unmountedRef.current) {
                    onMessageComplete();
                  }
                }
              } catch {
                // Network error during poll — keep trying until safety cap
              } finally {
                pollInFlight = false;
              }
            }, POLL_INTERVAL_MS);
          }
          return;
        }

        // Legacy fallback: old sessions without ui_events (text only)
        const copilotMessages: (TextMessage | ActionExecutionMessage)[] = sessionMsgs.flatMap((msg) => {
          const result: (TextMessage | ActionExecutionMessage)[] = [];
          result.push(new TextMessage({
            id: crypto.randomUUID(),
            role: msg.role === "user" ? MessageRole.User : MessageRole.Assistant,
            content: msg.content,
          }));
          return result;
        });
        setMessagesRef.current(copilotMessages);
      } finally {
        if (!cancelled) {
          setHistoryLoading(false);
          // Mark history as loaded — after this, scroll should be smooth for new messages
          // Use a short delay to let React render the messages first, then instant-scroll to bottom
          requestAnimationFrame(() => {
            bottomRef.current?.scrollIntoView({ behavior: "instant" });
            historyLoadedRef.current = true;
          });
        }
      }
    }

    loadHistory();
    return () => {
      cancelled = true;
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      setIsPolling(false);
    };
  }, [activeSessionId, userId]);

  // ── Live injection stream (out-of-band observations) ──────────────────────
  // Opens an SSE connection to /sessions/{id}/events/subscribe via our
  // Next.js proxy. Every `type: "injection"` frame appends to the state,
  // de-duped by id so a replayed-then-streamed event never doubles up.
  // Closes cleanly on session change / unmount.
  useEffect(() => {
    if (!activeSessionId) return;

    const dispose = subscribeToSessionEvents(
      activeSessionId,
      (ev) => {
        setInjections((prev) => {
          if (prev.some((p) => p.id === ev.id)) return prev;
          // Append + sort by time so out-of-order arrivals still render in
          // chronological order relative to existing injections.
          const next = [...prev, ev];
          next.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
          return next;
        });
      },
      { userId, onStatusChange: setLiveStatus }
    );

    return dispose;
  }, [activeSessionId, userId]);

  // Auto-scroll on new messages
  // Use "instant" for initial history load (avoids getting stuck mid-scroll on long conversations)
  // Use "smooth" for live messages during conversation
  useEffect(() => {
    if (!historyLoadedRef.current) return; // let the history load handler do the initial scroll
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, injections]);

  // Detect completion → refresh sidebar (defer so we can skip if unmounting when switching conversations)
  useEffect(() => {
    if (prevLoading.current && !isLoading) {
      setRoundTimes(prev => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        if (last.completedAt) return prev;
        return [...prev.slice(0, -1), { ...last, completedAt: new Date() }];
      });
      queueMicrotask(() => {
        if (!unmountedRef.current) {
          onMessageComplete();
        }
      });
    }
    prevLoading.current = isLoading;
  }, [isLoading, onMessageComplete, setRoundTimes]);

  const handleSend = useCallback(
    (query: string) => {
      // Stop any active poll — CopilotKit's live SSE stream takes over
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      setIsPolling(false);

      clearReasoning();
      setReasoningActive(true);
      if (isFirstMessage.current) {
        onFirstMessage(query.slice(0, 55) + (query.length > 55 ? "…" : ""));
        isFirstMessage.current = false;
      }
      setRoundTimes(prev => [...prev, { sentAt: new Date() }]);

      // Inject view context (application / managed service data) if available
      const context = getContextSummary();
      const enrichedContent = context
        ? `__SRE_VIEW_CTX_START__\n${context}\n__SRE_VIEW_CTX_END__\n\n${query}`
        : query;

      // sendMessage takes a plain AG-UI message object — no class instance needed
      const msgId = crypto.randomUUID();
      const msg = { 
        id: msgId, 
        role: "user", 
        content: enrichedContent,
        user_id: userId,
        user_name: userName || (userId && userId.includes("@") ? userId.split("@")[0] : userId)
      };
      sendMessage(msg as Parameters<typeof sendMessage>[0]);
    },
    [sendMessage, onFirstMessage, setRoundTimes, getContextSummary, userId, userName]
  );

  const fallbackUserName = userName || (userId && userId.includes("@") ? userId.split("@")[0] : userId);
  const turns = groupIntoTurns(messages).map((t, index, arr) => {
    // Only apply the fallback to newly sent messages in the current live session 
    // (the last message) so we don't retroactively mislabel historical conversations.
    const isLatestMessage = index === arr.length - 1 || index === arr.length - 2;
    if (t.type === "user" && !t.userName && isLatestMessage) {
      return { ...t, userName: fallbackUserName };
    }
    return t;
  });

  // Mark the last assistant turn as streaming while the model is generating
  // (either via live CopilotKit SSE or via our Redis poll after page refresh)
  if ((isLoading || isPolling) && turns.length > 0) {
    const last = turns[turns.length - 1];
    if (last.type === "assistant") {
      last.isStreaming = true;
    } else {
      // User message sent but no assistant turn yet — add a placeholder
      turns.push({ type: "assistant", id: "streaming-placeholder", segments: [], isStreaming: true });
    }
  } else if (isPolling && turns.length === 0) {
    // Mid-processing refresh: backend has intermediate events (thinking/progress)
    // but the user event hasn't been written to Redis yet. Show a streaming
    // placeholder so the user sees the agent is still working.
    turns.push({ type: "assistant", id: "streaming-placeholder", segments: [], isStreaming: true });
  }

  const isEmpty = turns.length === 0;

  // Find the last assistant turn to ensure we only show the retry scheduler once
  const lastAssistantTurnIndex = [...turns].reverse().findIndex(t => t.type === "assistant");
  const actualLastAssistantIndex = lastAssistantTurnIndex >= 0 ? turns.length - 1 - lastAssistantTurnIndex : -1;

  // Map each turn to its recorded timestamp (undefined for history-loaded turns)
  let _ui = 0, _ai = 0;
  const turnTimestamps = turns.map(t =>
    t.type === "user" ? roundTimes[_ui++]?.sentAt : roundTimes[_ai++]?.completedAt
  );

  // Build a merged chronological timeline of turns + injections so out-of-band
  // observations slot in at the correct spot in the conversation. Turns
  // without a timestamp (e.g. replayed historical turns) inherit the previous
  // turn's timestamp — this keeps injections from jumping to the top of the
  // chat when hydrating an old session.
  type TimelineItem =
    | { kind: "turn"; turn: Turn; turnIndex: number }
    | { kind: "injection"; event: InjectionEvent };

  const sortedInjections = [...injections].sort(
    (a, b) => a.timestamp.getTime() - b.timestamp.getTime()
  );
  const timeline: TimelineItem[] = [];
  let injIdx = 0;
  let lastKnownTurnMs = 0;
  for (let i = 0; i < turns.length; i++) {
    const ts = turnTimestamps[i];
    const tMs = ts ? ts.getTime() : lastKnownTurnMs;
    while (
      injIdx < sortedInjections.length &&
      sortedInjections[injIdx].timestamp.getTime() <= tMs
    ) {
      timeline.push({ kind: "injection", event: sortedInjections[injIdx] });
      injIdx++;
    }
    timeline.push({ kind: "turn", turn: turns[i], turnIndex: i });
    if (ts) lastKnownTurnMs = tMs;
  }
  while (injIdx < sortedInjections.length) {
    timeline.push({ kind: "injection", event: sortedInjections[injIdx] });
    injIdx++;
  }

  return (
    <>
      {/* Messages area */}
      <div className={`relative flex-1 overflow-y-auto px-4 md:px-6 py-6 ${isDark ? "bg-[#0d1117]" : "bg-gray-50"}`}>
        {/* Live SSE status badge — sticky top-right of the messages area so
            users always see whether out-of-band observations are flowing.
            Hidden while no session is active so the empty/welcome screen
            stays clean. */}
        {activeSessionId && (
          <div className="sticky top-0 z-10 flex justify-end pointer-events-none -mb-6 pr-1">
            <LiveStatusBadge status={liveStatus} isDark={isDark} />
          </div>
        )}
        {(agentsLoading || historyLoading) ? (
          <div className="flex flex-1 items-center justify-center min-h-[200px]">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 rounded-full border-2 border-[#0071CE] border-t-transparent animate-spin" />
              <p className="text-xs text-gray-500">Loading agents…</p>
            </div>
          </div>
        ) : isEmpty ? (
          <EmptyState agent={activeAgent} />
        ) : (
          <div className="w-full flex flex-col gap-4">
            {timeline.map((item) =>
              item.kind === "injection" ? (
                <InjectionCard key={`inj-${item.event.id}`} event={item.event} />
              ) : (
                <TurnRenderer
                  key={item.turn.id}
                  turn={item.turn}
                  _onSend={handleSend}
                  isDark={isDark}
                  timestamp={turnTimestamps[item.turnIndex]}
                  activeSessionId={activeSessionId}
                  isAlertSession={isAlertSession}
                  isLatestAssistant={item.turnIndex === actualLastAssistantIndex}
                  reasoningEntries={item.turnIndex === actualLastAssistantIndex ? reasoningEntries : []}
                  reasoningIsActive={item.turnIndex === actualLastAssistantIndex ? reasoningIsActive : false}
                />
              )
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className={`px-4 md:px-8 pt-1 pb-3 flex-shrink-0 ${isDark ? "bg-[#0d1117]" : "bg-gray-50"}`}>
        <div className="w-full">
          <ChatInput
            onSend={handleSend}
            onStop={stopGeneration}
            isLoading={isLoading}
            placeholder={activeAgent ? `Ask ${activeAgent.name}…` : "Select an agent above to start"}
            prefillValue={prefillValue}
            onPrefillConsumed={onPrefillConsumed}
            showSuggestions={isEmpty}
          />
        </div>
      </div>
    </>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function _timeAgo(date: Date): string {
  // Use date-fns for "20 minutes ago" format
  return formatDistanceToNow(date, { addSuffix: true });
}

/** Build the label shown above a user bubble: "Madhu · 30 min ago" */
function _buildUserLabel(userName: string | undefined, ts: Date | undefined): string {
  const time = ts ? _timeAgo(ts) : "";
  if (userName && time) return `${userName} (${time})`;
  if (userName) return userName;
  if (time)     return time;
  return "";
}

// ─── Live SSE status badge ───────────────────────────────────────────────────

/**
 * Tiny floating chip showing the state of the out-of-band SSE connection
 * (live observations from openclaw monitoring loops, alertmanager, etc.).
 *
 * The chip is intentionally subtle — it should disappear into the UI when
 * everything's healthy ("Live") and only attract attention when something
 * is wrong ("Reconnecting…" / "Offline"). We do NOT block the chat input
 * on this status; injection delivery is best-effort and the LLM
 * conversation is fully usable even when SSE is down.
 */
function LiveStatusBadge({
  status,
  isDark,
}: {
  status: SessionStreamStatus;
  isDark: boolean;
}) {
  const meta: { label: string; dot: string; chip: string; pulse: boolean } = (() => {
    switch (status) {
      case "live":
        return {
          label: "Live",
          dot: isDark ? "bg-emerald-400" : "bg-emerald-500",
          chip: isDark
            ? "bg-emerald-950/60 text-emerald-300 border-emerald-800/60"
            : "bg-emerald-50 text-emerald-700 border-emerald-200",
          pulse: true,
        };
      case "reconnecting":
        return {
          label: "Reconnecting…",
          dot: isDark ? "bg-amber-400" : "bg-amber-500",
          chip: isDark
            ? "bg-amber-950/60 text-amber-300 border-amber-800/60"
            : "bg-amber-50 text-amber-700 border-amber-200",
          pulse: true,
        };
      case "offline":
        return {
          label: "Offline",
          dot: isDark ? "bg-red-400" : "bg-red-500",
          chip: isDark
            ? "bg-red-950/60 text-red-300 border-red-800/60"
            : "bg-red-50 text-red-700 border-red-200",
          pulse: false,
        };
      case "connecting":
      default:
        return {
          label: "Connecting…",
          dot: isDark ? "bg-gray-400" : "bg-gray-500",
          chip: isDark
            ? "bg-gray-800/70 text-gray-300 border-gray-700/60"
            : "bg-gray-100 text-gray-600 border-gray-300",
          pulse: false,
        };
    }
  })();

  return (
    <span
      className={`pointer-events-auto inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10px] font-medium shadow-sm ${meta.chip}`}
      title="Live SSE feed for out-of-band observations (e.g. openclaw monitoring updates)"
      aria-live="polite"
    >
      <span className="relative flex h-1.5 w-1.5">
        {meta.pulse && (
          <span
            className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-60 ${meta.dot}`}
          />
        )}
        <span className={`relative inline-flex rounded-full h-1.5 w-1.5 ${meta.dot}`} />
      </span>
      {meta.label}
    </span>
  );
}

// ─── Code execution block ─────────────────────────────────────────────────────

function CodeExecutionBlock({ code, output, isStreaming, isDark }: {
  code: string;
  output: string;
  isStreaming: boolean;
  isDark: boolean;
}) {
  const [open, setOpen] = useState(false);
  const hasOutput = output && output.trim() && output !== "(no output)";
  const firstLine = code.split("\n")[0]?.trim().slice(0, 60) || "Python script";

  return (
    <div className={`rounded-lg border overflow-hidden w-full ${
      isDark ? "border-blue-900/40 bg-[#0d1117]" : "border-blue-200 bg-blue-50/30"
    }`}>
      {/* Header row — click to expand/collapse */}
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen(o => !o)}
      >
        <span className="text-base leading-none">🐍</span>
        {isStreaming && !hasOutput ? (
          <>
            <span className={`text-[11px] font-medium ${isDark ? "text-blue-300" : "text-blue-700"}`}>
              Executing Python script…
            </span>
            <span className="flex gap-0.5 ml-1">
              {[0,100,200].map(d => (
                <span key={d} className="w-1 h-1 rounded-full bg-blue-400 animate-bounce"
                  style={{ animationDelay: `${d}ms` }} />
              ))}
            </span>
          </>
        ) : (
          <>
            <span className={`text-[11px] font-semibold ${isDark ? "text-blue-300" : "text-blue-700"}`}>
              Python Script
            </span>
            <span className={`text-[10px] font-mono truncate flex-1 ${isDark ? "text-gray-500" : "text-gray-400"}`}>
              {firstLine}
            </span>
            {hasOutput && (
              <span className="text-[10px] text-green-500 flex-shrink-0">✓ done</span>
            )}
            <span className={`text-[10px] ml-1 ${isDark ? "text-gray-600" : "text-gray-400"}`}>
              {open ? "▲" : "▼"}
            </span>
          </>
        )}
      </button>

      {/* Expanded body */}
      {open && (
        <div className="border-t border-blue-900/30">
          {/* Code */}
          <div className={`border-b ${isDark ? "border-gray-800" : "border-gray-200"}`}>
            <div className={`px-3 py-1 text-[10px] font-medium ${isDark ? "text-blue-400 bg-blue-950/30" : "text-blue-600 bg-blue-50"}`}>
              Script
            </div>
            <pre className={`px-4 py-3 text-[11px] font-mono leading-relaxed overflow-x-auto whitespace-pre ${
              isDark ? "text-green-200" : "text-green-900"
            }`}>{code}</pre>
          </div>
          {/* Output */}
          {hasOutput && (
            <div>
              <div className={`px-3 py-1 text-[10px] font-medium ${isDark ? "text-gray-400 bg-gray-800/40" : "text-gray-500 bg-gray-100"}`}>
                Output
              </div>
              <pre className={`px-4 py-3 text-[11px] font-mono leading-relaxed overflow-x-auto whitespace-pre ${
                isDark ? "text-gray-100" : "text-gray-800"
              }`}>{output}</pre>
            </div>
          )}
          {!hasOutput && (
            <p className={`px-4 py-2 text-[11px] italic ${isDark ? "text-gray-600" : "text-gray-400"}`}>
              No output (add print() statements to see results)
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Turn renderer ─────────────────────────────────────────────────────────────

// ─── Tool call progress chip ──────────────────────────────────────────────────

function ToolCallChip({ name, args, isStreaming, isDark }: {
  name: string;
  args: Record<string, unknown>;
  isStreaming: boolean;
  isDark: boolean;
}) {
  const label   = toolLabel(name);
  const preview = toolArgPreview(args);
  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-mono w-fit max-w-full ${
      isDark ? "bg-[#0d1117] border border-[#30363d] text-gray-300" : "bg-gray-50 border border-gray-200 text-gray-600"
    }`}>
      {isStreaming ? (
        <span className="flex gap-0.5">
          {[0,80,160].map(d => (
            <span key={d} className="w-1.5 h-1.5 rounded-full bg-[#0071CE] animate-bounce opacity-80"
              style={{ animationDelay: `${d}ms` }} />
          ))}
        </span>
      ) : (
        <span className="text-green-500 text-sm leading-none">✓</span>
      )}
      <span className={`font-semibold ${isDark ? "text-blue-400" : "text-[#0071CE]"}`}>{label}</span>
      {preview && (
        <span className={`truncate max-w-[420px] ${isDark ? "text-gray-500" : "text-gray-400"}`}>{preview}</span>
      )}
    </div>
  );
}

// ─── Turn renderer ────────────────────────────────────────────────────────────

export function TurnRenderer({ 
  turn, _onSend, isDark, timestamp, activeSessionId, isAlertSession, isLatestAssistant, reasoningEntries, reasoningIsActive
}: { 
  turn: Turn; 
  _onSend?: (query: string) => void; 
  isDark: boolean; 
  timestamp?: Date; 
  activeSessionId?: string; 
  isAlertSession?: boolean;
  isLatestAssistant?: boolean;
  reasoningEntries?: Array<{ type: "thinking" | "reasoning"; text: string; ts: number }>;
  reasoningIsActive?: boolean;
}) {
  if (turn.type === "user") {
    // Prefer timestamp stored in the turn (from replay events) over live roundTime
    const effectiveTs = turn.timestamp ?? timestamp;
    const label = _buildUserLabel(turn.userName, effectiveTs);
    return (
      <div>
        {label && (
          <p className={`text-[10px] font-medium mb-0.5 text-right pr-1 select-none ${isDark ? "text-gray-500" : "text-gray-400"}`}>
            {label}
          </p>
        )}
        <MessageItem
          message={{ id: turn.id, role: "user", content: turn.content, timestamp: effectiveTs, user_id: turn.userId, user_name: turn.userName, isStreaming: false }}
        />
      </div>
    );
  }

  // Assistant turn — avatar + bubble wrapping all segments
  const assistantText = turn.segments
    .filter((s): s is { kind: "text"; content: string; id: string } => s.kind === "text")
    .map((s) => s.content)
    .join("\n\n");

  // Detect code execution state from live segments (CodeExecutionBlock handles its own state)
  const isExecutingCode = turn.isStreaming &&
    turn.segments.some(s => s.kind === "code" && !(s as { output?: string }).output?.trim());

  return (
    <div className="group/msg flex gap-3 items-start">
      {/* Bot avatar */}
      <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-gradient-to-br from-[#0071CE] to-[#004fa3] flex items-center justify-center text-white shadow-sm mt-1">
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17H3a2 2 0 01-2-2V5a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2h-2" />
        </svg>
      </div>

      {/* Response bubble */}
      <div className={`flex-1 min-w-0 mr-11 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm flex flex-col gap-4 ${
        isDark ? "bg-[#1c2332]" : "bg-white border border-gray-100"
      }`}>
        {/* Show reasoning-store entries only for the latest assistant turn during
        {/* Show reasoning-store entries only for the latest assistant turn during
            live streaming AND only when no inline reasoning segments exist yet.
            Once emit_reasoning tool-call events create inline segments, those
            take over — avoids duplicate reasoning cards on session replay. */}
        {isLatestAssistant
          && reasoningEntries
          && reasoningEntries.length > 0
          && !turn.segments.some(s => s.kind === "reasoning") ? (
          <ReasoningStream
            entries={reasoningEntries}
            isProcessing={Boolean(reasoningIsActive)}
            isDark={isDark}
          />
        ) : null}

        {turn.segments.map((seg, segIdx) =>
          seg.kind === "reasoning" ? (
            <ReasoningStream
              key={seg.id}
              entries={seg.entries}
              isProcessing={
                // A reasoning block is still "active" only if the turn is streaming
                // AND nothing comes after it yet. Once a tool call or another segment
                // follows, this reasoning block is complete.
                Boolean(turn.isStreaming) && segIdx === turn.segments.length - 1
              }
              isDark={isDark}
            />
          ) : seg.kind === "a2ui" ? (
            <A2UIRenderer key={seg.id} data={seg.data} />
          ) : seg.kind === "code" ? (
            <CodeExecutionBlock
              key={seg.id}
              code={seg.code}
              output={seg.output}
              isStreaming={turn.isStreaming}
              isDark={isDark}
            />
          ) : seg.kind === "tool" ? (
            <ToolCallChip
              key={seg.id}
              name={seg.name}
              args={seg.args}
              isStreaming={turn.isStreaming}
              isDark={isDark}
            />
          ) : seg.kind === "text" ? (
            <MarkdownRenderer key={seg.id} content={seg.content} isStreaming={turn.isStreaming} />
          ) : null
        )}

        {/* Streaming indicator — shown only while the turn is still generating.
            Priority: code execution > bouncing dots.
            Hidden when: reasoning panel is active OR a tool chip with its own spinner is visible. */}
        {turn.isStreaming && (
          isExecutingCode ? (
            /* Code is written, waiting for Python to execute */
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-950/30 border border-blue-900/40 w-fit">
              <span className="text-sm">🐍</span>
              <span className="text-[11px] text-blue-300 font-medium">Executing Python script</span>
              <span className="flex gap-0.5 ml-1">
                {[0, 100, 200].map(d => (
                  <span key={d} className="w-1 h-1 rounded-full bg-blue-400 animate-bounce"
                    style={{ animationDelay: `${d}ms` }} />
                ))}
              </span>
            </div>
          ) : (
            /* Normal streaming dots */
            <div className="flex gap-1 py-1">
              {[0, 150, 300].map((delay) => (
                <span
                  key={delay}
                  className="w-2 h-2 rounded-full bg-[#0071CE] animate-bounce opacity-70"
                  style={{ animationDelay: `${delay}ms` }}
                />
              ))}
            </div>
          )
        )}

        {/* Timestamp + Copy */}
        <div className="flex items-center gap-1.5 mt-1">
          {timestamp && (
            <p className={`text-[10px] select-none ${isDark ? "text-gray-500" : "text-gray-300"}`}>
              {timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </p>
          )}
          {assistantText && !turn.isStreaming && (
            <CopyButton text={assistantText} />
          )}
        </div>

        {/* Schedule Retry for Alerts */}
        {!turn.isStreaming && turn.type === "assistant" && activeSessionId && isLatestAssistant && (isAlertSession || extractAlertId(assistantText)) && (
          <AlertRetryScheduler 
            initialAlertId={extractAlertId(assistantText)} 
            conversationId={activeSessionId} 
          />
        )}
      </div>
    </div>
  );
}

// ─── Main ChatInterface ───────────────────────────────────────────────────────

export function ChatInterface({ initialSessionId, initialAgents }: { initialSessionId?: string; initialAgents?: AgentConfig[] }) {
  const { user, loading: authLoading, isLoggingOut, login } = useAuth();
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const userId = user?.loginId ?? "";

  const [activeAgent, setActiveAgent] = useState<AgentConfig | null>(null);
  const [agentsLoading, setAgentsLoading] = useState(() => !initialAgents?.length);
  const [showHowTo, setShowHowTo] = useState(false);
  const [prefillValue, setPrefillValue] = useState("");

  // Don't fetch conversations until auth has resolved — prevents empty userId
  // firing before we know the real userId (race condition).
  const {
    conversations,
    activeSessionId,
    loading: convsLoading,
    isAlertSession,
    refresh: refreshConversations,
    createNewConversation,
    selectConversation,
    updateConversationTitle,
  } = useConversations(userId, !authLoading, initialSessionId);

  const handleFirstMessage = useCallback(
    (title: string) => {
      updateConversationTitle(activeSessionId, title);
      setTimeout(() => refreshConversations(), 1500);
    },
    [activeSessionId, updateConversationTitle, refreshConversations]
  );

  const handleMessageComplete = useCallback(() => {
    refreshConversations();
  }, [refreshConversations]);

  // Redirect to PingFed login if auth has resolved but there is no session.
  // Handles expired tokens and cleared cookies without a page navigation.
  // Skip if logout is in progress — logout handles its own redirect.
  useEffect(() => {
    if (!authLoading && !user && !isLoggingOut) {
      login();
    }
  }, [authLoading, user, isLoggingOut, login]);

  // Memoize so the object reference only changes when agent/session change —
  // a new object on every render causes CopilotKit to reinitialise its connection.
  // Must live before early returns to satisfy Rules of Hooks.
  const runtimeHeaders = useMemo(() => ({
    "x-agent-id":          activeAgent?.id ?? "",
    "x-session-id":        activeSessionId ?? "",
    "x-user-timezone":     Intl.DateTimeFormat().resolvedOptions().timeZone,
    "x-current-epoch-ms":  String(Date.now()),
  }), [activeAgent?.id, activeSessionId]);

  // Show a minimal full-page spinner while the PingFed session is being verified.
  if (authLoading) {
    return (
      <div className={`flex h-screen items-center justify-center ${isDark ? "bg-[#161b22]" : "bg-white"}`}>
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 rounded-full border-2 border-[#0071CE] border-t-transparent animate-spin" />
          <p className={`text-xs ${isDark ? "text-gray-400" : "text-gray-500"}`}>Verifying session…</p>
        </div>
      </div>
    );
  }

  // Still redirecting (useEffect is async) — keep showing spinner
  if (!user) {
    return (
      <div className={`flex h-screen items-center justify-center ${isDark ? "bg-[#161b22]" : "bg-white"}`}>
        <div className="w-8 h-8 rounded-full border-2 border-[#0071CE] border-t-transparent animate-spin" />
      </div>
    );
  }

  // Keep runtimeUrl as a clean base path so ProxiedCopilotRuntimeAgent can
  // correctly construct /agent/:id/stop/:threadId for the Stop button.
  // agentId + sessionId travel as custom headers instead of URL query params.
  const runtimeUrl = "/api/copilotkit";

  return (
    <div className={`flex h-screen overflow-hidden ${isDark ? "bg-[#161b22]" : "bg-white"}`}>
      {/* Left Sidebar */}
      <Sidebar
        conversations={conversations}
        activeSessionId={activeSessionId}
        userId={userId}
        loading={convsLoading}
        onNewChat={createNewConversation}
        onSelectConversation={selectConversation}
        onHowToClick={() => setShowHowTo(true)}
      />

      {/* Main chat area */}
      <div className={`relative flex flex-col flex-1 min-w-0 ${isDark ? "bg-[#161b22]" : "bg-white"}`}>
        {/* Top bar */}
        <header className={`flex items-center justify-end px-5 h-[57px] flex-shrink-0 ${
          isDark ? "bg-[#161b22]" : "bg-white"
        }`}>
          <div className="flex items-center gap-2.5">
            <AgentSelector
              selectedId={activeAgent?.id ?? ""}
              onChange={setActiveAgent}
              onLoadingChange={setAgentsLoading}
              initialAgents={initialAgents}
            />
            <StatusBadge />
          </div>
        </header>

        {/*
          CopilotKit provider — keyed by sessionId so it re-mounts (clearing state)
          whenever the user switches conversations.
        */}
        <div className={`flex flex-col flex-1 overflow-hidden rounded-tl-2xl ${isDark ? "bg-[#0d1117]" : "bg-gray-50"}`}>
          <CopilotKit
            key={activeSessionId ?? "new"}
            runtimeUrl={runtimeUrl}
            headers={runtimeHeaders}
            showDevConsole={false}
            enableInspector={false}
          >
            <CopilotChatArea
              activeAgent={activeAgent}
              activeSessionId={activeSessionId}
              userId={userId}
                userName={user?.name}
              agentsLoading={agentsLoading}
              onFirstMessage={handleFirstMessage}
              onMessageComplete={handleMessageComplete}
              prefillValue={prefillValue}
              onPrefillConsumed={() => setPrefillValue("")}
              isAlertSession={isAlertSession}
            />
          </CopilotKit>
        </div>

        {/* How To slide-over panel */}
        {showHowTo && (
          <HowToPanel
            onSelect={(faq) => setPrefillValue(faq)}
            onClose={() => setShowHowTo(false)}
          />
        )}
      </div>
    </div>
  );
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge() {
  const { theme } = useTheme();
  const isDark = theme === "dark";

  return (
    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full ${
      isDark
        ? "bg-green-900/30 border border-green-700/40"
        : "bg-green-50 border border-green-200"
    }`}>
      <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${isDark ? "bg-green-400" : "bg-green-500"}`} />
      <span className={`text-xs font-medium ${isDark ? "text-green-400" : "text-green-700"}`}>Connected</span>
    </div>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────

function EmptyState({ agent }: { agent: AgentConfig | null }) {
  const { theme } = useTheme();
  const isDark = theme === "dark";

  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center px-4">
      <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[#0071CE] to-[#005baa] flex items-center justify-center mb-5 text-3xl shadow-md">
        {agent?.emoji ?? "🛡️"}
      </div>
      <h2 className={`text-xl font-semibold mb-2 ${isDark ? "text-gray-100" : "text-gray-800"}`}>
        {agent?.name ?? "SRE Super Agent"}
      </h2>
      <p className={`max-w-md text-sm leading-relaxed mb-8 ${isDark ? "text-gray-400" : "text-gray-500"}`}>
        {agent?.description ??
          "Multi-agent SRE assistant — ask about health checks, dependencies, edge network debugging, and exception RCA."}
      </p>
      <p className={`text-[10px] font-semibold uppercase tracking-wider mb-3 ${isDark ? "text-gray-500" : "text-gray-400"}`}>Connected Agents</p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 w-full max-w-3xl">
        {CAPABILITY_CARDS.map((card) => (
          <div key={card.title} className={`rounded-xl p-4 text-left shadow-sm hover:shadow-md transition-all ${
            isDark
              ? "bg-[#1c2332] hover:brightness-110"
              : "bg-white border border-gray-100 hover:border-[#0071CE]/20"
          }`}>
            <div className={`w-9 h-9 rounded-lg flex items-center justify-center text-lg mb-2.5 ${isDark ? "bg-[#0d1117]" : "bg-gray-100"}`}>{card.emoji}</div>
            <h3 className={`text-sm font-semibold mb-1 ${isDark ? "text-gray-200" : "text-gray-700"}`}>{card.title}</h3>
            <p className={`text-xs leading-relaxed ${isDark ? "text-gray-400" : "text-gray-500"}`}>{card.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

const CAPABILITY_CARDS = [
  { emoji: "🏥", title: "Health Agent", description: "Namespace health checks, pod status, deployment rollouts, and latency monitoring." },
  { emoji: "🔗", title: "Dependency Agent", description: "Upstream and downstream service dependency mapping across namespaces." },
  { emoji: "🌐", title: "Edge Network Agent", description: "Akamai, Torbit, and F5 analysis — routing, caching, and CDN debugging." },
  { emoji: "🔴", title: "Exception RCA Agent", description: "Root cause analysis for exceptions, stack traces, and error patterns." },
];

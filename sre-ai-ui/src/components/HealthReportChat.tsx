"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { CopilotKit, useCopilotChatInternal } from "@copilotkit/react-core";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { useViewContext } from "@/contexts/ViewContext";
import { groupIntoTurns } from "@/lib/chat-helpers";
import { TurnRenderer } from "./ChatInterface";
import { ChatInput } from "./ChatInput";
import { AgentSelector } from "./AgentSelector";
import { MessageCircle, Sparkles } from "lucide-react";
import { v4 as uuidv4 } from "uuid";
import type { AgentConfig } from "@/types";

// ─── Suggested questions for health context ────────────────────────────────

const HEALTH_SUGGESTIONS = [
  "What issues should I focus on first?",
  "Why is this cluster degraded?",
  "Are there any latency anomalies?",
  "Summarize the health of all clusters",
];

// ─── Inner chat area (needs CopilotKit context) ────────────────────────────

function HealthChatArea({
  activeAgent,
  appName,
  autoSummarize = false,
}: {
  activeAgent: AgentConfig | null;
  appName: string;
  autoSummarize?: boolean;
}) {
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const { getContextSummary } = useViewContext();

  const { messages, sendMessage, stopGeneration, isLoading } =
    useCopilotChatInternal();
  const bottomRef = useRef<HTMLDivElement>(null);
  const hasRenderedRef = useRef(false);
  const autoSummarizeFired = useRef(false);

  // Auto-scroll on new messages
  useEffect(() => {
    if (!hasRenderedRef.current && messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: "instant" });
      hasRenderedRef.current = true;
    } else if (hasRenderedRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleSend = useCallback(
    (query: string) => {
      const context = getContextSummary();
      const enrichedContent = context
        ? `__SRE_VIEW_CTX_START__\n${context}\n__SRE_VIEW_CTX_END__\n\n${query}`
        : query;

      sendMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: enrichedContent,
      } as Parameters<typeof sendMessage>[0]);
    },
    [sendMessage, getContextSummary]
  );

  // Auto-fire a summary request when the chat panel opens
  useEffect(() => {
    if (autoSummarize && !autoSummarizeFired.current && !isLoading && messages.length === 0) {
      autoSummarizeFired.current = true;
      // Small delay to let CopilotKit fully initialize
      const timer = setTimeout(() => {
        handleSend("Using ONLY the health report data provided in the context above (between --- LIVE HEALTH REPORT DATA --- markers), summarize the current health status. Do NOT call any tools or fetch new data. Highlight any degraded checks, unhealthy clusters, or anomalies. Be concise and use bullet points.");
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [autoSummarize, isLoading, messages.length, handleSend]);

  // Group messages into turns
  const turns = groupIntoTurns(messages);

  // Mark last assistant turn as streaming
  if (isLoading && turns.length > 0) {
    const last = turns[turns.length - 1];
    if (last.type === "assistant") {
      last.isStreaming = true;
    } else {
      turns.push({
        type: "assistant",
        id: "streaming-placeholder",
        segments: [],
        isStreaming: true,
      });
    }
  }

  const isEmpty = turns.length === 0;

  return (
    <div className="flex flex-col h-full">
      {/* Context badge */}
      <div
        className={`px-4 py-2 text-xs font-medium border-b flex items-center gap-2 flex-shrink-0 ${
          isDark
            ? "bg-emerald-950/30 border-emerald-900/40 text-emerald-300"
            : "bg-emerald-50 border-emerald-100 text-emerald-700"
        }`}
      >
        <Sparkles className="w-3.5 h-3.5" />
        Health Report Context: {appName}
      </div>

      {/* Messages */}
      <div
        className={`flex-1 overflow-y-auto px-4 py-4 ${
          isDark ? "bg-[#0d1117]" : "bg-gray-50"
        }`}
      >
        {isEmpty ? (
          <div
            className={`text-center py-6 ${
              isDark ? "text-gray-500" : "text-gray-400"
            }`}
          >
            <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 flex items-center justify-center">
              <MessageCircle
                className={`w-6 h-6 ${
                  isDark ? "text-emerald-400" : "text-emerald-500"
                }`}
              />
            </div>
            <p className="text-sm font-medium mb-1">
              Ask about this health report
            </p>
            <p className="text-xs opacity-70 mb-4">
              Full health data is included as context
            </p>

            {/* Suggestion chips */}
            <div className="flex flex-wrap gap-2 justify-center max-w-sm mx-auto">
              {HEALTH_SUGGESTIONS.map((q) => (
                <button
                  key={q}
                  onClick={() => handleSend(q)}
                  className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                    isDark
                      ? "border-[#30363d] text-gray-300 hover:bg-[#21262d] hover:border-emerald-700"
                      : "border-gray-200 text-gray-600 hover:bg-emerald-50 hover:border-emerald-300"
                  }`}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="w-full flex flex-col gap-4">
            {turns.map((turn) => (
              <TurnRenderer
                key={turn.id}
                turn={turn}
                _onSend={handleSend}
                isDark={isDark}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input */}
      <div
        className={`border-t px-4 py-3 flex-shrink-0 ${
          isDark
            ? "bg-[#161b22] border-[#30363d]"
            : "bg-white border-gray-200"
        }`}
      >
        <ChatInput
          onSend={handleSend}
          onStop={stopGeneration}
          isLoading={isLoading}
          placeholder="Ask about this health report…"
          showSuggestions={false}
        />
      </div>
    </div>
  );
}

// ─── Main HealthReportChat component ─────────────────────────────────────────

interface HealthReportChatProps {
  appName: string;
  autoSummarize?: boolean;
}

export function HealthReportChat({ appName, autoSummarize = false }: HealthReportChatProps) {
  const { user } = useAuth();
  const { theme } = useTheme();
  const isDark = theme === "dark";

  const [activeAgent, setActiveAgent] = useState<AgentConfig | null>(null);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [sessionId] = useState(() => uuidv4());

  const runtimeUrl = "/api/copilotkit";
  const runtimeHeaders = useMemo(
    () => ({
      "x-agent-id":         activeAgent?.id ?? "",
      "x-session-id":       sessionId,
      // Browser IANA timezone — lets the super agent convert "10 AM" → correct UTC epoch ms
      "x-user-timezone":    Intl.DateTimeFormat().resolvedOptions().timeZone,
      // Current epoch ms — anchors relative day expressions ("2AM to 10AM" = today)
      "x-current-epoch-ms": String(Date.now()),
    }),
    [activeAgent?.id, sessionId]
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div
        className={`flex items-center justify-between px-4 py-2.5 border-b flex-shrink-0 ${
          isDark
            ? "bg-[#161b22] border-[#30363d]"
            : "bg-white border-gray-200"
        }`}
      >
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
            <MessageCircle className="w-3.5 h-3.5 text-white" />
          </div>
          <span
            className={`text-sm font-semibold ${
              isDark ? "text-gray-100" : "text-gray-800"
            }`}
          >
            Health Assistant
          </span>
        </div>
        <AgentSelector
          selectedId={activeAgent?.id ?? ""}
          onChange={setActiveAgent}
          onLoadingChange={setAgentsLoading}
        />
      </div>

      {/* Chat area with CopilotKit provider */}
      <div className="flex-1 overflow-hidden">
        <CopilotKit
          key={sessionId}
          runtimeUrl={runtimeUrl}
          headers={runtimeHeaders}
          showDevConsole={false}
          enableInspector={false}
        >
          <HealthChatArea activeAgent={activeAgent} appName={appName} autoSummarize={autoSummarize} />
        </CopilotKit>
      </div>
    </div>
  );
}

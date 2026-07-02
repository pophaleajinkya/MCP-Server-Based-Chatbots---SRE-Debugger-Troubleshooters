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
import { X, Minimize2, Maximize2, MessageCircle, ChevronLeft, GripVertical } from "lucide-react";
import { v4 as uuidv4 } from "uuid";
import type { AgentConfig } from "@/types";

// ─── Inner chat area (needs CopilotKit context) ────────────────────────────

function SlideOverChatArea({ activeAgent }: { activeAgent: AgentConfig | null; agentsLoading?: boolean }) {
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const { getContextSummary, selectedApplication, selectedManagedService, activeView, healthReportData } = useViewContext();

  const { messages, sendMessage, stopGeneration, isLoading } = useCopilotChatInternal();
  const bottomRef = useRef<HTMLDivElement>(null);
  const hasRenderedRef = useRef(false);

  // Auto-scroll on new messages — instant for first render, smooth after
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

  // Build context badge text
  const hasHealthData = healthReportData != null;
  const contextBadge = hasHealthData
    ? `✨ Health Report: ${healthReportData.app_filter || selectedApplication?.appName || "app"}`
    : selectedApplication
      ? `📎 ${selectedApplication.name} (${selectedApplication.tier || "N/A"}, ${selectedApplication.tenant || "N/A"})`
      : selectedManagedService
        ? `📎 ${selectedManagedService.name} (${selectedManagedService.serviceType})`
        : activeView === "applications"
          ? "📊 Applications data"
          : activeView === "managed-services"
            ? "📊 Managed Services data"
            : null;

  // Suggested queries based on context
  const suggestedQueries = hasHealthData
    ? [
        "What issues should I focus on first?",
        "Why is this cluster degraded?",
        "Are there any latency anomalies?",
        "Summarize the health of all clusters",
      ]
    : selectedApplication
      ? [
          `Is ${selectedApplication.appName || selectedApplication.name} healthy?`,
          "Show dependencies for this app",
          "What team owns this application?",
        ]
      : null;

  // Use the same groupIntoTurns + TurnRenderer as the main ChatInterface
  const turns = groupIntoTurns(messages);

  // Mark the last assistant turn as streaming while the model is generating
  if (isLoading && turns.length > 0) {
    const last = turns[turns.length - 1];
    if (last.type === "assistant") {
      last.isStreaming = true;
    } else {
      turns.push({ type: "assistant", id: "streaming-placeholder", segments: [], isStreaming: true });
    }
  }

  const isEmpty = turns.length === 0;

  return (
    <div className="flex flex-col h-full">
      {/* Context badge */}
      {contextBadge && (
        <div className={`px-4 py-2 text-xs font-medium border-b flex items-center gap-2 flex-shrink-0 ${
          isDark
            ? "bg-blue-950/30 border-blue-900/40 text-blue-300"
            : "bg-blue-50 border-blue-100 text-blue-700"
        }`}>
          {contextBadge}
        </div>
      )}

      {/* Messages — same rendering as main ChatInterface */}
      <div className={`flex-1 overflow-y-auto px-4 py-4 ${isDark ? "bg-[#0d1117]" : "bg-gray-50"}`}>
        {isEmpty ? (
          <div className={`text-center py-8 ${isDark ? "text-gray-500" : "text-gray-400"}`}>
            <div className={`w-12 h-12 mx-auto mb-3 rounded-xl flex items-center justify-center ${
              hasHealthData
                ? "bg-gradient-to-br from-green-500/20 to-emerald-500/20"
                : "bg-gradient-to-br from-[#0071CE]/20 to-[#004fa3]/20"
            }`}>
              <MessageCircle className={`w-6 h-6 ${
                hasHealthData
                  ? isDark ? "text-green-400" : "text-green-500"
                  : isDark ? "text-blue-400" : "text-blue-500"
              }`} />
            </div>
            <p className="text-sm font-medium">
              {hasHealthData ? "Ask about this health report" : "Ask about the data you're viewing"}
            </p>
            {contextBadge && (
              <p className="text-xs mt-1.5 opacity-70">
                {hasHealthData ? "Full health data is included as context" : "Context will be automatically included"}
              </p>
            )}
            {suggestedQueries && (
              <div className="mt-4 flex flex-col gap-2 items-center">
                {suggestedQueries.map((q) => (
                  <button
                    key={q}
                    onClick={() => handleSend(q)}
                    className={`px-4 py-2 rounded-full text-xs border transition-colors ${
                      isDark
                        ? "border-[#30363d] text-gray-300 hover:border-blue-500 hover:text-blue-300 hover:bg-blue-900/20"
                        : "border-gray-200 text-gray-600 hover:border-[#0071CE] hover:text-[#0071CE] hover:bg-blue-50/60"
                    }`}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="w-full flex flex-col gap-4">
            {turns.map((turn) => (
              <TurnRenderer key={turn.id} turn={turn} _onSend={handleSend} isDark={isDark} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input */}
      <div className={`border-t px-4 py-3 flex-shrink-0 ${
        isDark ? "bg-[#161b22] border-[#30363d]" : "bg-white border-gray-200"
      }`}>
        <ChatInput
          onSend={handleSend}
          onStop={stopGeneration}
          isLoading={isLoading}
          placeholder={hasHealthData ? "Ask about this health report…" : activeAgent ? `Ask ${activeAgent.name}…` : "Ask about the data you're viewing…"}
          showSuggestions={false}
        />
      </div>
    </div>
  );
}

// ─── Main SlideOver component ──────────────────────────────────────────────

export type ChatSlideOverMode = "closed" | "collapsed" | "open";

interface ChatSlideOverProps {
  mode: ChatSlideOverMode;
  onModeChange: (mode: ChatSlideOverMode) => void;
}

export function ChatSlideOver({ mode, onModeChange }: ChatSlideOverProps) {
  const { user } = useAuth();
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const { selectedApplication, selectedManagedService } = useViewContext();

  const [activeAgent, setActiveAgent] = useState<AgentConfig | null>(null);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [sessionId] = useState(() => uuidv4());

  // ── Drag-to-resize state ──
  const MIN_WIDTH = 340;
  const MAX_WIDTH = 900;
  const DEFAULT_WIDTH = 420;
  const EXPANDED_WIDTH = 650;
  const [panelWidth, setPanelWidth] = useState(DEFAULT_WIDTH);
  const [isResizing, setIsResizing] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(DEFAULT_WIDTH);

  const isOpen = mode === "open";
  const isCollapsed = mode === "collapsed";

  // Drag handlers
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
    dragStartX.current = e.clientX;
    dragStartWidth.current = panelWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [panelWidth]);

  useEffect(() => {
    const handleDragMove = (e: MouseEvent) => {
      if (!isResizing) return;
      const delta = dragStartX.current - e.clientX; // dragging left = wider
      const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, dragStartWidth.current + delta));
      setPanelWidth(newWidth);
    };

    const handleDragEnd = () => {
      if (!isResizing) return;
      setIsResizing(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    if (isResizing) {
      window.addEventListener("mousemove", handleDragMove);
      window.addEventListener("mouseup", handleDragEnd);
      return () => {
        window.removeEventListener("mousemove", handleDragMove);
        window.removeEventListener("mouseup", handleDragEnd);
      };
    }
  }, [isResizing]);

  // Expand/shrink presets
  const isExpanded = panelWidth >= EXPANDED_WIDTH;
  const toggleExpand = useCallback(() => {
    setPanelWidth(isExpanded ? DEFAULT_WIDTH : EXPANDED_WIDTH);
  }, [isExpanded]);

  // Prevent body scroll when fully open — restore on unmount
  useEffect(() => {
    document.body.style.overflow = isOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [isOpen]);

  const runtimeUrl = "/api/copilotkit";
  const runtimeHeaders = useMemo(() => ({
    "x-agent-id":         activeAgent?.id ?? "",
    "x-session-id":       sessionId,
    // Browser IANA timezone — lets the super agent convert "10 AM" → correct UTC epoch ms
    "x-user-timezone":    Intl.DateTimeFormat().resolvedOptions().timeZone,
    // Current epoch ms — anchors relative day expressions ("2AM to 10AM" = today)
    "x-current-epoch-ms": String(Date.now()),
  }), [activeAgent?.id, sessionId]);

  // Context label for collapsed strip
  const contextLabel = selectedApplication
    ? selectedApplication.name
    : selectedManagedService
      ? selectedManagedService.name
      : "Ask AI";

  return (
    <>
      {/* Backdrop — only when fully open */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/20 transition-opacity duration-300"
          onClick={() => onModeChange("collapsed")}
        />
      )}

      {/* Collapsed strip — thin vertical bar on the right edge */}
      {isCollapsed && (
        <div
          onClick={() => onModeChange("open")}
          className={`fixed top-1/2 -translate-y-1/2 right-0 z-50 cursor-pointer group transition-all ${
            isDark ? "text-gray-300" : "text-gray-600"
          }`}
        >
          <div className={`flex flex-col items-center gap-2 px-1.5 py-4 rounded-l-xl border border-r-0 shadow-lg transition-all group-hover:px-2.5 ${
            isDark
              ? "bg-[#161b22] border-[#30363d] group-hover:bg-[#1c2332]"
              : "bg-white border-gray-200 group-hover:bg-gray-50"
          }`}>
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#0071CE] to-[#004fa3] flex items-center justify-center flex-shrink-0">
              <MessageCircle className="w-4 h-4 text-white" />
            </div>
            <ChevronLeft className={`w-3.5 h-3.5 opacity-50 group-hover:opacity-100 transition-opacity ${isDark ? "text-gray-500" : "text-gray-400"}`} />
            <span className={`text-[10px] font-medium writing-mode-vertical max-h-[120px] truncate ${
              isDark ? "text-gray-400 group-hover:text-gray-200" : "text-gray-500 group-hover:text-gray-700"
            }`} style={{ writingMode: "vertical-rl", textOrientation: "mixed" }}>
              {contextLabel}
            </span>
            {(selectedApplication || selectedManagedService) && (
              <span className="w-2.5 h-2.5 bg-green-500 rounded-full border-2 border-white dark:border-[#161b22] flex-shrink-0" />
            )}
          </div>
        </div>
      )}

      {/* Full slide-over panel */}
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: panelWidth }}
        className={`fixed top-0 right-0 z-50 h-full flex flex-col shadow-2xl ${
          isResizing ? "" : "transition-all duration-300 ease-out"
        } ${
          isOpen ? "translate-x-0" : "translate-x-full"
        } ${
          isDark ? "bg-[#161b22] border-l border-[#30363d]" : "bg-white border-l border-gray-200"
        }`}
      >
        {/* Drag handle — left edge */}
        <div
          onMouseDown={handleDragStart}
          className={`absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize z-10 group ${
            isDark ? "hover:bg-blue-500/30" : "hover:bg-blue-400/30"
          } transition-colors`}
        >
          {/* Visual grip indicator — centered vertically */}
          <div className="absolute top-1/2 -translate-y-1/2 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
            <GripVertical className={`w-3 h-4 ${isDark ? "text-blue-400" : "text-blue-500"}`} />
          </div>
        </div>
        {/* Header */}
        <div className={`flex items-center justify-between px-4 py-3 border-b flex-shrink-0 ${
          isDark ? "bg-[#161b22] border-[#30363d]" : "bg-white border-gray-200"
        }`}>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#0071CE] to-[#004fa3] flex items-center justify-center">
              <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
            </div>
            <span className={`text-sm font-semibold ${isDark ? "text-gray-100" : "text-gray-800"}`}>
              Ask AI
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <AgentSelector
              selectedId={activeAgent?.id ?? ""}
              onChange={setActiveAgent}
              onLoadingChange={setAgentsLoading}
            />
            <button
              onClick={toggleExpand}
              className={`p-1.5 rounded-lg transition-colors ${
                isDark ? "hover:bg-[#21262d] text-gray-400" : "hover:bg-gray-100 text-gray-500"
              }`}
              title={isExpanded ? "Shrink panel" : "Expand panel"}
            >
              {isExpanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onModeChange("collapsed"); }}
              className={`p-1.5 rounded-lg transition-colors ${
                isDark ? "hover:bg-[#21262d] text-gray-400" : "hover:bg-gray-100 text-gray-500"
              }`}
              title="Collapse to sidebar"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onModeChange("closed"); }}
              className={`p-1.5 rounded-lg transition-colors ${
                isDark ? "hover:bg-[#21262d] text-gray-400" : "hover:bg-gray-100 text-gray-500"
              }`}
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
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
            <SlideOverChatArea
              activeAgent={activeAgent}
              agentsLoading={agentsLoading}
            />
          </CopilotKit>
        </div>
      </div>
    </>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ReasoningEntry } from "@/lib/reasoning-store";

// Re-export for any consumers importing from here
export type { ReasoningEntry };

interface ReasoningStreamProps {
  /** Array of reasoning/thinking events from the reasoning store */
  entries: ReasoningEntry[];
  /** Whether the agent is still processing (no "complete" yet) */
  isProcessing: boolean;
  /** Maximum visible lines before scrolling (default: 5) */
  maxVisibleLines?: number;
  /** Dark mode */
  isDark?: boolean;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ReasoningStream({
  entries,
  isProcessing,
  maxVisibleLines = 5,
  isDark = true,
}: ReasoningStreamProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Initialize to 0 — will be set from first entry's timestamp, not mount time
  const startTimeRef = useRef<number>(0);
  const [elapsedDisplay, setElapsedDisplay] = useState(0);
  // Track whether the user manually toggled expand after auto-collapse
  const userToggledRef = useRef(false);

  // Derive start time from the first entry's timestamp (works for both live + replay)
  useEffect(() => {
    if (entries.length > 0 && startTimeRef.current === 0) {
      startTimeRef.current = entries[0].ts;
    }
  }, [entries]);

  // Auto-scroll to bottom when new entries arrive
  useEffect(() => {
    if (scrollRef.current && isExpanded) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries.length, isExpanded]);

  // Auto-collapse when processing completes — but respect user's manual toggle
  useEffect(() => {
    if (!isProcessing && entries.length > 0 && !userToggledRef.current) {
      const timer = setTimeout(() => setIsExpanded(false), 600);
      return () => clearTimeout(timer);
    }
  }, [isProcessing, entries.length]);

  // Auto-expand when processing starts (reset user toggle for new processing cycle)
  useEffect(() => {
    if (isProcessing && entries.length > 0) {
      setIsExpanded(true);
      userToggledRef.current = false;
      // Re-initialize start time for new processing cycle
      if (entries.length > 0) {
        startTimeRef.current = entries[0].ts;
      }
    }
  }, [isProcessing]); // eslint-disable-line react-hooks/exhaustive-deps

  // Live elapsed timer while processing
  useEffect(() => {
    if (!isProcessing) {
      // Freeze at final value — guard against NaN / negative
      if (entries.length > 0 && startTimeRef.current > 0) {
        const last = entries[entries.length - 1];
        const delta = last.ts - startTimeRef.current;
        setElapsedDisplay(Math.max(0, Math.round(delta / 1000)));
      }
      return;
    }
    if (startTimeRef.current === 0) return; // no entries yet
    const interval = setInterval(() => {
      const delta = Date.now() - startTimeRef.current;
      setElapsedDisplay(Math.max(0, Math.round(delta / 1000)));
    }, 1000);
    return () => clearInterval(interval);
  }, [isProcessing, entries]);

  const toggleExpand = useCallback(() => {
    userToggledRef.current = true; // Respect user's manual toggle — suppress auto-collapse
    setIsExpanded((prev) => !prev);
  }, []);

  if (entries.length === 0) return null;

  const totalSteps = entries.length;
  const lineHeight = 24; // px
  const maxHeight = maxVisibleLines * lineHeight + 16; // + padding

  return (
    <div
      className={cn(
        "mb-2 rounded-lg border overflow-hidden transition-all duration-200",
        isDark
          ? "border-zinc-800/60 bg-zinc-900/40 backdrop-blur-sm"
          : "border-zinc-200/80 bg-zinc-50/60"
      )}
    >
      {/* Header — always visible */}
      <button
        onClick={toggleExpand}
        className={cn(
          "flex w-full items-center gap-2 px-3 py-2 text-left",
          "text-xs transition-colors",
          isDark
            ? "text-zinc-400 hover:text-zinc-300 hover:bg-zinc-800/30"
            : "text-zinc-500 hover:text-zinc-600 hover:bg-zinc-100/60"
        )}
      >
        <Brain
          className={cn(
            "h-3.5 w-3.5 shrink-0",
            isDark ? "text-violet-400/80" : "text-violet-500/70"
          )}
        />

        {isProcessing ? (
          <>
            <span
              className={cn(
                "font-medium",
                isDark ? "text-violet-400/90" : "text-violet-600/90"
              )}
            >
              Reasoning
            </span>
            <span className="ml-auto flex items-center gap-1.5">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-violet-400 opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-violet-500" />
              </span>
            </span>
          </>
        ) : (
          <>
            <span
              className={cn(
                "font-medium",
                isDark ? "text-zinc-500" : "text-zinc-400"
              )}
            >
              {elapsedDisplay > 0 ? `Thought for ${elapsedDisplay}s` : "Thought process"}
            </span>
            <span className={isDark ? "text-zinc-600 ml-1" : "text-zinc-400 ml-1"}>
              {totalSteps > 0 ? `· ${totalSteps} thought${totalSteps !== 1 ? "s" : ""}` : ""}
            </span>
          </>
        )}

        {isExpanded ? (
          <ChevronDown
            className={cn(
              "h-3 w-3 ml-auto shrink-0",
              isDark ? "text-zinc-500" : "text-zinc-400"
            )}
          />
        ) : (
          <ChevronRight
            className={cn(
              "h-3 w-3 ml-auto shrink-0",
              isDark ? "text-zinc-500" : "text-zinc-400"
            )}
          />
        )}
      </button>

      {/* Content — collapsible with CSS transition */}
      <div
        className={cn(
          "transition-all duration-200 ease-in-out overflow-hidden",
          isExpanded ? "opacity-100" : "max-h-0 opacity-0"
        )}
        style={isExpanded ? { maxHeight: `${maxHeight}px` } : undefined}
      >
        <div
          ref={scrollRef}
          className="reasoning-scroll px-3 pb-2 overflow-y-auto scroll-smooth"
          style={{ maxHeight: `${maxHeight}px` }}
        >
          {entries.map((entry, i) => (
            <div
              key={i}
              className="flex gap-2 py-0.5 animate-reasoning-fade-in"
              style={{ animationDelay: `${Math.min(i * 30, 150)}ms` }}
            >
              {/* Step number for thinking, muted dot for reasoning */}
              <span
                className={cn(
                  "shrink-0 text-[10px] font-medium leading-relaxed w-4 text-right",
                  entry.type === "thinking"
                    ? isDark
                      ? "text-violet-400/80"
                      : "text-violet-500/70"
                    : isDark
                    ? "text-zinc-600"
                    : "text-zinc-400"
                )}
              >
                {i + 1}.
              </span>
              <span
                className={cn(
                  "text-xs leading-relaxed break-words min-w-0",
                  entry.type === "thinking"
                    ? isDark
                      ? "text-zinc-300/90"
                      : "text-zinc-700"
                    : isDark
                    ? "text-zinc-500"
                    : "text-zinc-400"
                )}
              >
                {entry.text}
              </span>
            </div>
          ))}

          {/* Pulsing cursor while processing */}
          {isProcessing && (
            <div className="flex gap-2 py-0.5">
              <span
                className={cn(
                  "mt-1.5 h-1.5 w-1.5 rounded-full animate-pulse shrink-0",
                  isDark ? "bg-violet-400" : "bg-violet-500"
                )}
              />
              <span className={isDark ? "text-xs text-zinc-600" : "text-xs text-zinc-400"}>
                ...
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

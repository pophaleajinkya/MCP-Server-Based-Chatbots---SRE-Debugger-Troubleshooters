"use client";

import { useTheme } from "@/contexts/ThemeContext";
import { MarkdownRenderer } from "./MarkdownRenderer";
import type { InjectionEvent } from "@/types";

/**
 * Renders a single out-of-band "injection" event as a visually-distinct
 * notification card in the chat stream. Injections are markdown payloads
 * pushed by external producers (openclaw monitoring loop, alertmanager,
 * deployment agents, ...) via super-agent's POST /sessions/{id}/inject_message.
 *
 * Design goals:
 *  - Visually clearly NOT a user or assistant bubble — this is a system
 *    observation, not a conversation turn.
 *  - Readable but unobtrusive: amber/blue accent stripe, compact padding.
 *  - Renders the markdown exactly as the producer framed it; super-agent
 *    never rewrites the payload.
 */
export function InjectionCard({ event }: { event: InjectionEvent }) {
  const { theme } = useTheme();
  const isDark = theme === "dark";

  const ts = event.timestamp.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div
      className={`flex gap-3 items-start rounded-xl border-l-4 px-4 py-3 shadow-sm ${
        isDark
          ? "bg-amber-950/20 border-amber-500/70"
          : "bg-amber-50 border-amber-400"
      }`}
    >
      {/* Bell / broadcast icon */}
      <div
        className={`flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center ${
          isDark ? "bg-amber-900/40 text-amber-300" : "bg-amber-100 text-amber-700"
        }`}
        aria-hidden="true"
      >
        <svg
          className="w-4 h-4"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 10-12 0v3.2c0 .5-.2 1-.6 1.4L4 17h5m6 0a3 3 0 11-6 0m6 0H9"
          />
        </svg>
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1 gap-2">
          <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
            {/* Producer label — falls back to "System observation" when the
                injection didn't carry a sidecar `source=` marker (legacy
                producers, alertmanager via raw POST, etc.). */}
            <span
              className={`text-[10px] font-semibold uppercase tracking-wide truncate ${
                isDark ? "text-amber-300" : "text-amber-700"
              }`}
              title={event.source ?? undefined}
            >
              {event.source ?? "System observation"}
            </span>
            {/* Render at most one "kind" badge — the most actionable one — so
                the row stays readable. We DON'T render alert-id badges here
                (the markdown body already names the alert in its heading). */}
            {renderKindBadge(event.tags, isDark)}
          </div>
          <span
            className={`text-[10px] select-none flex-shrink-0 ${
              isDark ? "text-amber-400/70" : "text-amber-700/70"
            }`}
          >
            {ts}
          </span>
        </div>

        {/* Content is producer-authored markdown. Super-agent treats it as
            opaque text; we render it with the same MarkdownRenderer the
            assistant bubble uses so headings / lists / code blocks all work.
            The sidecar marker has already been stripped in parseSidecarMeta. */}
        <MarkdownRenderer content={event.content} isStreaming={false} />
      </div>
    </div>
  );
}

/** Render a small colored chip for the lifecycle "kind" tag if present.
 *  Tag format from openclaw: "kind:verdict_change" / "kind:terminal_verdict"
 *  / "kind:max_retries_reached" / "kind:verdict_unchanged" / etc. */
function renderKindBadge(tags: string[] | undefined, isDark: boolean) {
  if (!tags?.length) return null;
  const kindTag = tags.find((t) => t.startsWith("kind:"));
  if (!kindTag) return null;
  const kind = kindTag.slice("kind:".length);

  // Color theme per kind — tuned to convey urgency at a glance without
  // overwhelming the surrounding amber card.
  const palette = (() => {
    switch (kind) {
      case "terminal_verdict":
        return isDark
          ? "bg-emerald-900/40 text-emerald-300 border-emerald-700/40"
          : "bg-emerald-100 text-emerald-800 border-emerald-300";
      case "verdict_change":
        return isDark
          ? "bg-blue-900/40 text-blue-300 border-blue-700/40"
          : "bg-blue-100 text-blue-800 border-blue-300";
      case "max_retries_reached":
        return isDark
          ? "bg-red-900/40 text-red-300 border-red-700/40"
          : "bg-red-100 text-red-800 border-red-300";
      case "verdict_unchanged":
        return isDark
          ? "bg-gray-800/60 text-gray-400 border-gray-700/40"
          : "bg-gray-100 text-gray-600 border-gray-300";
      default:
        return isDark
          ? "bg-amber-900/40 text-amber-300 border-amber-700/40"
          : "bg-amber-100 text-amber-800 border-amber-300";
    }
  })();

  return (
    <span
      className={`text-[9px] font-medium px-1.5 py-0.5 rounded border ${palette}`}
    >
      {kind.replace(/_/g, " ")}
    </span>
  );
}

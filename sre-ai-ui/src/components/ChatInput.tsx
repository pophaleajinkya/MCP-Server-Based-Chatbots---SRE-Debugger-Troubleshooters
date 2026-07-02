"use client";

import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { Send, Square } from "lucide-react";
import { useTheme } from "@/contexts/ThemeContext";

interface ChatInputProps {
  onSend: (query: string) => void;
  onStop?: () => void;
  isLoading: boolean;
  isReadOnly?: boolean;
  placeholder?: string;
  prefillValue?: string;
  onPrefillConsumed?: () => void;
  showSuggestions?: boolean;
}

const SUGGESTED_QUERIES = [
  { icon: "🛡️", text: "Check health of namespace intl-sre" },
  { icon: "🔗", text: "Get dependencies for namespace item-assembler-async and app iro-prod" },
  { icon: "🛡️", text: "Check health of namespace unified-promise-discovery and app unifiedpromise-prod-tg2"},
  { icon: "🌐", text: "Run edge network analysis on https://www.walmart.com" },
  { icon: "🚀", text: "What deployments are running in sre-tools?" },
  { icon: "🔴", text: "Are there any pod failures in intl-sre?" },
];

export function ChatInput({ onSend, onStop, isLoading, isReadOnly, placeholder, prefillValue, onPrefillConsumed, showSuggestions }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { theme } = useTheme();
  const isDark = theme === "dark";

  useEffect(() => {
    if (prefillValue) {
      setValue(prefillValue);
      textareaRef.current?.focus();
      onPrefillConsumed?.();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillValue]);

  function handleSend() {
    const trimmed = value.trim();
    if (!trimmed || isLoading) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  function handleStop() {
    onStop?.();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (isLoading) {
        handleStop();
      } else {
        handleSend();
      }
    }
  }

  function handleInput() {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }
  }

  if (isReadOnly) {
    return (
      <div className={`flex items-center justify-center gap-2 py-3 px-4 rounded-2xl border text-sm ${
        isDark
          ? "border-amber-700/50 bg-amber-900/20 text-amber-400"
          : "border-amber-200 bg-amber-50 text-amber-700"
      }`}>
        <span>👁️</span>
        <span>You&apos;re viewing a shared conversation — <button onClick={() => window.location.href = "/"} className="underline font-medium hover:opacity-80">start a new chat</button> to ask your own questions.</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Suggested queries — only on new chat, hide while loading */}
      {showSuggestions && value === "" && !isLoading && (
        <div className="flex flex-wrap gap-2">
          {SUGGESTED_QUERIES.map((q) => (
            <button
              key={q.text}
              onClick={() => { setValue(q.text); textareaRef.current?.focus(); }}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full transition-all shadow-sm ${
                isDark
                  ? "bg-[#1c2332] text-gray-400 hover:text-[#60a5fa] hover:brightness-110"
                  : "bg-white border border-gray-200 text-gray-600 hover:border-[#0071CE] hover:text-[#0071CE] hover:bg-blue-50/60"
              }`}
            >
              <span>{q.icon}</span>
              <span>{q.text}</span>
            </button>
          ))}
        </div>
      )}

      {/* Input box */}
      <div className={`flex items-center gap-3 rounded-2xl border shadow-sm px-4 py-2.5 transition-all focus-within:ring-2 ${
        isLoading
          ? isDark
            ? "bg-[#1c2332] border-orange-700/50 focus-within:border-orange-500 focus-within:ring-orange-500/15"
            : "bg-white border-orange-200 focus-within:border-orange-400 focus-within:ring-orange-400/15"
          : isDark
            ? "bg-[#1c2332] border-[#30363d] focus-within:border-[#0071CE] focus-within:ring-[#0071CE]/15"
            : "bg-white border-gray-200 focus-within:border-[#0071CE] focus-within:ring-[#0071CE]/10"
      }`}>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          rows={1}
          placeholder={isLoading ? "Generating… press Stop or type your next question" : (placeholder ?? "Ask about WCNP namespaces, deployments, latency…")}
          className={`flex-1 resize-none bg-transparent text-sm focus:outline-none leading-normal ${
            isDark
              ? "text-gray-100 placeholder-gray-500"
              : "text-gray-800 placeholder-gray-400"
          }`}
          style={{ maxHeight: "200px", paddingTop: 0, paddingBottom: 0 }}
        />

        {isLoading ? (
          /* Stop button */
          <button
            onClick={handleStop}
            className="self-center flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center bg-gradient-to-br from-orange-500 to-red-500 text-white hover:brightness-110 transition-all active:scale-95 shadow-sm"
            title="Stop generation"
          >
            <Square className="w-4 h-4 fill-white" />
          </button>
        ) : (
          /* Send button */
          <button
            onClick={handleSend}
            disabled={!value.trim()}
            className="self-center flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center bg-gradient-to-br from-[#0071CE] to-[#004fa3] text-white disabled:opacity-35 hover:brightness-110 transition-all active:scale-95 shadow-sm"
            title="Send"
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>

      {(isLoading || showSuggestions) && (
        <p className={`text-xs text-center ${isDark ? "text-gray-500" : "text-gray-400"}`}>
        {isLoading ? (
          <>
            Press{" "}
            <kbd className={`px-1.5 py-0.5 border rounded font-mono text-[10px] ${
              isDark
                ? "bg-orange-900/30 border-orange-700/50 text-orange-400"
                : "bg-orange-50 border-orange-200 text-orange-500"
            }`}>
              Enter
            </kbd>{" "}
            or click{" "}
            <span className={`font-medium ${isDark ? "text-orange-400" : "text-orange-500"}`}>Stop</span> to cancel
          </>
        ) : (
          <>
            Press{" "}
            <kbd className={`px-1.5 py-0.5 border rounded font-mono text-[10px] ${
              isDark
                ? "bg-[#1c2332] border-gray-700 text-gray-400"
                : "bg-gray-100 border-gray-200 text-gray-500"
            }`}>
              Enter
            </kbd>{" "}
            to send ·{" "}
            <kbd className={`px-1.5 py-0.5 border rounded font-mono text-[10px] ${
              isDark
                ? "bg-[#1c2332] border-gray-700 text-gray-400"
                : "bg-gray-100 border-gray-200 text-gray-500"
            }`}>
              Shift+Enter
            </kbd>{" "}
            for new line
          </>
        )}
      </p>
      )}
    </div>
  );
}

"use client";

import { useState } from "react";
import type { ChatMessage, ErrorDetail } from "@/types";
import { AlertCircle, Bot, User, ChevronDown, ChevronUp, Copy, Check } from "lucide-react";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { useTheme } from "@/contexts/ThemeContext";

interface MessageItemProps {
  message: ChatMessage;
}

export function MessageItem({ message }: MessageItemProps) {
  const isUser = message.role === "user";
  const { theme } = useTheme();
  const isDark = theme === "dark";

  // Extract copyable text from the message
  const copyText = message.content || message.parsedData?.text || "";

  return (
    <div className={`group/msg flex gap-3 items-end ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center text-white text-xs font-semibold shadow-sm ${
          isUser
            ? "bg-gradient-to-br from-amber-400 to-orange-500"
            : "bg-gradient-to-br from-[#0071CE] to-[#004fa3]"
        }`}
      >
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      {/* Bubble */}
      <div
        className={`relative ${
          isUser
            ? "max-w-[55%] rounded-2xl rounded-br-sm px-4 py-3 bg-gradient-to-br from-[#0071CE] to-[#004fa3] text-white shadow-md"
            : `flex-1 min-w-0 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm ${
                isDark ? "bg-[#1c2332]" : "bg-white border border-gray-100"
              }`
        }`}
      >
        {/* User message */}
        {isUser && (
          <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">{message.content}</p>
        )}

        {/* Assistant error */}
        {!isUser && message.error && (
          <ErrorBlock detail={message.errorDetail ?? { error: message.error }} />
        )}

        {/* Assistant response */}
        {!isUser && !message.isStreaming && !message.error && message.content && (
          <MarkdownRenderer content={message.content} />
        )}

        {/* Timestamp + Copy */}
        <div
          className={`flex items-center gap-1.5 mt-2 ${
            isUser ? "justify-end" : "justify-start"
          }`}
        >
          {message.timestamp && (
            <p
              className={`text-[10px] select-none ${
                isUser ? "text-blue-200/80" : isDark ? "text-gray-500" : "text-gray-300"
              }`}
            >
              {message.timestamp.toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </p>
          )}
          {copyText && !message.isStreaming && (
            <CopyButton
              text={copyText}
              variant={isUser ? "light" : "default"}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function ErrorBlock({ detail }: { detail: ErrorDetail }) {
  const [showStack, setShowStack] = useState(false);

  return (
    <div className="rounded-xl border border-red-200 bg-red-50 overflow-hidden text-sm">
      {/* Header */}
      <div className="flex items-start gap-2.5 px-4 py-3 bg-red-100/80 border-b border-red-200">
        <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
        <div className="min-w-0">
          <p className="font-semibold text-red-700 text-sm">Agent Error</p>
          <p className="text-red-600 text-xs mt-0.5 break-words leading-relaxed">{detail.error}</p>
        </div>
      </div>

      {/* Details */}
      <div className="px-4 py-3 space-y-2">
        {detail.hint && (
          <DetailRow icon="💡" label="Hint" value={detail.hint} valueClass="text-amber-700 font-medium" />
        )}
        {detail.agentUrl && detail.agentUrl !== "unknown" && (
          <DetailRow icon="🔗" label="Agent URL" value={detail.agentUrl} mono />
        )}
        {detail.agentId && detail.agentId !== "unknown" && (
          <DetailRow icon="🤖" label="Agent ID" value={detail.agentId} mono />
        )}
        {detail.taskState && (
          <DetailRow icon="📋" label="Task State" value={detail.taskState} mono />
        )}
      </div>

      {/* Stack trace */}
      {detail.stack && (
        <div className="border-t border-red-200">
          <button
            onClick={() => setShowStack((v) => !v)}
            className="w-full flex items-center justify-between px-4 py-2 text-xs text-red-400 hover:bg-red-100 transition-colors font-medium"
          >
            <span>Stack trace</span>
            {showStack ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          {showStack && (
            <pre className="px-4 pb-3 text-[10px] text-red-500 font-mono whitespace-pre-wrap break-all leading-relaxed overflow-x-auto max-h-48 bg-red-50/50">
              {detail.stack}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function DetailRow({
  icon, label, value, mono, valueClass,
}: {
  icon: string; label: string; value: string; mono?: boolean; valueClass?: string;
}) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="flex-shrink-0">{icon}</span>
      <span className="text-gray-400 flex-shrink-0 w-20">{label}</span>
      <span className={`break-all leading-relaxed ${mono ? "font-mono text-gray-600" : ""} ${valueClass ?? "text-gray-700"}`}>
        {value}
      </span>
    </div>
  );
}

export function CopyButton({
  text,
  className = "",
  variant = "default",
}: {
  text: string;
  className?: string;
  variant?: "default" | "light";
}) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard may be blocked */
    }
  }

  return (
    <button
      onClick={handleCopy}
      className={`opacity-0 group-hover/msg:opacity-100 transition-opacity p-1 rounded-md ${
        variant === "light"
          ? "hover:bg-white/20 text-white/60 hover:text-white"
          : "hover:bg-gray-100 text-gray-300 hover:text-gray-500"
      } ${className}`}
      title="Copy message"
    >
      {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}


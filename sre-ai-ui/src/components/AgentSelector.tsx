"use client";

import { useEffect, useState, useRef } from "react";
import type { AgentConfig } from "@/types";
import { ChevronDown, Bot, Loader2 } from "lucide-react";
import { useTheme } from "@/contexts/ThemeContext";

interface AgentSelectorProps {
  selectedId: string;
  onChange: (agent: AgentConfig) => void;
  onLoadingChange?: (loading: boolean) => void;
  /** Pre-loaded agents from the server — skips the /api/agents fetch entirely. */
  initialAgents?: AgentConfig[];
}

export function AgentSelector({ selectedId, onChange, onLoadingChange, initialAgents }: AgentSelectorProps) {
  const [agents, setAgents] = useState<AgentConfig[]>(() => initialAgents ?? []);
  const [loading, setLoading] = useState(() => !initialAgents?.length);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  const isDark = theme === "dark";

  useEffect(() => {
    // Auto-select first agent when pre-loaded from server
    if (initialAgents?.length && !initialAgents.find((a) => a.id === selectedId)) {
      onChange(initialAgents[0]);
    }
    onLoadingChange?.(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Skip fetch if agents were pre-loaded from the server
    if (initialAgents?.length) return;
    onLoadingChange?.(true);
    fetch("/api/agents")
      .then((r) => r.json())
      .then((data) => {
        const list: AgentConfig[] = data.agents ?? [];
        setAgents(list);
        if (list.length > 0 && !list.find((a) => a.id === selectedId)) {
          onChange(list[0]);
        }
      })
      .catch(() => setAgents([]))
      .finally(() => {
        setLoading(false);
        onLoadingChange?.(false);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const selected = agents.find((a) => a.id === selectedId) ?? agents[0];

  if (loading) {
    return (
      <div className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border rounded-lg ${
        isDark
          ? "text-gray-400 border-gray-700/50 bg-gray-800/60"
          : "text-gray-500 border-gray-200 bg-gray-50"
      }`}>
        <Loader2 className="w-3 h-3 animate-spin" />
        Loading agents…
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <div className={`px-3 py-1.5 text-xs border rounded-lg ${
        isDark
          ? "text-red-400 border-red-800/50 bg-red-900/30"
          : "text-red-500 border-red-200 bg-red-50"
      }`}>
        No agents configured
      </div>
    );
  }

  // Single agent — show static pill, no dropdown needed
  if (agents.length === 1) {
    return (
      <div className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border rounded-lg ${
        isDark
          ? "text-gray-300 border-gray-700/50 bg-gray-800/60"
          : "text-gray-600 border-gray-200 bg-gray-50"
      }`}>
        <span className="text-sm">{selected?.emoji ?? "🤖"}</span>
        <span className="font-medium">{selected?.name ?? "Agent"}</span>
      </div>
    );
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-2 px-3 py-1.5 text-xs font-medium border rounded-lg transition-all ${
          isDark
            ? "border-gray-700/50 bg-gray-800/60 hover:bg-gray-700/80 hover:border-[#0071CE]/50 text-gray-300"
            : "border-gray-200 bg-white hover:bg-gray-50 hover:border-[#0071CE] text-gray-700 shadow-sm"
        }`}
      >
        <span className="text-sm">{selected?.emoji ?? "🤖"}</span>
        <span className="max-w-[140px] truncate">
          {selected?.name ?? "Select agent"}
        </span>
        <ChevronDown
          className={`w-3.5 h-3.5 transition-transform ${open ? "rotate-180" : ""} ${isDark ? "text-gray-500" : "text-gray-400"}`}
        />
      </button>

      {open && (
        <div className={`absolute right-0 top-full mt-2 w-72 border rounded-xl shadow-2xl z-50 overflow-hidden ${
          isDark
            ? "bg-gray-900 border-gray-700/50"
            : "bg-white border-gray-200"
        }`}>
          <div className={`px-3 py-2 border-b ${isDark ? "border-gray-800" : "border-gray-100"}`}>
            <p className={`text-[10px] font-semibold uppercase tracking-wider ${isDark ? "text-gray-500" : "text-gray-400"}`}>
              Select Agent
            </p>
          </div>
          <ul className="py-1 max-h-64 overflow-y-auto">
            {agents.map((agent) => (
              <li key={agent.id}>
                <button
                  onClick={() => {
                    onChange(agent);
                    setOpen(false);
                  }}
                  className={`w-full flex items-start gap-3 px-4 py-2.5 text-left transition-colors ${
                    agent.id === selectedId
                      ? isDark ? "bg-[#0071CE]/15" : "bg-blue-50"
                      : isDark ? "hover:bg-gray-800" : "hover:bg-gray-50"
                  }`}
                >
                  <span className="text-xl flex-shrink-0 mt-0.5">
                    {agent.emoji ?? "🤖"}
                  </span>
                  <div className="min-w-0">
                    <p
                      className={`text-sm font-medium truncate ${
                        agent.id === selectedId
                          ? "text-[#0071CE]"
                          : isDark ? "text-gray-200" : "text-gray-800"
                      }`}
                    >
                      {agent.name}
                      {agent.id === selectedId && (
                        <span className="ml-1.5 text-[10px] text-[#0071CE] font-semibold">
                          ACTIVE
                        </span>
                      )}
                    </p>
                    {agent.description && (
                      <p className={`text-xs truncate mt-0.5 ${isDark ? "text-gray-500" : "text-gray-500"}`}>
                        {agent.description}
                      </p>
                    )}
                    <p className={`text-[10px] font-mono truncate mt-0.5 ${isDark ? "text-gray-600" : "text-gray-400"}`}>
                      {agent.url.replace("https://", "").replace("/a2a", "")}
                    </p>
                  </div>
                  {agent.id === selectedId && (
                    <Bot className="w-4 h-4 text-[#0071CE] flex-shrink-0 ml-auto mt-0.5" />
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

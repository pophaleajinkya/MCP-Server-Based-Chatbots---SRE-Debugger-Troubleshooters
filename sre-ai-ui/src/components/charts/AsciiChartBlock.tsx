"use client";

import { useState } from "react";
import { BarChart2, Copy, Check } from "lucide-react";

interface AsciiChartBlockProps {
  content: string;
  title?: string;
}

export function AsciiChartBlock({ content, title }: AsciiChartBlockProps) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="rounded-xl border border-gray-700/40 overflow-hidden my-3 shadow-lg">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#161b22] border-b border-gray-700/40">
        <div className="flex items-center gap-2">
          <BarChart2 className="w-3.5 h-3.5 text-blue-400" />
          <span className="text-xs font-semibold text-gray-300">
            {title ?? "Chart"}
          </span>
          <span className="text-[10px] text-gray-500 bg-gray-800/80 px-1.5 py-0.5 rounded font-mono">
            ascii
          </span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-200 transition-colors"
        >
          {copied ? (
            <Check className="w-3 h-3 text-green-400" />
          ) : (
            <Copy className="w-3 h-3" />
          )}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>

      {/* ASCII content — horizontal scroll, fixed-width font, no wrapping */}
      <div className="bg-[#0d1117] overflow-x-auto">
        <pre
          className="px-5 py-4 text-[0.78rem] leading-[1.55] text-[#c9d1d9] whitespace-pre select-text"
          style={{ fontFamily: "var(--font-mono), 'JetBrains Mono', Consolas, monospace" }}
        >
          {content}
        </pre>
      </div>

      {/* Footer hint */}
      <div className="flex items-center justify-end px-4 py-1.5 bg-[#0d1117] border-t border-gray-800/60">
        <p className="text-[10px] text-gray-600">
          Scroll horizontally to see full chart
        </p>
      </div>
    </div>
  );
}

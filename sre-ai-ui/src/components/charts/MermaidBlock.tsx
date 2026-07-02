"use client";

import { useEffect, useRef, useState } from "react";
import { GitBranch, Copy, Check } from "lucide-react";
import DOMPurify from "dompurify";
import { autoFixMermaid } from "@/lib/mermaid-utils";

interface MermaidBlockProps {
  content: string;
}

export function MermaidBlock({ content }: MermaidBlockProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wasAutoCorrected, setWasAutoCorrected] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "neutral" });

        let diagramContent = content;

        // Step 1: Pre-validate original content
        try {
          await mermaid.parse(content);
        } catch {
          // Step 2: Auto-fix and validate again
          diagramContent = autoFixMermaid(content);
          try {
            await mermaid.parse(diagramContent);
            if (!cancelled) setWasAutoCorrected(true);
          } catch {
            // Even auto-fix couldn't save it — show fallback
            if (!cancelled) setError("Invalid diagram syntax");
            return;
          }
        }

        // Step 3: Render the (possibly auto-fixed) diagram
        const id = `mermaid-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, diagramContent);

        if (!cancelled && ref.current) {
          ref.current.innerHTML = DOMPurify.sanitize(svg, {
            USE_PROFILES: { svg: true },
            ADD_TAGS: ["foreignObject"],
          });
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError("Failed to render diagram");
      }
    }

    // Debounce 400ms — prevents hammering mermaid during streaming
    const timer = setTimeout(render, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [content]);

  function handleCopy() {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="rounded-xl border border-gray-700/40 overflow-hidden my-3 shadow-lg">
      {/* Header bar — matches AsciiChartBlock style */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#161b22] border-b border-gray-700/40">
        <div className="flex items-center gap-2">
          <GitBranch className="w-3.5 h-3.5 text-blue-400" />
          <span className="text-xs font-semibold text-gray-300">Dependency Map</span>
          <span className="text-[10px] text-gray-500 bg-gray-800/80 px-1.5 py-0.5 rounded font-mono">
            mermaid
          </span>
          {wasAutoCorrected && (
            <span className="text-[10px] text-yellow-400 bg-yellow-900/30 px-1.5 py-0.5 rounded">
              auto-corrected
            </span>
          )}
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

      {/* Rendered SVG — white background for diagram readability */}
      <div className="bg-white overflow-x-auto px-4 py-4">
        {error ? (
          <div>
            <p className="text-xs text-red-400 mb-2">{error}</p>
            <pre className="text-xs text-gray-500 whitespace-pre-wrap bg-gray-50 p-3 rounded border border-gray-200 overflow-x-auto">
              {content}
            </pre>
          </div>
        ) : (
          <div ref={ref} className="min-h-[80px]" />
        )}
      </div>
    </div>
  );
}

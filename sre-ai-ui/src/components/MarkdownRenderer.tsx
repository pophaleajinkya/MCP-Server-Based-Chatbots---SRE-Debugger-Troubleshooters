"use client";

import React from "react";
import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AsciiChartBlock } from "./charts/AsciiChartBlock";

// Dynamic import prevents recharts (which accesses `window` internally) from
// running during SSR and causing "window is not defined" crashes on page load.
const RechartsBlock = dynamic(
  () => import("./charts/RechartsBlock").then((m) => ({ default: m.RechartsBlock })),
  { ssr: false }
);

// Dynamic import prevents mermaid (which accesses `window` internally) from
// running during SSR and causing "window is not defined" crashes on page load.
const MermaidBlock = dynamic(
  () => import("./charts/MermaidBlock").then((m) => ({ default: m.MermaidBlock })),
  { ssr: false }
);

/**
 * Detects ASCII bar/line charts using box-drawing and block characters.
 * Heuristic: has y-axis labels (e.g. "160 ┤") and block chars (▄█).
 */
function isAsciiChart(content: string): boolean {
  const hasYAxis = /^\s*\d+\s*[┤├|]/m.test(content);
  const hasBlocks = /[▄█▀▐▌▒░]/.test(content);
  const hasBoxLines = /[┌─┐└┘│┼┬┴├┤]/.test(content);
  const lineCount = content.split("\n").length;
  return (hasYAxis || hasBoxLines) && hasBlocks && lineCount > 3;
}

/**
 * Extracts a title hint from the first line of ASCII chart content.
 * e.g. "CPU Cores   Day 1 (Mar 7)..." → "CPU Cores"
 */
function extractAsciiTitle(content: string): string | undefined {
  const firstLine = content.split("\n")[0].trim();
  if (!firstLine || firstLine.startsWith("┌") || /^\d/.test(firstLine)) return undefined;
  const match = firstLine.match(/^([A-Za-z][A-Za-z0-9 /()%]+?)(?:\s{3,})/);
  return match ? match[1].trim() : undefined;
}

interface MarkdownRendererProps {
  content: string;
  className?: string;
  isStreaming?: boolean;
}

/** Render inline markdown (links, bold, etc.) inside a table cell. */
function InlineMarkdown({ children }: { children: React.ReactNode }) {
  // If children is not a plain string, react-markdown has already processed it
  // into React elements — return as-is to avoid String(element) → "[object Object]"
  if (typeof children !== "string") {
    return <>{children}</>;
  }
  const text = children;
  // Only re-process if it looks like it contains markdown links/formatting
  if (!text.includes("[") && !text.includes("**") && !text.includes("_")) {
    return <>{children}</>;
  }
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      unwrapDisallowed
      allowedElements={["a", "strong", "em", "code", "del"]}
      components={{
        a({ href, children: linkChildren }) {
          return (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-[#0071CE] underline hover:opacity-80">
              {linkChildren}
            </a>
          );
        },
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

export function MarkdownRenderer({ content, className, isStreaming }: MarkdownRendererProps) {
  return (
    <div className={`prose-adk ${isStreaming ? "streaming-cursor" : ""} ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Always render links as clickable anchors opening in new tab
          a({ href, children: linkChildren }) {
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" className="text-[#0071CE] underline hover:opacity-80">
                {linkChildren}
              </a>
            );
          },
          // Wrap table in overflow-x-auto so wide tables scroll instead of squashing cells
          table({ children }) {
            return (
              <div className="overflow-x-auto my-4 rounded-lg">
                <table className="min-w-full">{children}</table>
              </div>
            );
          },
          // Process inline markdown (links) inside table cells
          td({ children }) {
            return (
              <td className="max-w-xs">
                <InlineMarkdown>{children}</InlineMarkdown>
              </td>
            );
          },
          th({ children }) {
            return (
              <th className="whitespace-nowrap">
                <InlineMarkdown>{children}</InlineMarkdown>
              </th>
            );
          },
          // Intercept all <pre><code> blocks before default rendering
          pre({ children, ...props }) {
            const codeEl = React.Children.toArray(children).find(
              (c): c is React.ReactElement =>
                React.isValidElement(c) && (c as React.ReactElement).type === "code"
            ) as React.ReactElement<{ className?: string; children?: React.ReactNode }> | undefined;

            const langClass: string = codeEl?.props?.className ?? "";
            const rawContent: string = String(codeEl?.props?.children ?? "").replace(/\n$/, "");

            // Route: JSON chart block (```chart ... ```)
            if (langClass.includes("language-chart")) {
              const chart = <RechartsBlock content={rawContent} />;
              if (chart) return chart;
            }

            // Route: Mermaid diagram block (```mermaid ... ```)
            // During streaming the content arrives incrementally — partial mermaid
            // syntax causes cascading "Syntax error in text" from mermaid v11.
            // Show a placeholder with raw source until the stream finishes.
            if (langClass.includes("language-mermaid")) {
              if (isStreaming) {
                return (
                  <div className="rounded-xl border border-gray-700/40 overflow-hidden my-3">
                    <div className="flex items-center gap-2 px-4 py-2.5 bg-[#161b22] border-b border-gray-700/40">
                      <span className="text-xs font-semibold text-gray-300">Dependency Map</span>
                      <span className="text-[10px] text-gray-500 bg-gray-800/80 px-1.5 py-0.5 rounded font-mono">mermaid</span>
                      <span className="ml-auto text-[10px] text-blue-400 animate-pulse">rendering after stream\u2026</span>
                    </div>
                    <pre className="m-0 px-4 py-3 text-[12px] font-mono text-gray-400 bg-[#0d1117] overflow-x-auto">{rawContent}</pre>
                  </div>
                );
              }
              return <MermaidBlock content={rawContent} />;
            }

            // Route: ASCII art chart detection
            if (isAsciiChart(rawContent)) {
              return (
                <AsciiChartBlock
                  content={rawContent}
                  title={extractAsciiTitle(rawContent)}
                />
              );
            }

            // Route: Python script block (```python or ```tool_code) — from UnsafeLocalCodeExecutor
            const isPythonBlock = langClass.includes("language-python") || langClass.includes("language-tool_code");
            if (isPythonBlock) {
              return (
                <div className="rounded-lg border border-blue-900/40 bg-[#0d1117] overflow-hidden my-1">
                  <div className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-950/40 border-b border-blue-900/30">
                    <span className="text-sm">🐍</span>
                    <span className="text-[11px] font-medium text-blue-300">Python Script</span>
                    <span className="ml-auto text-[10px] text-blue-500 font-mono">executed</span>
                  </div>
                  <pre className="m-0 px-4 py-3 text-[12px] font-mono text-green-200 leading-relaxed overflow-x-auto" style={{ whiteSpace: "pre" }}>
                    {rawContent}
                  </pre>
                </div>
              );
            }

            // Route: Tool output block (```tool_output) — stdout from code execution
            if (langClass.includes("language-tool_output")) {
              return (
                <div className="rounded-lg border border-gray-700/50 bg-[#111827] overflow-hidden my-1">
                  <div className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800/60 border-b border-gray-700/40">
                    <span className="text-sm">📤</span>
                    <span className="text-[11px] font-medium text-gray-300">Output</span>
                  </div>
                  <pre className="m-0 px-4 py-3 text-[12px] font-mono text-gray-100 leading-relaxed overflow-x-auto" style={{ whiteSpace: "pre" }}>
                    {rawContent}
                  </pre>
                </div>
              );
            }

            // Default: styled dark code block (globals.css .prose-adk pre)
            return <pre {...props}>{children}</pre>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

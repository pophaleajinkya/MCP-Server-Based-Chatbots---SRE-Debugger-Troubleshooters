"use client";

import { useEffect, useState, useCallback } from "react";
import DOMPurify from "dompurify";
import { autoFixMermaid } from "@/lib/mermaid-utils";

const MERMAID_CONFIG = {
  startOnLoad: false,
  theme: "default" as const,
  securityLevel: "loose" as const,
  flowchart: {
    useMaxWidth: true,
    htmlLabels: true,
  },
};

interface MermaidDiagramProps {
  diagram?: string | null;
  /** When true, container shrinks to diagram so parent can center it */
  center?: boolean;
}

const MermaidDiagram: React.FC<MermaidDiagramProps> = ({ diagram, center }) => {
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);

  const renderDiagram = useCallback(async () => {
    if (!diagram) return;
    setError(null);
    try {
      const mermaid = (await import("mermaid")).default;
      mermaid.initialize(MERMAID_CONFIG);

      let diagramContent = diagram;

      // Pre-validate; auto-fix if original syntax is invalid
      try {
        await mermaid.parse(diagram);
      } catch {
        diagramContent = autoFixMermaid(diagram);
        await mermaid.parse(diagramContent); // throws if still broken
      }

      const id = `mermaid-${Date.now()}`;
      const { svg: renderedSvg } = await mermaid.render(id, diagramContent);
      setSvg(renderedSvg);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("Mermaid rendering error:", err);
      setError("Failed to load diagram");
    }
  }, [diagram, retryCount]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancelled = false;

    renderDiagram().catch(() => {
      if (!cancelled) setError("Failed to load diagram");
    });

    return () => {
      cancelled = true;
    };
  }, [renderDiagram]);

  if (!diagram) return null;

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-4 border border-gray-200 dark:border-gray-700 rounded bg-gray-50 dark:bg-[#161b22] text-sm text-gray-500 dark:text-gray-400">
        <span>{error}</span>
        <button
          onClick={() => setRetryCount(c => c + 1)}
          className="px-3 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div
      className={`overflow-auto p-2 border border-gray-200 rounded bg-white ${center ? "w-fit max-w-full" : "w-full"}`}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true }, ADD_TAGS: ["foreignObject"] }) }}
    />
  );
};

export default MermaidDiagram;

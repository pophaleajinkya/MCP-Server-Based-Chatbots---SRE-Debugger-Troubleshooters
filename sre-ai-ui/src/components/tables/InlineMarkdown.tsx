"use client";

/**
 * Renders lightweight inline markdown within table cells.
 * Supports: **bold**, *italic*, `code`, and [links](url).
 */
export function InlineMarkdown({ text }: { text: string }) {
  // Split on inline markdown patterns, preserving delimiters as capture groups
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|https?:\/\/[^\s)]+)/g);

  return (
    <>
      {parts.map((part, i) => {
        // **bold**
        if (/^\*\*(.+)\*\*$/.test(part)) {
          return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
        }
        // *italic*
        if (/^\*(.+)\*$/.test(part)) {
          return <em key={i}>{part.slice(1, -1)}</em>;
        }
        // `code`
        if (/^`(.+)`$/.test(part)) {
          return (
            <code key={i} className="px-1 py-0.5 bg-gray-100 text-pink-600 rounded text-[11px] font-mono">
              {part.slice(1, -1)}
            </code>
          );
        }
        // [text](url)
        const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        if (linkMatch) {
          return (
            <a key={i} href={linkMatch[2]} target="_blank" rel="noopener noreferrer"
               className="text-walmart-blue hover:underline font-medium" title={linkMatch[2]}>
              {linkMatch[1]}
            </a>
          );
        }
        // Plain URL
        if (/^https?:\/\/[^\s)]+$/.test(part)) {
          return (
            <a key={i} href={part} target="_blank" rel="noopener noreferrer"
               className="text-walmart-blue hover:underline" title={part}>
              {part}
            </a>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

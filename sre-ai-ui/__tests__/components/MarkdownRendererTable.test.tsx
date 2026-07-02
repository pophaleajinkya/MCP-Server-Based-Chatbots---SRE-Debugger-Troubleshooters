/**
 * MarkdownRendererTable.test.tsx
 *
 * Covers the uncovered td/th component overrides and the local InlineMarkdown
 * function inside src/components/MarkdownRenderer.tsx (lines 53-112).
 *
 * The global react-markdown mock in jest.setup.ts does NOT simulate table
 * rendering, so this file supplies its own file-scoped mock that:
 *   1. Calls the td/th component handlers when the input contains pipe chars.
 *   2. Handles the nested ReactMarkdown call made by InlineMarkdown when the
 *      cell text contains markdown formatting characters.
 */

// ─── Module-level mocks (hoisted before imports by Jest) ─────────────────────

// Override the global react-markdown mock from jest.setup.ts with a
// table-aware version scoped to this file only.
jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({
    children,
    components,
  }: {
    children: string | React.ReactNode;
    remarkPlugins?: unknown[];
    allowedElements?: string[];
    unwrapDisallowed?: boolean;
    components?: Record<string, Function>;
  }) => {
    const React = require("react");

    // Non-string children: wrap and return as-is (top-level guard)
    if (typeof children !== "string")
      return React.createElement("div", null, children);

    // ── Simulate table cell rendering ──────────────────────────────────────
    // When the content contains "|" chars we treat it as a table and exercise
    // the td/th component overrides with a representative set of cell values.
    if (children.includes("|")) {
      const parts: React.ReactNode[] = [];

      const TdComp = components?.td as
        | ((p: { children: React.ReactNode }) => React.ReactNode)
        | undefined;
      const ThComp = components?.th as
        | ((p: { children: React.ReactNode }) => React.ReactNode)
        | undefined;

      // th with a plain string header
      if (ThComp) {
        parts.push(
          React.createElement(
            ThComp as React.FC<{ children: React.ReactNode }>,
            { key: "th1" },
            "Header"
          )
        );
      }

      if (TdComp) {
        // td with a React element child (non-string → InlineMarkdown returns as-is)
        parts.push(
          React.createElement(
            TdComp as React.FC<{ children: React.ReactNode }>,
            { key: "td-el" },
            React.createElement("span", null, "element")
          )
        );

        // td with plain text that has no markdown symbols (no re-processing)
        parts.push(
          React.createElement(
            TdComp as React.FC<{ children: React.ReactNode }>,
            { key: "td-plain" },
            "plain text"
          )
        );

        // td with a markdown link → InlineMarkdown will call ReactMarkdown again
        parts.push(
          React.createElement(
            TdComp as React.FC<{ children: React.ReactNode }>,
            { key: "td-link" },
            "[click here](https://example.com)"
          )
        );

        // td with bold markdown → InlineMarkdown will call ReactMarkdown again
        parts.push(
          React.createElement(
            TdComp as React.FC<{ children: React.ReactNode }>,
            { key: "td-bold" },
            "**bold value**"
          )
        );

        // td with underscore italic → InlineMarkdown will call ReactMarkdown again
        parts.push(
          React.createElement(
            TdComp as React.FC<{ children: React.ReactNode }>,
            { key: "td-italic" },
            "_italic value_"
          )
        );
      }

      return React.createElement("table", null, ...parts);
    }

    // ── Handle nested ReactMarkdown call from InlineMarkdown ────────────────
    // InlineMarkdown calls ReactMarkdown with the raw cell string when it
    // contains "[", "**", or "_".  We simulate the output for each pattern.

    // Markdown link: [text](url)
    if (children.includes("[") && children.includes("](")) {
      const AComp = components?.a as
        | ((p: { href: string; children: React.ReactNode }) => React.ReactNode)
        | undefined;
      const linkMatch = children.match(/\[([^\]]+)\]\(([^)]+)\)/);
      if (linkMatch && AComp) {
        return React.createElement(
          AComp as React.FC<{ href: string; children: React.ReactNode }>,
          { href: linkMatch[2] },
          linkMatch[1]
        );
      }
    }

    // Bold: **text**
    if (children.startsWith("**") && children.endsWith("**")) {
      const innerText = children.slice(2, -2);
      return React.createElement("strong", null, innerText);
    }

    // Underscore italic: _text_
    if (children.startsWith("_") && children.endsWith("_")) {
      const innerText = children.slice(1, -1);
      return React.createElement("em", null, innerText);
    }

    // Default: plain paragraph
    return React.createElement("p", null, children);
  },
}));

jest.mock("@/components/charts/AsciiChartBlock", () => ({
  AsciiChartBlock: ({
    content,
    title,
  }: {
    content: string;
    title?: string;
  }) => (
    <div data-testid="ascii-chart-block" data-title={title ?? ""}>
      {content}
    </div>
  ),
}));

jest.mock("next/dynamic", () => (fn: () => Promise<unknown>) => {
  const factoryStr = fn.toString();
  const isRecharts = factoryStr.includes("RechartsBlock");
  const testId = isRecharts ? "recharts-block" : "mermaid-block";
  return function DynamicComponent({ content }: { content: string }) {
    return <div data-testid={testId}>{content}</div>;
  };
});

// ─── Imports (after mock declarations) ───────────────────────────────────────

import React from "react";
import { render, screen } from "@testing-library/react";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Renders MarkdownRenderer with content that includes a pipe character so
 * the table-aware mock triggers td/th component handler calls.
 */
function renderWithTable(content = "| col |") {
  return render(<MarkdownRenderer content={content} />);
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("MarkdownRenderer — table cell (td/th) overrides and InlineMarkdown", () => {
  // ── th handler ────────────────────────────────────────────────────────────

  describe("th handler", () => {
    it("renders a th cell wrapping InlineMarkdown with plain text", () => {
      renderWithTable();
      // The mock supplies "Header" as the th child.  InlineMarkdown passes it
      // through as-is because it has no markdown symbols.
      const th = document.querySelector("th");
      expect(th).toBeInTheDocument();
      expect(th).toHaveTextContent("Header");
    });
  });

  // ── td handler — non-string child ─────────────────────────────────────────

  describe("td handler — React element child", () => {
    it("renders a td wrapping a React element child without stringifying it", () => {
      renderWithTable();
      // The mock passes a <span>element</span> as the td child.
      // InlineMarkdown detects typeof children !== "string" and returns it as-is.
      const td = document.querySelector("td");
      expect(td).toBeInTheDocument();
    });

    it("preserves the inner span element when child is a React element", () => {
      renderWithTable();
      // The first td receives a React element child; the inner <span> must survive.
      const spanInsideTd = document.querySelector("td span");
      expect(spanInsideTd).toBeInTheDocument();
      expect(spanInsideTd).toHaveTextContent("element");
    });
  });

  // ── td handler — plain string child (no markdown) ─────────────────────────

  describe("td handler — plain text child", () => {
    it("renders a td with plain text that contains no markdown symbols", () => {
      renderWithTable();
      // "plain text" has no "[", "**", or "_", so InlineMarkdown returns as-is.
      expect(screen.getByText("plain text")).toBeInTheDocument();
    });

    it("plain text td is wrapped in a <td> element", () => {
      const { container } = renderWithTable();
      // Find the td that directly holds "plain text" (no child element)
      const tds = Array.from(container.querySelectorAll("td"));
      const plainTd = tds.find((td) => td.textContent === "plain text");
      expect(plainTd).toBeDefined();
    });
  });

  // ── td handler — markdown link ─────────────────────────────────────────────

  describe("td handler — markdown link", () => {
    it("renders an anchor element inside a td for [text](url) content", () => {
      renderWithTable();
      const link = screen.getByRole("link", { name: "click here" });
      expect(link).toBeInTheDocument();
    });

    it("anchor inside td has the correct href", () => {
      renderWithTable();
      const link = screen.getByRole("link", { name: "click here" });
      expect(link).toHaveAttribute("href", "https://example.com");
    });

    it("link inside td opens in a new tab", () => {
      renderWithTable();
      const link = screen.getByRole("link", { name: "click here" });
      expect(link).toHaveAttribute("target", "_blank");
    });

    it("link inside td has rel=noopener noreferrer for security", () => {
      renderWithTable();
      const link = screen.getByRole("link", { name: "click here" });
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    });

    it("link inside td carries the text-[#0071CE] styling class", () => {
      renderWithTable();
      const link = screen.getByRole("link", { name: "click here" });
      expect(link).toHaveClass("text-[#0071CE]");
    });
  });

  // ── td handler — bold text ─────────────────────────────────────────────────

  describe("td handler — bold markdown (**text**)", () => {
    it("renders a <strong> element inside a td for **bold** content", () => {
      renderWithTable();
      const strong = screen.getByText("bold value");
      expect(strong.tagName).toBe("STRONG");
    });

    it("bold element is a descendant of a <td>", () => {
      const { container } = renderWithTable();
      const strong = container.querySelector("td strong");
      expect(strong).toBeInTheDocument();
      expect(strong).toHaveTextContent("bold value");
    });
  });

  // ── td handler — underscore italic ────────────────────────────────────────

  describe("td handler — underscore italic (_text_)", () => {
    it("renders an <em> element inside a td for _italic_ content", () => {
      renderWithTable();
      const em = screen.getByText("italic value");
      expect(em.tagName).toBe("EM");
    });

    it("em element is a descendant of a <td>", () => {
      const { container } = renderWithTable();
      const em = container.querySelector("td em");
      expect(em).toBeInTheDocument();
      expect(em).toHaveTextContent("italic value");
    });
  });

  // ── InlineMarkdown — non-string child guard ────────────────────────────────

  describe("InlineMarkdown — typeof children !== string guard", () => {
    it("does not attempt to re-process a React element child as a string", () => {
      // The mock passes React.createElement("span", null, "element") as the td
      // child.  If InlineMarkdown tried to call String() on it the text content
      // would be "[object Object]".  The guard must prevent that.
      renderWithTable();
      expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
    });
  });

  // ── InlineMarkdown — plain string early return ─────────────────────────────

  describe("InlineMarkdown — plain string without markdown symbols", () => {
    it("renders plain cell content without creating any anchor/strong/em", () => {
      const { container } = renderWithTable();
      // Locate the td containing only "plain text"; it must have no child elements
      // that correspond to markdown formatting.
      const tds = Array.from(container.querySelectorAll("td"));
      const plainTd = tds.find((td) => td.textContent === "plain text");
      expect(plainTd).toBeDefined();
      expect(plainTd!.querySelector("a")).not.toBeInTheDocument();
      expect(plainTd!.querySelector("strong")).not.toBeInTheDocument();
      expect(plainTd!.querySelector("em")).not.toBeInTheDocument();
    });
  });
});

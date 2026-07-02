import React from "react";
import { render, screen } from "@testing-library/react";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";

// ─── Module-level mocks ───────────────────────────────────────────────────────

jest.mock("@/components/charts/AsciiChartBlock", () => ({
  AsciiChartBlock: ({ content, title }: { content: string; title?: string }) => (
    <div data-testid="ascii-chart-block" data-title={title ?? ""}>
      {content}
    </div>
  ),
}));

// next/dynamic: synchronously return a stub component that echoes content so
// we can assert which chart type was rendered without actual dynamic loading.
jest.mock("next/dynamic", () => (fn: () => Promise<unknown>) => {
  // Peek at the promise factory to distinguish RechartsBlock from MermaidBlock.
  // We rely on a shared `DynamicComponent` stub that renders a data-testid derived
  // from the import path captured in the closure string.
  const factoryStr = fn.toString();
  const isRecharts = factoryStr.includes("RechartsBlock");
  const testId = isRecharts ? "recharts-block" : "mermaid-block";

  return function DynamicComponent({ content }: { content: string }) {
    return <div data-testid={testId}>{content}</div>;
  };
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Build a fenced code block string that the react-markdown mock (jest.setup.ts)
 * will parse and route through the `pre` component handler.
 */
function fencedBlock(lang: string, body: string): string {
  return `\`\`\`${lang}\n${body}\`\`\``;
}

/**
 * A minimal ASCII chart string that satisfies isAsciiChart's heuristic:
 *   - Has a Y-axis label  (^\s*\d+\s*[┤├|])
 *   - Has block chars     ([▄█▀▐▌▒░])
 *   - Has > 3 lines
 */
const VALID_ASCII_CHART = [
  "CPU Usage   Column A   Column B",
  "100 ┤▄█▄▄▄▄▄▄",
  " 50 ┤▄▄▄▄████",
  "  0 └──────────",
  "    Jan  Feb  Mar",
].join("\n");

/**
 * An ASCII chart whose first line can be extracted as a title:
 * - starts with a letter, has 3+ trailing spaces before more content.
 */
const ASCII_CHART_WITH_TITLE = [
  "Response Time   2024-01-01",
  "100 ┤▄█▄▄▄",
  " 50 ┤▄▄████",
  "  0 └───────",
  "    Jan  Feb",
].join("\n");

/**
 * An ASCII chart that uses box-drawing lines (no y-axis digits) but has block chars.
 */
const ASCII_CHART_BOX_LINES = [
  "┌────────────────────────────┐",
  "│  Some title                │",
  "│  ▄█▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄        │",
  "│  ▄▄████▄▄▄▄▄▄▄▄▄▄▄        │",
  "└────────────────────────────┘",
].join("\n");

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("MarkdownRenderer", () => {
  // ── Basic rendering ─────────────────────────────────────────────────────────

  describe("basic rendering", () => {
    it("renders plain text content", () => {
      render(<MarkdownRenderer content="Hello world" />);
      expect(screen.getByText("Hello world")).toBeInTheDocument();
    });

    it("renders bold text marked with **", () => {
      render(<MarkdownRenderer content="This is **bold** text" />);
      // The react-markdown mock renders <strong> for **bold**
      const strong = screen.getByText("bold");
      expect(strong.tagName).toBe("STRONG");
    });

    it("renders italic text marked with _", () => {
      render(<MarkdownRenderer content="This is _italic_ text" />);
      const em = screen.getByText("italic");
      expect(em.tagName).toBe("EM");
    });

    it("renders text before and after inline formatting", () => {
      render(<MarkdownRenderer content="Before **bold** after" />);
      expect(screen.getByText(/before/i)).toBeInTheDocument();
      expect(screen.getByText("bold")).toBeInTheDocument();
      expect(screen.getByText(/after/i)).toBeInTheDocument();
    });
  });

  // ── Links ───────────────────────────────────────────────────────────────────

  describe("links", () => {
    it("renders a markdown link as an anchor element", () => {
      render(<MarkdownRenderer content="See [docs](https://example.com) here" />);
      const link = screen.getByRole("link", { name: "docs" });
      expect(link).toBeInTheDocument();
      expect(link).toHaveAttribute("href", "https://example.com");
    });

    it("opens links in a new tab with target=_blank", () => {
      render(<MarkdownRenderer content="[open me](https://example.com)" />);
      const link = screen.getByRole("link", { name: "open me" });
      expect(link).toHaveAttribute("target", "_blank");
    });

    it("sets rel=noopener noreferrer on links for security", () => {
      render(<MarkdownRenderer content="[secure link](https://example.com)" />);
      const link = screen.getByRole("link", { name: "secure link" });
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    });
  });

  // ── className and streaming cursor ──────────────────────────────────────────

  describe("className and streaming", () => {
    it("applies the prose-adk class to the outer wrapper", () => {
      const { container } = render(<MarkdownRenderer content="text" />);
      expect(container.firstChild).toHaveClass("prose-adk");
    });

    it("applies a custom className prop to the outer wrapper", () => {
      const { container } = render(
        <MarkdownRenderer content="text" className="my-custom-class" />
      );
      expect(container.firstChild).toHaveClass("my-custom-class");
    });

    it("applies streaming-cursor class when isStreaming=true", () => {
      const { container } = render(
        <MarkdownRenderer content="text" isStreaming={true} />
      );
      expect(container.firstChild).toHaveClass("streaming-cursor");
    });

    it("does NOT apply streaming-cursor when isStreaming=false", () => {
      const { container } = render(
        <MarkdownRenderer content="text" isStreaming={false} />
      );
      expect(container.firstChild).not.toHaveClass("streaming-cursor");
    });

    it("does NOT apply streaming-cursor when isStreaming is not provided", () => {
      const { container } = render(<MarkdownRenderer content="text" />);
      expect(container.firstChild).not.toHaveClass("streaming-cursor");
    });

    it("applies both custom className and streaming-cursor together", () => {
      const { container } = render(
        <MarkdownRenderer content="text" className="extra" isStreaming={true} />
      );
      expect(container.firstChild).toHaveClass("prose-adk");
      expect(container.firstChild).toHaveClass("streaming-cursor");
      expect(container.firstChild).toHaveClass("extra");
    });
  });

  // ── Code block routing ──────────────────────────────────────────────────────

  describe("fenced code block routing", () => {
    it("renders ```chart blocks via RechartsBlock (dynamic)", () => {
      render(<MarkdownRenderer content={fencedBlock("chart", '{"type":"bar"}')} />);
      expect(screen.getByTestId("recharts-block")).toBeInTheDocument();
    });

    it("passes the chart JSON content to RechartsBlock", () => {
      const chartJson = '{"type":"line","data":[1,2,3]}';
      render(<MarkdownRenderer content={fencedBlock("chart", chartJson)} />);
      expect(screen.getByTestId("recharts-block")).toHaveTextContent(chartJson);
    });

    it("renders ```mermaid blocks via MermaidBlock (dynamic)", () => {
      render(
        <MarkdownRenderer content={fencedBlock("mermaid", "graph TD; A-->B")} />
      );
      expect(screen.getByTestId("mermaid-block")).toBeInTheDocument();
    });

    it("passes the diagram content to MermaidBlock", () => {
      const diagram = "graph LR; A-->B; B-->C";
      render(<MarkdownRenderer content={fencedBlock("mermaid", diagram)} />);
      expect(screen.getByTestId("mermaid-block")).toHaveTextContent(diagram);
    });

    it("renders plain code blocks (no special lang) as <pre>", () => {
      const { container } = render(
        <MarkdownRenderer content={fencedBlock("bash", "echo hello")} />
      );
      const pre = container.querySelector("pre");
      expect(pre).toBeInTheDocument();
      // Should NOT have routed to a special block
      expect(screen.queryByTestId("recharts-block")).not.toBeInTheDocument();
      expect(screen.queryByTestId("mermaid-block")).not.toBeInTheDocument();
      expect(screen.queryByTestId("ascii-chart-block")).not.toBeInTheDocument();
    });

    it("renders no-language code blocks as <pre>", () => {
      const { container } = render(
        <MarkdownRenderer content={fencedBlock("", "some code")} />
      );
      const pre = container.querySelector("pre");
      expect(pre).toBeInTheDocument();
    });

    it("does not render AsciiChartBlock for plain code blocks", () => {
      render(<MarkdownRenderer content={fencedBlock("python", "x = 1")} />);
      expect(screen.queryByTestId("ascii-chart-block")).not.toBeInTheDocument();
    });
  });

  // ── isAsciiChart detection (tested indirectly via <pre> routing) ────────────

  describe("isAsciiChart detection", () => {
    it("renders ASCII chart content inside a code block via AsciiChartBlock", () => {
      render(<MarkdownRenderer content={fencedBlock("", VALID_ASCII_CHART)} />);
      expect(screen.getByTestId("ascii-chart-block")).toBeInTheDocument();
    });

    it("passes the raw ASCII content to AsciiChartBlock", () => {
      render(<MarkdownRenderer content={fencedBlock("", VALID_ASCII_CHART)} />);
      const block = screen.getByTestId("ascii-chart-block");
      // Content should include the chart body (trailing newline stripped)
      expect(block.textContent).toContain("100 ┤▄█▄▄▄▄▄▄");
    });

    it("detects ASCII chart using box-drawing box lines combined with block chars", () => {
      render(<MarkdownRenderer content={fencedBlock("", ASCII_CHART_BOX_LINES)} />);
      expect(screen.getByTestId("ascii-chart-block")).toBeInTheDocument();
    });

    it("does NOT detect ASCII chart when block chars are absent", () => {
      const noBlockChars = [
        "100 ┤--------",
        " 50 ┤--------",
        "  0 └────────",
        "    Jan  Feb",
      ].join("\n");
      const { container } = render(
        <MarkdownRenderer content={fencedBlock("", noBlockChars)} />
      );
      // Without block chars the heuristic fails — falls through to plain <pre>
      expect(screen.queryByTestId("ascii-chart-block")).not.toBeInTheDocument();
      expect(container.querySelector("pre")).toBeInTheDocument();
    });

    it("does NOT detect ASCII chart when there is no y-axis and no box lines", () => {
      const noAxes = [
        "just some text",
        "▄█ with blocks",
        "but no axes here",
        "fourth line",
      ].join("\n");
      const { container } = render(
        <MarkdownRenderer content={fencedBlock("", noAxes)} />
      );
      expect(screen.queryByTestId("ascii-chart-block")).not.toBeInTheDocument();
      expect(container.querySelector("pre")).toBeInTheDocument();
    });

    it("does NOT detect ASCII chart when line count is 3 or fewer", () => {
      // Only 3 lines — heuristic requires > 3
      const tooShort = ["100 ┤▄█", " 50 ┤██", "  0 └──"].join("\n");
      const { container } = render(
        <MarkdownRenderer content={fencedBlock("", tooShort)} />
      );
      expect(screen.queryByTestId("ascii-chart-block")).not.toBeInTheDocument();
      expect(container.querySelector("pre")).toBeInTheDocument();
    });

    it("detects ASCII chart when it has exactly 4 lines", () => {
      // 4 lines is exactly > 3
      const fourLines = [
        "100 ┤▄█▄",
        " 50 ┤██▄",
        "  0 └───",
        "    Jan ",
      ].join("\n");
      render(<MarkdownRenderer content={fencedBlock("", fourLines)} />);
      expect(screen.getByTestId("ascii-chart-block")).toBeInTheDocument();
    });
  });

  // ── extractAsciiTitle (tested indirectly via AsciiChartBlock data-title) ────

  describe("extractAsciiTitle", () => {
    it("extracts a title from the first line when followed by 3+ spaces", () => {
      render(<MarkdownRenderer content={fencedBlock("", ASCII_CHART_WITH_TITLE)} />);
      const block = screen.getByTestId("ascii-chart-block");
      // "Response Time   2024-01-01" → title = "Response Time"
      expect(block.getAttribute("data-title")).toBe("Response Time");
    });

    it("returns no title when first line starts with ┌ (box-drawing)", () => {
      render(<MarkdownRenderer content={fencedBlock("", ASCII_CHART_BOX_LINES)} />);
      const block = screen.getByTestId("ascii-chart-block");
      expect(block.getAttribute("data-title")).toBe("");
    });

    it("returns no title when first line starts with a digit", () => {
      // VALID_ASCII_CHART first line starts with "CPU Usage" — but we construct
      // a chart whose first line is a digit-led y-axis label.
      const digitFirst = [
        "100 ┤▄█▄▄▄▄",
        " 50 ┤▄▄████",
        "  0 └──────",
        "    Jan Feb",
      ].join("\n");
      render(<MarkdownRenderer content={fencedBlock("", digitFirst)} />);
      const block = screen.getByTestId("ascii-chart-block");
      expect(block.getAttribute("data-title")).toBe("");
    });

    it("returns no title when first line has no trailing 3-space separator", () => {
      // First line looks like a label but lacks the 3+ space gap for title extraction.
      const noSeparator = [
        "CPU",
        "100 ┤▄█▄",
        " 50 ┤██▄",
        "  0 └───",
        "    Jan ",
      ].join("\n");
      render(<MarkdownRenderer content={fencedBlock("", noSeparator)} />);
      const block = screen.getByTestId("ascii-chart-block");
      // No match for the 3-space pattern → title is undefined → data-title=""
      expect(block.getAttribute("data-title")).toBe("");
    });

    it("extracts a multi-word title with slash and parens", () => {
      const chartWithComplexTitle = [
        "CPU Cores (%)   Day 1 (Mar 7)",
        "100 ┤▄█▄",
        " 50 ┤██▄",
        "  0 └───",
        "    Jan ",
      ].join("\n");
      render(<MarkdownRenderer content={fencedBlock("", chartWithComplexTitle)} />);
      const block = screen.getByTestId("ascii-chart-block");
      expect(block.getAttribute("data-title")).toBe("CPU Cores (%)");
    });
  });

  // ── Python and tool_output code blocks ────────────────────────────────────

  describe("python and tool_output code blocks", () => {
    it("renders ```python blocks with a Python Script header", () => {
      render(<MarkdownRenderer content={fencedBlock("python", "print('hello')")} />);
      expect(screen.getByText("Python Script")).toBeInTheDocument();
      expect(screen.getByText("print('hello')")).toBeInTheDocument();
    });

    it("renders ```tool_code blocks with a Python Script header", () => {
      render(<MarkdownRenderer content={fencedBlock("tool_code", "x = 42")} />);
      expect(screen.getByText("Python Script")).toBeInTheDocument();
    });

    it("renders ```tool_output blocks with an Output header", () => {
      render(<MarkdownRenderer content={fencedBlock("tool_output", "result: 42")} />);
      expect(screen.getByText("Output")).toBeInTheDocument();
      expect(screen.getByText("result: 42")).toBeInTheDocument();
    });

    it("does not route tool_output blocks to RechartsBlock or AsciiChartBlock", () => {
      render(<MarkdownRenderer content={fencedBlock("tool_output", "some output")} />);
      expect(screen.queryByTestId("recharts-block")).not.toBeInTheDocument();
      expect(screen.queryByTestId("ascii-chart-block")).not.toBeInTheDocument();
      expect(screen.queryByTestId("mermaid-block")).not.toBeInTheDocument();
    });
  });

  // ── Multiple elements in one render ─────────────────────────────────────────

  describe("mixed content", () => {
    it("renders text alongside a chart block", () => {
      const content = `Here is a chart:\n${fencedBlock("chart", '{"type":"pie"}')}`;
      render(<MarkdownRenderer content={content} />);
      expect(screen.getByText(/here is a chart/i)).toBeInTheDocument();
      expect(screen.getByTestId("recharts-block")).toBeInTheDocument();
    });

    it("renders multiple code blocks of different types", () => {
      const content = [
        fencedBlock("chart", '{"type":"bar"}'),
        fencedBlock("mermaid", "graph TD; A-->B"),
      ].join("\n\n");
      render(<MarkdownRenderer content={content} />);
      expect(screen.getByTestId("recharts-block")).toBeInTheDocument();
      expect(screen.getByTestId("mermaid-block")).toBeInTheDocument();
    });
  });
});

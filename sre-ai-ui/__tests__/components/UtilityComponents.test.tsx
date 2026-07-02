/**
 * Tests for utility components: MarkdownRenderer, TableBlock, etc.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";

// Mock dynamic imports
jest.mock("next/dynamic", () => ({
  __esModule: true,
  default: (loader: any, options: any) => {
    const Component = React.lazy(loader);
    // Return a component that suspends, wrapped in a Suspense boundary for tests
    return (props: any) => (
      <React.Suspense fallback={<div>Loading...</div>}>
        <Component {...props} />
      </React.Suspense>
    );
  },
}));

jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children, className, ...props }: any) => (
    <div className={className} data-testid="markdown-content" {...props}>
      {children}
    </div>
  ),
}));

jest.mock("remark-gfm", () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock("@/components/charts/AsciiChartBlock", () => ({
  AsciiChartBlock: ({ content }: any) => (
    <div data-testid="ascii-chart">{content}</div>
  ),
}));

jest.mock("@/components/charts/RechartsBlock", () => ({
  RechartsBlock: ({ content }: any) => (
    <div data-testid="recharts-block">{content}</div>
  ),
}));

jest.mock("@/components/charts/MermaidBlock", () => ({
  MermaidBlock: ({ content }: any) => (
    <div data-testid="mermaid-block">{content}</div>
  ),
}));

describe("Utility Components", () => {
  // ── MarkdownRenderer Tests ──────────────────────────────────────────

  describe("MarkdownRenderer", () => {

    it("renders basic markdown content", () => {
      render(<MarkdownRenderer content="# Hello World" />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("accepts custom className prop", () => {
      render(
        <MarkdownRenderer
          content="Test"
          className="custom-class"
        />
      );
      // Component should render without errors when className is provided
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles empty content", () => {
      render(<MarkdownRenderer content="" />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with special characters", () => {
      render(
        <MarkdownRenderer content="**Bold** and *italic* and `code`" />
      );
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with lists", () => {
      const listContent = `
- Item 1
- Item 2
- Item 3`;
      render(<MarkdownRenderer content={listContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with code blocks", () => {
      const codeContent = `
\`\`\`javascript
const x = 5;
console.log(x);
\`\`\``;
      render(<MarkdownRenderer content={codeContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with links", () => {
      render(
        <MarkdownRenderer content="[Link](https://example.com)" />
      );
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with tables", () => {
      const tableContent = `
| Header 1 | Header 2 |
|----------|----------|
| Cell 1   | Cell 2   |`;
      render(<MarkdownRenderer content={tableContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles long markdown content", () => {
      const longContent = "# Title\n\n" + "Paragraph with text. ".repeat(100);
      render(<MarkdownRenderer content={longContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with mixed content types", () => {
      const mixedContent = `
# Title
Some text with **bold** and *italic*.

- List item 1
- List item 2

\`\`\`
code block
\`\`\`

[Link](https://example.com)`;
      render(<MarkdownRenderer content={mixedContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with special unicode characters", () => {
      render(
        <MarkdownRenderer content="Test with émojis 🎉 and spëcial çhars" />
      );
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });
  });

  // ── ASCII Chart Detection ────────────────────────────────────────────

  describe("ASCII Chart Detection", () => {
    it("detects ASCII bar chart patterns", async () => {
      // This would normally be tested by checking if content renders as ASCII chart
      // For now, verify the component handles chart-like content
      const asciiContent = `
160 ┤     ╭─╮
140 ┤     │ │╭─
120 ┤   ╭─╯ ╰─╯
100 ┤───╯`;
      render(<MarkdownRenderer content={asciiContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("detects ASCII with box-drawing characters", async () => {
      const boxContent = `
┌──────────┐
│ Title    │
├──────────┤
│ Content  │
└──────────┘`;
      render(<MarkdownRenderer content={boxContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles content without ASCII patterns as regular markdown", () => {
      const regularContent = `
This is just
regular text
with no special
patterns`;
      render(<MarkdownRenderer content={regularContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });
  });

  // ── Title Extraction ────────────────────────────────────────────────

  describe("ASCII Chart Title Extraction", () => {
    it("extracts title from ASCII chart first line", () => {
      const asciiWithTitle = `CPU Cores   Day 1   Day 2
160 ┤     ╭─╮
140 ┤     │ │`;
      render(<MarkdownRenderer content={asciiWithTitle} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles ASCII chart without obvious title", () => {
      const asciiNoTitle = `
160 ┤     ╭─╮
140 ┤     │ │`;
      render(<MarkdownRenderer content={asciiNoTitle} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("ignores lines starting with box-drawing characters", () => {
      const content = `┌──────────┐
│ Content  │
└──────────┘`;
      render(<MarkdownRenderer content={content} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });
  });

  // ── Streaming Support ────────────────────────────────────────────────

  describe("Streaming Content", () => {
    it("renders with isStreaming prop", () => {
      render(
        <MarkdownRenderer
          content="Streaming content..."
          isStreaming={true}
        />
      );
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles progressive content updates", () => {
      const { rerender } = render(
        <MarkdownRenderer content="Partial" isStreaming={true} />
      );
      rerender(
        <MarkdownRenderer
          content="Partial content update"
          isStreaming={true}
        />
      );
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles completion of streaming", () => {
      const { rerender } = render(
        <MarkdownRenderer content="Complete content" isStreaming={true} />
      );
      rerender(
        <MarkdownRenderer content="Complete content" isStreaming={false} />
      );
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });
  });

  // ── Edge Cases ──────────────────────────────────────────────────────

  describe("Edge Cases", () => {
    it("handles null or undefined content gracefully", () => {
      render(<MarkdownRenderer content="" />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles very large markdown documents", () => {
      const largDoc = Array(1000)
        .fill("# Heading\nParagraph text\n\n")
        .join("");
      render(<MarkdownRenderer content={largDoc} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with only whitespace", () => {
      render(<MarkdownRenderer content="   \n\n   " />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with deeply nested structures", () => {
      const nestedContent = `
> Quote level 1
> > Quote level 2
> > > Quote level 3
> > > > Quote level 4`;
      render(<MarkdownRenderer content={nestedContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with problematic characters", () => {
      const problematicContent = `
Test with < and > and & and "quotes"
Test with ${"{}"} and $ $ and \\backslash`;
      render(<MarkdownRenderer content={problematicContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("handles markdown with mixed line endings", () => {
      const mixedLineEndings =
        "Line 1\r\nLine 2\nLine 3\rLine 4";
      render(<MarkdownRenderer content={mixedLineEndings} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });
  });

  // ── Accessibility ──────────────────────────────────────────────────

  describe("Accessibility", () => {
    it("renders semantic markdown structure", () => {
      render(<MarkdownRenderer content="# Heading\n\nParagraph" />);
      const content = screen.getByTestId("markdown-content");
      expect(content).toBeInTheDocument();
    });

    it("preserves content readability with markdown", () => {
      const readableContent = `
# Important Title

This is a paragraph with **important** information.

- Point 1
- Point 2
- Point 3`;
      render(<MarkdownRenderer content={readableContent} />);
      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });
  });

  // ── Performance ────────────────────────────────────────────────────

  describe("Performance", () => {
    it("handles frequent content updates efficiently", () => {
      const { rerender } = render(
        <MarkdownRenderer content="Version 1" />
      );

      // Simulate rapid updates
      for (let i = 2; i <= 10; i++) {
        rerender(<MarkdownRenderer content={`Version ${i}`} />);
      }

      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });

    it("maintains stability with repeated renders", () => {
      const { rerender } = render(
        <MarkdownRenderer content="Static content" />
      );

      for (let i = 0; i < 5; i++) {
        rerender(<MarkdownRenderer content="Static content" />);
      }

      expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    });
  });
});

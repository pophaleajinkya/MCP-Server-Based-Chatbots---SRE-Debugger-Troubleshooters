/**
 * Tests for src/components/charts/MermaidBlock.tsx
 */

import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { MermaidBlock } from "@/components/charts/MermaidBlock";

// Mock mermaid library
jest.mock("mermaid", () => ({
  default: {
    initialize: jest.fn(),
    parse: jest.fn().mockResolvedValue(true),
    render: jest.fn().mockResolvedValue({
      svg: '<svg><rect width="100" height="100"></rect></svg>',
    }),
  },
}));

// Set up clipboard mock at module level
const mockClipboardWriteText = jest.fn().mockResolvedValue(undefined);
Object.defineProperty(navigator, "clipboard", {
  value: {
    writeText: mockClipboardWriteText,
  },
  writable: true,
  configurable: true,
});

describe("MermaidBlock", () => {
  beforeEach(() => {
    // Reset timers if they were fake
    if (jest.isMockFunction(setTimeout)) {
      jest.useRealTimers();
    }

    // Clear all mocks
    jest.clearAllMocks();

    // Reset mermaid mock implementations
    const mermaidMock = require("mermaid").default;
    mermaidMock.initialize.mockImplementation(() => {});
    mermaidMock.parse.mockResolvedValue(true);
    mermaidMock.render.mockResolvedValue({
      svg: '<svg><rect width="100" height="100"></rect></svg>',
    });
  });

  afterEach(() => {
    // Ensure real timers are restored
    if (jest.isMockFunction(setTimeout)) {
      jest.useRealTimers();
    }
  });

  // ── Rendering ───────────────────────────────────────────────────────────────

  describe("Rendering", () => {
    it("renders mermaid block container", () => {
      const { container } = render(<MermaidBlock content="graph LR: A --> B" />);

      const block = container.querySelector(".rounded-xl");
      expect(block).toBeInTheDocument();
    });

    it("displays Dependency Map header", () => {
      render(<MermaidBlock content="graph LR: A --> B" />);

      expect(screen.getByText("Dependency Map")).toBeInTheDocument();
    });

    it("shows mermaid label", () => {
      render(<MermaidBlock content="graph LR: A --> B" />);

      expect(screen.getByText("mermaid")).toBeInTheDocument();
    });
  });

  // ── Copy Button ─────────────────────────────────────────────────────────────

  describe("Copy Button", () => {
    it("renders copy button", () => {
      render(<MermaidBlock content="graph LR: A --> B" />);

      const copyButton = screen.getByRole("button");
      expect(copyButton).toBeInTheDocument();
    });

    it("shows Copy text initially", () => {
      render(<MermaidBlock content="graph LR: A --> B" />);

      expect(screen.getByText("Copy")).toBeInTheDocument();
    });

    it("copies content to clipboard when clicked", () => {
      const content = "graph LR: A --> B";

      render(<MermaidBlock content={content} />);

      const copyButton = screen.getByRole("button");
      fireEvent.click(copyButton);

      // Clipboard call should happen synchronously
      expect(mockClipboardWriteText).toHaveBeenCalledWith(content);
    });

    it("shows Copied feedback after copying", () => {
      render(<MermaidBlock content="graph LR: A --> B" />);

      const copyButton = screen.getByRole("button");
      fireEvent.click(copyButton);

      // Copied text should appear immediately after click
      expect(screen.getByText("Copied")).toBeInTheDocument();
    });

    it("returns to Copy text after timeout", async () => {
      render(<MermaidBlock content="graph LR: A --> B" />);

      const copyButton = screen.getByRole("button");
      fireEvent.click(copyButton);

      // Verify Copied is shown immediately
      expect(screen.getByText("Copied")).toBeInTheDocument();

      // Wait for timeout to reset state back to Copy
      await waitFor(
        () => {
          expect(screen.getByText("Copy")).toBeInTheDocument();
        },
        { timeout: 3000 }
      );
    });
  });

  // ── Content Rendering ───────────────────────────────────────────────────────

  describe("Content Rendering", () => {
    it("renders SVG content area", () => {
      const { container } = render(<MermaidBlock content="graph LR: A --> B" />);

      const contentArea = container.querySelector(".bg-white");
      expect(contentArea).toBeInTheDocument();
    });

    it("renders diagram from mermaid", async () => {
      const { container } = render(<MermaidBlock content="graph LR: A --> B" />);

      await waitFor(() => {
        const svg = container.querySelector("svg");
        expect(svg).toBeInTheDocument();
      });
    });
  });

  // ── Error Handling ───────────────────────────────────────────────────────────

  describe("Error Handling", () => {
    it("displays error message on mermaid error", async () => {
      const mermaidMock = require("mermaid").default;
      // Both parse calls must reject — first for original, second for auto-fixed content
      mermaidMock.parse
        .mockRejectedValueOnce(new Error("Invalid syntax"))
        .mockRejectedValueOnce(new Error("Still invalid"));

      const { container } = render(<MermaidBlock content="invalid mermaid" />);

      // Wait for the error message to appear (rendered in a <p> with text-red-400)
      await waitFor(() => {
        const errorElements = container.querySelectorAll("p.text-red-400, .text-red-400");
        expect(errorElements.length).toBeGreaterThan(0);
      });
    });

    it("renders safely with empty content", () => {
      const { container } = render(<MermaidBlock content="" />);

      expect(container.querySelector(".rounded-xl")).toBeInTheDocument();
    });

    it("renders safely with complex content", () => {
      const complexDiagram = `
        graph TD
          A[Start] --> B{Condition}
          B -->|Yes| C[Process]
          B -->|No| D[Stop]
          C --> E[End]
      `;

      const { container } = render(<MermaidBlock content={complexDiagram} />);

      expect(container.querySelector(".rounded-xl")).toBeInTheDocument();
    });
  });

  // ── Theme/Styling ───────────────────────────────────────────────────────────

  describe("Styling", () => {
    it("has proper border styling", () => {
      const { container } = render(<MermaidBlock content="graph LR: A --> B" />);

      const block = container.querySelector(".rounded-xl");
      expect(block?.className).toContain("border");
      expect(block?.className).toContain("rounded-xl");
    });

    it("has dark background header", () => {
      const { container } = render(<MermaidBlock content="graph LR: A --> B" />);

      // Find the header by checking for the dark background color class
      const block = container.querySelector(".rounded-xl");
      const header = block?.querySelector("[class*='bg-']");
      expect(header).toBeInTheDocument();
      // Verify it has the expected dark background class
      expect(header?.className).toMatch(/bg-\[/);
    });

    it("has white background for diagram", () => {
      const { container } = render(<MermaidBlock content="graph LR: A --> B" />);

      const contentArea = container.querySelector(".bg-white");
      expect(contentArea).toBeInTheDocument();
    });
  });

  // ── Content Updates ─────────────────────────────────────────────────────────

  describe("Content Updates", () => {
    it("re-renders when content changes", async () => {
      const { rerender } = render(<MermaidBlock content="graph LR: A --> B" />);

      rerender(<MermaidBlock content="graph LR: C --> D" />);

      expect(screen.getByText("Dependency Map")).toBeInTheDocument();
    });

    it("updates diagram when content changes", () => {
      const { rerender, container } = render(
        <MermaidBlock content="graph LR: A --> B" />
      );

      // Verify initial render created container
      expect(container.querySelector(".rounded-xl")).toBeInTheDocument();

      // Rerender with different content
      rerender(<MermaidBlock content="graph LR: C --> D" />);

      // Verify component still renders correctly with new content
      expect(container.querySelector(".rounded-xl")).toBeInTheDocument();
      expect(screen.getByText("Dependency Map")).toBeInTheDocument();
    });
  });

  // ── Accessibility ───────────────────────────────────────────────────────────

  describe("Accessibility", () => {
    it("copy button is keyboard accessible", () => {
      render(<MermaidBlock content="graph LR: A --> B" />);

      const copyButton = screen.getByRole("button");
      expect(copyButton.tagName).toBe("BUTTON");
    });

    it("has semantic structure", () => {
      const { container } = render(<MermaidBlock content="graph LR: A --> B" />);

      const block = container.querySelector("div");
      expect(block).toBeInTheDocument();
    });
  });
});

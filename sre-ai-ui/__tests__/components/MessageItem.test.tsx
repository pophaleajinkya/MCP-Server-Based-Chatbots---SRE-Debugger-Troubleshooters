/**
 * Tests for src/components/MessageItem.tsx
 *
 * Covers:
 *  - MessageItem: user vs assistant rendering, timestamp, copy button
 *  - ErrorBlock: all detail fields, stack trace toggle
 *  - CopyButton: copy functionality, variant styling
 */

import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";

// ─── Mock dependencies ────────────────────────────────────────────────────────

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: jest.fn(),
}));

jest.mock("@/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => {
    const React = require("react");
    return React.createElement("div", { "data-testid": "markdown-renderer" }, content);
  },
}));

jest.mock("lucide-react", () => ({
  AlertCircle: ({ className }: { className?: string }) => {
    const React = require("react");
    return React.createElement("span", { "data-testid": "alert-circle-icon", className });
  },
  Bot: ({ className }: { className?: string }) => {
    const React = require("react");
    return React.createElement("span", { "data-testid": "bot-icon", className });
  },
  User: ({ className }: { className?: string }) => {
    const React = require("react");
    return React.createElement("span", { "data-testid": "user-icon", className });
  },
  ChevronDown: ({ className }: { className?: string }) => {
    const React = require("react");
    return React.createElement("span", { "data-testid": "chevron-down", className });
  },
  ChevronUp: ({ className }: { className?: string }) => {
    const React = require("react");
    return React.createElement("span", { "data-testid": "chevron-up", className });
  },
  Copy: ({ className }: { className?: string }) => {
    const React = require("react");
    return React.createElement("span", { "data-testid": "copy-icon", className });
  },
  Check: ({ className }: { className?: string }) => {
    const React = require("react");
    return React.createElement("span", { "data-testid": "check-icon", className });
  },
}));

// ─── Typed references to mocks ────────────────────────────────────────────────

import { useTheme } from "@/contexts/ThemeContext";

const mockUseTheme = useTheme as jest.MockedFunction<typeof useTheme>;

// ─── Import components under test ─────────────────────────────────────────────

import { MessageItem, CopyButton } from "@/components/MessageItem";
import type { ChatMessage } from "@/types";

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();
  mockUseTheme.mockReturnValue({
    theme: "light",
    toggleTheme: jest.fn(),
    isDark: false,
  });

  // Mock clipboard API
  Object.assign(navigator, {
    clipboard: {
      writeText: jest.fn().mockResolvedValue(undefined),
    },
  });
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "msg-1",
    role: "user",
    content: "Hello world",
    ...overrides,
  };
}

// ─── Tests: MessageItem ───────────────────────────────────────────────────────

describe("MessageItem", () => {
  // ── User messages ─────────────────────────────────────────────────────────

  it("renders user message with User icon and content text", () => {
    render(<MessageItem message={makeMessage({ role: "user", content: "Test question" })} />);

    expect(screen.getByTestId("user-icon")).toBeInTheDocument();
    expect(screen.getByText("Test question")).toBeInTheDocument();
    expect(screen.queryByTestId("bot-icon")).not.toBeInTheDocument();
  });

  it("renders user message bubble with blue gradient styling", () => {
    const { container } = render(
      <MessageItem message={makeMessage({ role: "user", content: "Hi" })} />
    );

    // The bubble div should have the blue gradient class
    const bubble = container.querySelector(".bg-gradient-to-br.from-\\[\\#0071CE\\]");
    expect(bubble).toBeInTheDocument();
  });

  // ── Assistant messages ────────────────────────────────────────────────────

  it("renders assistant message with Bot icon and MarkdownRenderer", () => {
    render(
      <MessageItem
        message={makeMessage({ role: "assistant", content: "Here is the answer" })}
      />
    );

    expect(screen.getByTestId("bot-icon")).toBeInTheDocument();
    expect(screen.getByTestId("markdown-renderer")).toBeInTheDocument();
    expect(screen.getByText("Here is the answer")).toBeInTheDocument();
    expect(screen.queryByTestId("user-icon")).not.toBeInTheDocument();
  });

  it("does not render MarkdownRenderer when assistant message is streaming", () => {
    render(
      <MessageItem
        message={makeMessage({
          role: "assistant",
          content: "Streaming...",
          isStreaming: true,
        })}
      />
    );

    expect(screen.queryByTestId("markdown-renderer")).not.toBeInTheDocument();
  });

  it("does not render MarkdownRenderer when assistant has empty content", () => {
    render(
      <MessageItem message={makeMessage({ role: "assistant", content: "" })} />
    );

    expect(screen.queryByTestId("markdown-renderer")).not.toBeInTheDocument();
  });

  // ── Error rendering ───────────────────────────────────────────────────────

  it("renders ErrorBlock when assistant message has an error", () => {
    render(
      <MessageItem
        message={makeMessage({
          role: "assistant",
          content: "",
          error: "Something went wrong",
        })}
      />
    );

    expect(screen.getByText("Agent Error")).toBeInTheDocument();
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("renders ErrorBlock with errorDetail fields", () => {
    render(
      <MessageItem
        message={makeMessage({
          role: "assistant",
          content: "",
          error: "Connection failed",
          errorDetail: {
            error: "Connection failed",
            hint: "Check your network",
            agentUrl: "http://agent:8001",
            agentId: "health-agent",
            taskState: "failed",
          },
        })}
      />
    );

    expect(screen.getByText("Connection failed")).toBeInTheDocument();
    expect(screen.getByText("Check your network")).toBeInTheDocument();
    expect(screen.getByText("http://agent:8001")).toBeInTheDocument();
    expect(screen.getByText("health-agent")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("does not render agentUrl when it is 'unknown'", () => {
    render(
      <MessageItem
        message={makeMessage({
          role: "assistant",
          content: "",
          error: "err",
          errorDetail: {
            error: "err",
            agentUrl: "unknown",
            agentId: "unknown",
          },
        })}
      />
    );

    expect(screen.queryByText("unknown")).not.toBeInTheDocument();
  });

  it("toggles stack trace visibility when button is clicked", () => {
    render(
      <MessageItem
        message={makeMessage({
          role: "assistant",
          content: "",
          error: "err",
          errorDetail: {
            error: "err",
            stack: "Error: err\n  at handler (route.ts:10)",
          },
        })}
      />
    );

    // Stack trace button should be visible
    const stackButton = screen.getByText("Stack trace");
    expect(stackButton).toBeInTheDocument();

    // Stack content not visible initially
    expect(screen.queryByText(/at handler/)).not.toBeInTheDocument();
    expect(screen.getByTestId("chevron-down")).toBeInTheDocument();

    // Click to show
    fireEvent.click(stackButton);
    expect(screen.getByText(/at handler/)).toBeInTheDocument();
    expect(screen.getByTestId("chevron-up")).toBeInTheDocument();

    // Click to hide
    fireEvent.click(stackButton);
    expect(screen.queryByText(/at handler/)).not.toBeInTheDocument();
  });

  it("does not render stack trace section when no stack is provided", () => {
    render(
      <MessageItem
        message={makeMessage({
          role: "assistant",
          content: "",
          error: "err",
          errorDetail: { error: "err" },
        })}
      />
    );

    expect(screen.queryByText("Stack trace")).not.toBeInTheDocument();
  });

  it("uses errorDetail when provided, falls back to error string otherwise", () => {
    render(
      <MessageItem
        message={makeMessage({
          role: "assistant",
          content: "",
          error: "fallback error message",
        })}
      />
    );

    // When no errorDetail provided, it should create { error: message.error }
    expect(screen.getByText("fallback error message")).toBeInTheDocument();
  });

  // ── Timestamp ─────────────────────────────────────────────────────────────

  it("renders timestamp when provided", () => {
    const date = new Date(2025, 0, 15, 14, 30);
    render(
      <MessageItem message={makeMessage({ timestamp: date })} />
    );

    // Should show the time in HH:MM format
    const timeText = screen.getByText(/\d{1,2}:\d{2}/);
    expect(timeText).toBeInTheDocument();
  });

  it("does not render timestamp when not provided", () => {
    const { container } = render(
      <MessageItem message={makeMessage({ timestamp: undefined })} />
    );

    // No time element should be rendered (the text-[10px] timestamp paragraph)
    const timestampEl = container.querySelector(".text-\\[10px\\]");
    expect(timestampEl).toBeNull();
  });

  // ── Copy button in message ────────────────────────────────────────────────

  it("renders copy button for user message with non-empty content", () => {
    render(<MessageItem message={makeMessage({ role: "user", content: "Copy me" })} />);

    expect(screen.getByTitle("Copy message")).toBeInTheDocument();
  });

  it("does not render copy button when message is streaming", () => {
    render(
      <MessageItem
        message={makeMessage({ role: "assistant", content: "Loading...", isStreaming: true })}
      />
    );

    expect(screen.queryByTitle("Copy message")).not.toBeInTheDocument();
  });

  it("uses parsedData.text as copyText fallback when content is empty", () => {
    render(
      <MessageItem
        message={makeMessage({
          role: "assistant",
          content: "",
          parsedData: { text: "parsed content" },
        })}
      />
    );

    // With empty content and no error, no MarkdownRenderer, but copy button should still appear
    // since parsedData.text provides the copyText
    // Actually with empty content and no error, no copy button either since copyText = ""
    // Wait: copyText = message.content || message.parsedData?.text || ""
    // "" is falsy so it falls through to parsedData.text = "parsed content"
    expect(screen.getByTitle("Copy message")).toBeInTheDocument();
  });

  it("does not render copy button when content and parsedData are both empty", () => {
    render(
      <MessageItem message={makeMessage({ role: "assistant", content: "" })} />
    );

    expect(screen.queryByTitle("Copy message")).not.toBeInTheDocument();
  });

  // ── Dark mode ─────────────────────────────────────────────────────────────

  it("applies dark mode styling for assistant messages", () => {
    mockUseTheme.mockReturnValue({
      theme: "dark",
      toggleTheme: jest.fn(),
      isDark: true,
    });

    const { container } = render(
      <MessageItem message={makeMessage({ role: "assistant", content: "Dark" })} />
    );

    const darkBubble = container.querySelector(".bg-\\[\\#1c2332\\]");
    expect(darkBubble).toBeInTheDocument();
  });

  it("applies light mode styling for assistant messages", () => {
    const { container } = render(
      <MessageItem message={makeMessage({ role: "assistant", content: "Light" })} />
    );

    const lightBubble = container.querySelector(".bg-white");
    expect(lightBubble).toBeInTheDocument();
  });
});

// ─── Tests: CopyButton ───────────────────────────────────────────────────────

describe("CopyButton", () => {
  it("renders with Copy icon initially", () => {
    render(<CopyButton text="hello" />);

    expect(screen.getByTestId("copy-icon")).toBeInTheDocument();
    expect(screen.queryByTestId("check-icon")).not.toBeInTheDocument();
  });

  it("copies text to clipboard and shows Check icon on click", async () => {
    jest.useFakeTimers();

    render(<CopyButton text="copy this" />);

    const button = screen.getByTitle("Copy message");
    await act(async () => {
      fireEvent.click(button);
    });

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("copy this");
    expect(screen.getByTestId("check-icon")).toBeInTheDocument();
    expect(screen.queryByTestId("copy-icon")).not.toBeInTheDocument();

    // After 1500ms, it should revert
    act(() => {
      jest.advanceTimersByTime(1500);
    });

    expect(screen.getByTestId("copy-icon")).toBeInTheDocument();

    jest.useRealTimers();
  });

  it("handles clipboard failure gracefully", async () => {
    (navigator.clipboard.writeText as jest.Mock).mockRejectedValueOnce(
      new Error("Clipboard blocked")
    );

    render(<CopyButton text="fail copy" />);

    const button = screen.getByTitle("Copy message");
    await act(async () => {
      fireEvent.click(button);
    });

    // Should still show Copy icon (not Check) since copy failed
    expect(screen.getByTestId("copy-icon")).toBeInTheDocument();
  });

  it("applies light variant styling", () => {
    const { container } = render(<CopyButton text="test" variant="light" />);

    const button = container.querySelector("button");
    expect(button?.className).toContain("hover:bg-white/20");
  });

  it("applies default variant styling", () => {
    const { container } = render(<CopyButton text="test" variant="default" />);

    const button = container.querySelector("button");
    expect(button?.className).toContain("hover:bg-gray-100");
  });

  it("applies custom className", () => {
    const { container } = render(<CopyButton text="test" className="extra-class" />);

    const button = container.querySelector("button");
    expect(button?.className).toContain("extra-class");
  });
});

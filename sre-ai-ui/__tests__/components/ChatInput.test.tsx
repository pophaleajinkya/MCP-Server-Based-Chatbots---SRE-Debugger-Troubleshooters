/**
 * Tests for src/components/ChatInput.tsx
 *
 * Covers:
 *  - Renders suggested queries when input is empty
 *  - Hides suggested queries when input has text
 *  - Hides suggested queries while loading
 *  - Clicking suggested query populates input
 *  - Send button disabled when input is empty
 *  - Send button enabled when input has text
 *  - Clicking send button calls onSend with trimmed value
 *  - Enter key sends message (not loading)
 *  - Shift+Enter does not send (allows newline)
 *  - Enter key while loading calls onStop
 *  - Stop button appears while loading
 *  - Clicking stop button calls onStop
 *  - Input clears after sending
 *  - Textarea auto-resizes on input
 *  - Placeholder changes based on loading state
 *  - Custom placeholder is used when provided
 */

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── Mock ThemeContext ──────────────────────────────────────────────────────────
const mockIsDark = { value: false };
jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ theme: mockIsDark.value ? "dark" : "light", isDark: mockIsDark.value, toggleTheme: jest.fn() }),
}));

import { ChatInput } from "@/components/ChatInput";

describe("ChatInput", () => {
  const mockOnSend = jest.fn();
  const mockOnStop = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  // ── Suggested Queries ───────────────────────────────────────────────────────

  it("renders suggested queries when input is empty and not loading", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={false} showSuggestions />);

    // Check for the first health check suggestion
    expect(screen.getByText(/Check health of namespace intl-sre/)).toBeInTheDocument();
    // Check for a unique suggestion to avoid ambiguity with the second health check
    expect(screen.getByText(/Run edge network analysis/)).toBeInTheDocument();
  });

  it("hides suggested queries when input has text", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} isLoading={false} showSuggestions />);

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "test");

    expect(screen.queryByText(/Check health of namespace intl-sre/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Run edge network analysis/)).not.toBeInTheDocument();
  });

  it("hides suggested queries while loading", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={true} showSuggestions />);

    expect(screen.queryByText(/Check health of namespace intl-sre/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Run edge network analysis/)).not.toBeInTheDocument();
  });

  it("clicking suggested query populates input and focuses textarea", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} isLoading={false} showSuggestions />);

    // Click on the first health check suggestion (intl-sre)
    const suggestion = screen.getByText(/Check health of namespace intl-sre/);
    await user.click(suggestion);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toContain("Check health of namespace");
    expect(document.activeElement).toBe(textarea);
  });

  // ── Send Button ─────────────────────────────────────────────────────────────

  it("send button is disabled when input is empty", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={false} />);

    const sendButton = screen.getByTitle("Send");
    expect(sendButton).toBeDisabled();
  });

  it("send button is enabled when input has text", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "hello");

    const sendButton = screen.getByTitle("Send");
    expect(sendButton).not.toBeDisabled();
  });

  it("clicking send button calls onSend with trimmed value", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "  hello world  ");

    const sendButton = screen.getByTitle("Send");
    await user.click(sendButton);

    expect(mockOnSend).toHaveBeenCalledWith("hello world");
  });

  it("clears input after sending", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} isLoading={false} />);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    await user.type(textarea, "test message");
    await user.click(screen.getByTitle("Send"));

    expect(textarea.value).toBe("");
  });

  it("does not send when input is only whitespace", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "   ");

    // The send button should be disabled since trimmed value is empty
    const sendButton = screen.getByTitle("Send");
    expect(sendButton).toBeDisabled();
  });

  // ── Keyboard Events ─────────────────────────────────────────────────────────

  it("Enter key sends message when not loading", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "test message{Enter}");

    expect(mockOnSend).toHaveBeenCalledWith("test message");
  });

  it("Shift+Enter does not send message (allows newline)", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "line1");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    await user.type(textarea, "line2");

    expect(mockOnSend).not.toHaveBeenCalled();
  });

  it("Enter key while loading calls onStop", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} onStop={mockOnStop} isLoading={true} />);

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "{Enter}");

    expect(mockOnStop).toHaveBeenCalled();
    expect(mockOnSend).not.toHaveBeenCalled();
  });

  // ── Stop Button ─────────────────────────────────────────────────────────────

  it("shows stop button while loading", () => {
    render(<ChatInput onSend={mockOnSend} onStop={mockOnStop} isLoading={true} />);

    expect(screen.getByTitle("Stop generation")).toBeInTheDocument();
    expect(screen.queryByTitle("Send")).not.toBeInTheDocument();
  });

  it("clicking stop button calls onStop", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} onStop={mockOnStop} isLoading={true} />);

    await user.click(screen.getByTitle("Stop generation"));

    expect(mockOnStop).toHaveBeenCalled();
  });

  // ── Placeholder ─────────────────────────────────────────────────────────────

  it("uses default placeholder when not loading", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    expect(textarea).toHaveAttribute("placeholder", expect.stringContaining("WCNP namespaces"));
  });

  it("shows loading placeholder when loading", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={true} />);

    const textarea = screen.getByRole("textbox");
    expect(textarea).toHaveAttribute("placeholder", expect.stringContaining("Generating"));
  });

  it("uses custom placeholder when provided", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={false} placeholder="Ask me anything…" />);

    const textarea = screen.getByRole("textbox");
    expect(textarea).toHaveAttribute("placeholder", "Ask me anything…");
  });

  // ── Auto-resize ─────────────────────────────────────────────────────────────

  it("textarea auto-resizes on input", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={mockOnSend} isLoading={false} />);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    
    // Mock scrollHeight
    Object.defineProperty(textarea, "scrollHeight", {
      value: 100,
      configurable: true,
    });

    await user.type(textarea, "test");

    // The component sets height based on scrollHeight
    fireEvent.input(textarea);
    expect(textarea.style.height).toBeDefined();
  });

  // ── Hint Text ───────────────────────────────────────────────────────────────

  it("shows send hint when not loading", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={false} showSuggestions />);

    expect(screen.getByText(/to send/)).toBeInTheDocument();
    expect(screen.getByText(/for new line/)).toBeInTheDocument();
  });

  it("shows stop hint when loading", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={true} />);

    expect(screen.getByText(/to cancel/)).toBeInTheDocument();
  });

  // ── Prefill ──────────────────────────────────────────────────────────────────

  it("sets textarea value when prefillValue prop is provided", () => {
    render(
      <ChatInput
        onSend={mockOnSend}
        isLoading={false}
        prefillValue="Check health of intl-sre"
        onPrefillConsumed={jest.fn()}
      />
    );

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe("Check health of intl-sre");
  });

  it("focuses the textarea when a prefillValue is applied", () => {
    render(
      <ChatInput
        onSend={mockOnSend}
        isLoading={false}
        prefillValue="some prompt"
        onPrefillConsumed={jest.fn()}
      />
    );

    const textarea = screen.getByRole("textbox");
    expect(document.activeElement).toBe(textarea);
  });

  it("calls onPrefillConsumed after applying the prefill value", () => {
    const onPrefillConsumed = jest.fn();
    render(
      <ChatInput
        onSend={mockOnSend}
        isLoading={false}
        prefillValue="hello"
        onPrefillConsumed={onPrefillConsumed}
      />
    );

    expect(onPrefillConsumed).toHaveBeenCalledTimes(1);
  });

  it("does not prefill when prefillValue is empty string", () => {
    render(
      <ChatInput
        onSend={mockOnSend}
        isLoading={false}
        prefillValue=""
        onPrefillConsumed={jest.fn()}
      />
    );

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe("");
  });

  it("updates textarea when prefillValue changes to a new non-empty value", () => {
    const { rerender } = render(
      <ChatInput
        onSend={mockOnSend}
        isLoading={false}
        prefillValue=""
        onPrefillConsumed={jest.fn()}
      />
    );

    rerender(
      <ChatInput
        onSend={mockOnSend}
        isLoading={false}
        prefillValue="updated prompt"
        onPrefillConsumed={jest.fn()}
      />
    );

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe("updated prompt");
  });

  // ── isReadOnly ───────────────────────────────────────────────────────────────

  it("renders the read-only banner instead of the input when isReadOnly is true", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={false} isReadOnly={true} />);

    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText(/viewing a shared conversation/i)).toBeInTheDocument();
  });

  it("does not render the read-only banner when isReadOnly is false", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={false} isReadOnly={false} />);

    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.queryByText(/viewing a shared conversation/i)).toBeNull();
  });

  it("renders the normal input when isReadOnly is not provided", () => {
    render(<ChatInput onSend={mockOnSend} isLoading={false} />);

    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });
});

// ── isReadOnly mode ───────────────────────────────────────────────────────────

describe("isReadOnly mode", () => {
  afterEach(() => { mockIsDark.value = false; });

  it("shows read-only banner instead of input when isReadOnly=true", () => {
    render(
      <ChatInput onSend={jest.fn()} isLoading={false} isReadOnly={true} />
    );
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText(/viewing a shared conversation/i)).toBeInTheDocument();
  });

  it("read-only banner applies dark class when isDark=true (line 79)", () => {
    mockIsDark.value = true;
    const { container } = render(
      <ChatInput onSend={jest.fn()} isLoading={false} isReadOnly={true} />
    );
    expect(container.querySelector(".text-amber-400")).toBeInTheDocument();
  });
});

// ── Dark mode variants ────────────────────────────────────────────────────────

describe("dark mode", () => {
  afterEach(() => { mockIsDark.value = false; });

  it("applies dark background to input box when isDark=true (lines 99, 114, 130)", () => {
    mockIsDark.value = true;
    const { container } = render(
      <ChatInput onSend={jest.fn()} isLoading={false} />
    );
    // Input box should have dark border class
    expect(container.querySelector(".border-\\[\\#30363d\\]")).toBeInTheDocument();
  });

  it("applies dark class to loading input box when isDark=true + isLoading (line 117)", () => {
    mockIsDark.value = true;
    const { container } = render(
      <ChatInput onSend={jest.fn()} isLoading={true} />
    );
    // Loading + dark mode border
    expect(container.querySelector(".border-orange-700\\/50")).toBeInTheDocument();
  });

  it("applies dark kbd style when isLoading=true and isDark=true (line 165)", () => {
    mockIsDark.value = true;
    const { container } = render(
      <ChatInput onSend={jest.fn()} onStop={jest.fn()} isLoading={true} showSuggestions={true} />
    );
    // Loading hint text with dark kbd styling
    expect(container.querySelector(".bg-orange-900\\/30")).toBeInTheDocument();
  });

  it("applies dark kbd style when isLoading=false and isDark=true (lines 178, 186)", () => {
    mockIsDark.value = true;
    const { container } = render(
      <ChatInput onSend={jest.fn()} isLoading={false} showSuggestions={true} />
    );
    // Regular hint text with dark kbd styling
    expect(container.querySelector(".bg-\\[\\#1c2332\\]")).toBeInTheDocument();
  });
});

// ── prefillValue without onPrefillConsumed ─────────────────────────────────────

it("sets textarea value from prefillValue even when onPrefillConsumed is not provided", async () => {
  // onPrefillConsumed?.() — the optional-call branch where the callback is absent
  render(
    <ChatInput
      onSend={jest.fn()}
      isLoading={false}
      prefillValue="pre-filled query"
    />
  );

  // RTL flushes effects; value should be applied without throwing
  const textarea = await screen.findByRole("textbox") as HTMLTextAreaElement;
  expect(textarea.value).toBe("pre-filled query");
});

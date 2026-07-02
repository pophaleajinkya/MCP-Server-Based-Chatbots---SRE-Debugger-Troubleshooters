/**
 * Tests for src/components/ChatSlideOver.tsx
 *
 * Covers panel open/close/collapse states, button interactions, backdrop,
 * context badge, expand/shrink toggle, and body overflow side-effect.
 */

import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom";

// ─── Mock dependencies ────────────────────────────────────────────────────────

jest.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { loginId: "test.user" }, loading: false }),
}));

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false, theme: "light", toggleTheme: jest.fn() }),
}));

jest.mock("@/contexts/ViewContext", () => ({
  useViewContext: () => ({
    getContextSummary: () => "test context",
    selectedApplication: null,
    selectedManagedService: null,
    activeView: "applications",
  }),
}));

jest.mock("@copilotkit/react-core", () => ({
  CopilotKit: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useCopilotChatInternal: () => ({
    messages: [],
    sendMessage: jest.fn(),
    stopGeneration: jest.fn(),
    isLoading: false,
    setMessages: jest.fn(),
  }),
}));

jest.mock("@/components/ChatInterface", () => ({
  TurnRenderer: () => <div data-testid="turn-renderer" />,
}));

jest.mock("@/lib/chat-helpers", () => ({
  groupIntoTurns: () => [],
}));

jest.mock("@/components/AgentSelector", () => ({
  AgentSelector: () => <div data-testid="agent-selector" />,
}));

jest.mock("@/components/ChatInput", () => ({
  ChatInput: ({ onSend }: { onSend: (q: string) => void }) => (
    <div data-testid="chat-input">
      <button onClick={() => onSend("test query")} data-testid="send-btn">
        Send
      </button>
    </div>
  ),
}));

// uuid mock to avoid crypto.randomUUID issues in JSDOM
jest.mock("uuid", () => ({
  v4: () => "test-session-id",
}));

// ─── Import after mocks ──────────────────────────────────────────────────────

import { ChatSlideOver } from "@/components/ChatSlideOver";

// ─── Tests ───────────────────────────────────────────────────────────────────

// Stub scrollIntoView for jsdom (used by bottomRef auto-scroll)
beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
});

describe("ChatSlideOver", () => {
  afterEach(() => {
    // Reset body styles between tests
    document.body.style.overflow = "";
  });

  it('has translate-x-full (off-screen) when mode="closed"', () => {
    const onModeChange = jest.fn();
    const { container } = render(
      <ChatSlideOver mode="closed" onModeChange={onModeChange} />
    );
    // The main panel div should have translate-x-full when not open
    const panel = container.querySelector(".translate-x-full");
    expect(panel).toBeInTheDocument();
  });

  it('renders panel with translate-x-0 when mode="open"', () => {
    const onModeChange = jest.fn();
    const { container } = render(
      <ChatSlideOver mode="open" onModeChange={onModeChange} />
    );
    const panel = container.querySelector(".translate-x-0");
    expect(panel).toBeInTheDocument();
  });

  it('renders collapsed strip when mode="collapsed"', () => {
    const onModeChange = jest.fn();
    render(<ChatSlideOver mode="collapsed" onModeChange={onModeChange} />);
    // The collapsed strip contains a vertical "Ask AI" label with writingMode style
    const allAskAI = screen.getAllByText("Ask AI");
    const verticalLabel = allAskAI.find(
      (el) => (el as HTMLElement).style.writingMode === "vertical-rl"
    );
    expect(verticalLabel).toBeDefined();
  });

  it('close button calls onModeChange("closed")', () => {
    const onModeChange = jest.fn();
    render(<ChatSlideOver mode="open" onModeChange={onModeChange} />);
    const closeBtn = screen.getByTitle("Close");
    fireEvent.click(closeBtn);
    expect(onModeChange).toHaveBeenCalledWith("closed");
  });

  it('collapse button calls onModeChange("collapsed")', () => {
    const onModeChange = jest.fn();
    render(<ChatSlideOver mode="open" onModeChange={onModeChange} />);
    const collapseBtn = screen.getByTitle("Collapse to sidebar");
    fireEvent.click(collapseBtn);
    expect(onModeChange).toHaveBeenCalledWith("collapsed");
  });

  it('clicking collapsed strip calls onModeChange("open")', () => {
    const onModeChange = jest.fn();
    render(<ChatSlideOver mode="collapsed" onModeChange={onModeChange} />);
    // The collapsed strip contains a vertical "Ask AI" label — find the one
    // with writing-mode style (the vertical strip text).
    const allAskAI = screen.getAllByText("Ask AI");
    // The strip text element has an inline writingMode style
    const stripText = allAskAI.find(
      (el) => (el as HTMLElement).style.writingMode === "vertical-rl"
    );
    expect(stripText).toBeDefined();
    // Click the parent fixed container
    fireEvent.click(stripText!.closest("[class*='fixed']")!);
    expect(onModeChange).toHaveBeenCalledWith("open");
  });

  it('backdrop click calls onModeChange("collapsed")', () => {
    const onModeChange = jest.fn();
    const { container } = render(
      <ChatSlideOver mode="open" onModeChange={onModeChange} />
    );
    // Backdrop is the fixed inset-0 div with bg-black/20
    const backdrop = container.querySelector(".bg-black\\/20");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onModeChange).toHaveBeenCalledWith("collapsed");
  });

  it("shows context badge when on applications view", () => {
    const onModeChange = jest.fn();
    render(<ChatSlideOver mode="open" onModeChange={onModeChange} />);
    // The SlideOverChatArea renders a context badge with the applications data text
    // (activeView is "applications" and no selectedApplication, so badge = "Applications data")
    expect(screen.getByText(/Applications data/)).toBeInTheDocument();
  });

  it("expand/shrink toggle changes panel width", () => {
    const onModeChange = jest.fn();
    const { container } = render(
      <ChatSlideOver mode="open" onModeChange={onModeChange} />
    );

    // Initially DEFAULT_WIDTH (420px)
    const panel = container.querySelector(".translate-x-0") as HTMLElement;
    expect(panel).toBeInTheDocument();
    expect(panel.style.width).toBe("420px");

    // Click expand button (title: "Expand panel")
    const expandBtn = screen.getByTitle("Expand panel");
    fireEvent.click(expandBtn);

    // After expand, width should change to EXPANDED_WIDTH (650px)
    expect(panel.style.width).toBe("650px");

    // Now it should show "Shrink panel"
    const shrinkBtn = screen.getByTitle("Shrink panel");
    fireEvent.click(shrinkBtn);

    expect(panel.style.width).toBe("420px");
  });

  it("sets body overflow to hidden when open, empty when not", () => {
    const onModeChange = jest.fn();

    const { rerender } = render(
      <ChatSlideOver mode="open" onModeChange={onModeChange} />
    );
    expect(document.body.style.overflow).toBe("hidden");

    rerender(<ChatSlideOver mode="closed" onModeChange={onModeChange} />);
    expect(document.body.style.overflow).toBe("");
  });
});

// ─── Additional coverage tests ────────────────────────────────────────────────

// Helper to swap mock return values for a single test
function mockViewContext(overrides: Record<string, unknown>) {
  const mod = jest.requireMock("@/contexts/ViewContext");
  const original = mod.useViewContext;
  mod.useViewContext = () => ({
    getContextSummary: () => "test context",
    selectedApplication: null,
    selectedManagedService: null,
    activeView: "applications",
    ...overrides,
  });
  return () => { mod.useViewContext = original; };
}

function mockCopilotChat(overrides: Record<string, unknown>) {
  const mod = jest.requireMock("@copilotkit/react-core");
  const original = mod.useCopilotChatInternal;
  mod.useCopilotChatInternal = () => ({
    messages: [],
    sendMessage: jest.fn(),
    stopGeneration: jest.fn(),
    isLoading: false,
    setMessages: jest.fn(),
    ...overrides,
  });
  return () => { mod.useCopilotChatInternal = original; };
}

function mockGroupIntoTurns(fn: (msgs: unknown[]) => unknown[]) {
  const mod = jest.requireMock("@/lib/chat-helpers");
  const original = mod.groupIntoTurns;
  mod.groupIntoTurns = fn;
  return () => { mod.groupIntoTurns = original; };
}

describe("ChatSlideOver – handleSend (context enrichment)", () => {
  it("calls sendMessage with enriched content when context exists", () => {
    const sendMessage = jest.fn();
    const restore1 = mockCopilotChat({ sendMessage });
    const restore2 = mockViewContext({ getContextSummary: () => "my context summary" });

    // crypto.randomUUID mock for jsdom
    const origRandomUUID = crypto.randomUUID;
    crypto.randomUUID = jest.fn(() => "mock-uuid-1234") as unknown as typeof crypto.randomUUID;

    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    const sendBtn = screen.getByTestId("send-btn");
    fireEvent.click(sendBtn);

    expect(sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "user",
        content: "__SRE_VIEW_CTX_START__\nmy context summary\n__SRE_VIEW_CTX_END__\n\ntest query",
      })
    );

    crypto.randomUUID = origRandomUUID;
    restore1();
    restore2();
  });

  it("calls sendMessage with plain query when no context", () => {
    const sendMessage = jest.fn();
    const restore1 = mockCopilotChat({ sendMessage });
    const restore2 = mockViewContext({ getContextSummary: () => "" });

    const origRandomUUID = crypto.randomUUID;
    crypto.randomUUID = jest.fn(() => "mock-uuid-5678") as unknown as typeof crypto.randomUUID;

    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    fireEvent.click(screen.getByTestId("send-btn"));

    expect(sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "user",
        content: "test query",
      })
    );

    crypto.randomUUID = origRandomUUID;
    restore1();
    restore2();
  });
});

describe("ChatSlideOver – contextBadge variations", () => {
  it("shows selectedApplication badge with tier and tenant", () => {
    const restore = mockViewContext({
      selectedApplication: { name: "MyApp", tier: "Gold", tenant: "Corp" },
      selectedManagedService: null,
      activeView: "applications",
    });

    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    expect(screen.getByText(/MyApp \(Gold, Corp\)/)).toBeInTheDocument();

    restore();
  });

  it("shows selectedApplication badge with N/A fallbacks", () => {
    const restore = mockViewContext({
      selectedApplication: { name: "MyApp", tier: undefined, tenant: undefined },
      selectedManagedService: null,
      activeView: "applications",
    });

    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    expect(screen.getByText(/MyApp \(N\/A, N\/A\)/)).toBeInTheDocument();

    restore();
  });

  it("shows selectedManagedService badge when no app selected", () => {
    const restore = mockViewContext({
      selectedApplication: null,
      selectedManagedService: { name: "Redis Cluster", serviceType: "Redis" },
      activeView: "managed-services",
    });

    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    expect(screen.getByText(/Redis Cluster \(Redis\)/)).toBeInTheDocument();

    restore();
  });

  it('shows "Managed Services data" badge for managed-services view', () => {
    const restore = mockViewContext({
      selectedApplication: null,
      selectedManagedService: null,
      activeView: "managed-services",
    });

    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    expect(screen.getByText(/Managed Services data/)).toBeInTheDocument();

    restore();
  });

  it("shows no badge when activeView is something else", () => {
    const restore = mockViewContext({
      selectedApplication: null,
      selectedManagedService: null,
      activeView: "other",
    });

    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    expect(screen.queryByText(/Applications data/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Managed Services data/)).not.toBeInTheDocument();

    restore();
  });
});

describe("ChatSlideOver – streaming placeholder logic", () => {
  it("marks last assistant turn as streaming when isLoading", () => {
    const turns = [
      { type: "assistant", id: "t1", segments: [{ kind: "text", content: "hi" }], isStreaming: false },
    ];
    const restore1 = mockCopilotChat({ isLoading: true, messages: [{}] });
    const restore2 = mockGroupIntoTurns(() => turns);

    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    // TurnRenderer should be rendered for the turn
    expect(screen.getByTestId("turn-renderer")).toBeInTheDocument();
    // The turn object should have been mutated
    expect(turns[0].isStreaming).toBe(true);

    restore1();
    restore2();
  });

  it("pushes streaming placeholder when last turn is not assistant and isLoading", () => {
    const turns = [
      { type: "user", id: "t1", segments: [{ kind: "text", content: "hello" }] },
    ];
    const restore1 = mockCopilotChat({ isLoading: true, messages: [{}] });
    const restore2 = mockGroupIntoTurns(() => turns);

    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    // Should have 2 turn renderers: user + streaming placeholder
    const renderers = screen.getAllByTestId("turn-renderer");
    expect(renderers.length).toBe(2);

    restore1();
    restore2();
  });
});

describe("ChatSlideOver – empty state context badge hint", () => {
  it("shows 'Context will be automatically included' when contextBadge is present and empty", () => {
    // Default mock has activeView="applications" and no selectedApp, so contextBadge = "Applications data"
    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    expect(screen.getByText("Context will be automatically included")).toBeInTheDocument();
  });

  it("does not show context hint when no badge", () => {
    const restore = mockViewContext({
      selectedApplication: null,
      selectedManagedService: null,
      activeView: "other",
    });

    render(<ChatSlideOver mode="open" onModeChange={jest.fn()} />);
    expect(screen.queryByText("Context will be automatically included")).not.toBeInTheDocument();

    restore();
  });
});

describe("ChatSlideOver – drag resize", () => {
  it("drag handle resizes the panel", () => {
    const { container } = render(
      <ChatSlideOver mode="open" onModeChange={jest.fn()} />
    );

    const panel = container.querySelector(".translate-x-0") as HTMLElement;
    expect(panel.style.width).toBe("420px");

    // Find the drag handle — the div with cursor-col-resize
    const dragHandle = container.querySelector(".cursor-col-resize") as HTMLElement;
    expect(dragHandle).toBeInTheDocument();

    // Simulate drag start
    fireEvent.mouseDown(dragHandle, { clientX: 500 });

    // body cursor should change
    expect(document.body.style.cursor).toBe("col-resize");
    expect(document.body.style.userSelect).toBe("none");

    // Simulate drag move — dragging left (smaller clientX = wider panel)
    act(() => {
      window.dispatchEvent(new MouseEvent("mousemove", { clientX: 400 }));
    });

    // Delta = 500 - 400 = 100, new width = 420 + 100 = 520
    expect(panel.style.width).toBe("520px");

    // Simulate drag end
    act(() => {
      window.dispatchEvent(new MouseEvent("mouseup"));
    });

    // body cursor should be restored
    expect(document.body.style.cursor).toBe("");
    expect(document.body.style.userSelect).toBe("");
  });

  it("clamps width to MIN_WIDTH and MAX_WIDTH", () => {
    const { container } = render(
      <ChatSlideOver mode="open" onModeChange={jest.fn()} />
    );

    const panel = container.querySelector(".translate-x-0") as HTMLElement;
    const dragHandle = container.querySelector(".cursor-col-resize") as HTMLElement;

    // Try to drag way right (shrink below min)
    fireEvent.mouseDown(dragHandle, { clientX: 500 });
    act(() => {
      window.dispatchEvent(new MouseEvent("mousemove", { clientX: 1000 }));
    });
    // Delta = 500 - 1000 = -500, newWidth = 420 + (-500) = -80, clamped to 340
    expect(panel.style.width).toBe("340px");

    act(() => {
      window.dispatchEvent(new MouseEvent("mouseup"));
    });

    // Now drag way left (expand above max)
    fireEvent.mouseDown(dragHandle, { clientX: 500 });
    act(() => {
      window.dispatchEvent(new MouseEvent("mousemove", { clientX: -500 }));
    });
    // Delta = 500 - (-500) = 1000, newWidth = 340 + 1000 = 1340, clamped to 900
    expect(panel.style.width).toBe("900px");

    act(() => {
      window.dispatchEvent(new MouseEvent("mouseup"));
    });
  });

  it("mousemove/mouseup do nothing when not resizing", () => {
    const { container } = render(
      <ChatSlideOver mode="open" onModeChange={jest.fn()} />
    );

    const panel = container.querySelector(".translate-x-0") as HTMLElement;
    expect(panel.style.width).toBe("420px");

    // Dispatch mousemove without a prior mousedown — should not change width
    act(() => {
      window.dispatchEvent(new MouseEvent("mousemove", { clientX: 100 }));
    });
    expect(panel.style.width).toBe("420px");

    // mouseup without resizing should be a no-op
    act(() => {
      window.dispatchEvent(new MouseEvent("mouseup"));
    });
    expect(document.body.style.cursor).not.toBe("col-resize");
  });
});

describe("ChatSlideOver – collapsed strip label and green dot", () => {
  it("shows selectedApplication name in collapsed strip", () => {
    const restore = mockViewContext({
      selectedApplication: { name: "MyApp", tier: "Gold", tenant: "Corp" },
      selectedManagedService: null,
      activeView: "applications",
    });

    render(<ChatSlideOver mode="collapsed" onModeChange={jest.fn()} />);

    // The vertical label should show "MyApp" not "Ask AI"
    const verticalLabels = screen.getAllByText("MyApp");
    const stripLabel = verticalLabels.find(
      (el) => (el as HTMLElement).style.writingMode === "vertical-rl"
    );
    expect(stripLabel).toBeDefined();

    // Green dot should be present (selectedApplication is truthy)
    const greenDot = document.querySelector(".bg-green-500");
    expect(greenDot).toBeInTheDocument();

    restore();
  });

  it("shows selectedManagedService name in collapsed strip", () => {
    const restore = mockViewContext({
      selectedApplication: null,
      selectedManagedService: { name: "Redis Cluster", serviceType: "Redis" },
      activeView: "managed-services",
    });

    render(<ChatSlideOver mode="collapsed" onModeChange={jest.fn()} />);

    const verticalLabels = screen.getAllByText("Redis Cluster");
    const stripLabel = verticalLabels.find(
      (el) => (el as HTMLElement).style.writingMode === "vertical-rl"
    );
    expect(stripLabel).toBeDefined();

    // Green dot should be present
    const greenDot = document.querySelector(".bg-green-500");
    expect(greenDot).toBeInTheDocument();

    restore();
  });

  it('shows "Ask AI" and no green dot when nothing selected', () => {
    render(<ChatSlideOver mode="collapsed" onModeChange={jest.fn()} />);

    const allAskAI = screen.getAllByText("Ask AI");
    const stripLabel = allAskAI.find(
      (el) => (el as HTMLElement).style.writingMode === "vertical-rl"
    );
    expect(stripLabel).toBeDefined();

    // No green dot when nothing selected
    const greenDot = document.querySelector(".bg-green-500");
    expect(greenDot).not.toBeInTheDocument();
  });
});

function mockTheme(overrides: Record<string, unknown>) {
  const mod = jest.requireMock("@/contexts/ThemeContext");
  const original = mod.useTheme;
  mod.useTheme = () => ({
    isDark: false,
    theme: "light",
    toggleTheme: jest.fn(),
    ...overrides,
  });
  return () => { mod.useTheme = original; };
}

describe("ChatSlideOver – dark theme branches", () => {
  it("renders context badge with dark styles", () => {
    const restoreTheme = mockTheme({ theme: "dark", isDark: true });

    const { container } = render(
      <ChatSlideOver mode="open" onModeChange={jest.fn()} />
    );

    // Context badge should have dark bg class
    const badge = container.querySelector(".bg-blue-950\\/30");
    expect(badge).toBeInTheDocument();

    restoreTheme();
  });

  it("renders collapsed strip with dark styles", () => {
    const restoreTheme = mockTheme({ theme: "dark", isDark: true });

    const { container } = render(
      <ChatSlideOver mode="collapsed" onModeChange={jest.fn()} />
    );

    // Collapsed strip container should have dark bg class
    const darkStrip = container.querySelector(".bg-\\[\\#161b22\\]");
    expect(darkStrip).toBeInTheDocument();

    restoreTheme();
  });
});

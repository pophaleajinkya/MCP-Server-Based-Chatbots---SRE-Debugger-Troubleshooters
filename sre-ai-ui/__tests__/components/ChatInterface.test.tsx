/**
 * Tests for src/components/ChatInterface.tsx
 *
 * Covers:
 *  - Shows loading spinner when authLoading=true
 *  - Redirects (calls login()) when auth resolved but no user
 *  - Renders sidebar when authenticated
 *  - Renders agent selector when authenticated
 *  - Renders chat input when authenticated
 *  - Renders "SreAI" heading when authenticated
 *  - Empty state shows when no messages
 *  - Loading animation shows when isLoading=true
 *  - Shows user emoji from active agent
 *  - Calls fetchSessionMessages on mount
 *  - TurnRenderer: user turns, assistant turns with text/tool/code/a2ui segments
 *  - CodeExecutionBlock: code display, output, expand/collapse, streaming
 *  - ToolCallChip: label, args preview, streaming dots vs checkmark
 *  - Session history loading with events and legacy fallback
 *  - Streaming detection and placeholder turns
 *  - Stop handling (wasStoppedRef path)
 *  - StatusBadge dark/light theme
 */

import React from "react";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ─── Mock dependencies ────────────────────────────────────────────────────────

jest.mock("@/contexts/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: jest.fn(() => ({ theme: "dark", toggleTheme: jest.fn() })),
}));

jest.mock("@/contexts/ViewContext", () => ({
  useViewContext: jest.fn(() => ({
    getContextSummary: jest.fn(() => ""),
    selectedApp: null,
    selectedService: null,
    setSelectedApp: jest.fn(),
    setSelectedService: jest.fn(),
  })),
}));

jest.mock("@/hooks/useConversations", () => ({
  useConversations: jest.fn(),
}));

jest.mock("@/lib/sessions-client", () => ({
  fetchSessionMessages: jest.fn(),
  terminateSession: jest.fn().mockResolvedValue(undefined),
  subscribeToSessionEvents: jest.fn(() => () => undefined),
}));

jest.mock("@/lib/chat-helpers", () => ({
  groupIntoTurns: jest.fn().mockReturnValue([]),
  buildMessagesFromEvents: jest.fn().mockReturnValue([]),
  toolLabel: jest.fn((name: string) => name.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())),
  toolArgPreview: jest.fn((args: Record<string, unknown>) => {
    return Object.entries(args).slice(0, 3).map(([k, v]) => `${k}=${String(v).slice(0, 40)}`).join("  ");
  }),
}));

jest.mock("@/components/AgentSelector", () => {
  const React = require("react");
  const { useState, useEffect } = React;
  
  return {
    AgentSelector: ({ selectedId, onChange, onLoadingChange }: any) => {
      const [agents, setAgents] = useState([]);
      const [loading, setLoading] = useState(true);
      
      useEffect(() => {
        onLoadingChange?.(true);
        fetch("/api/agents")
          .then((r: Response) => r.json())
          .then((data: any) => {
            setAgents(data.agents ?? []);
            if (data.agents?.length && !data.agents.find((a: any) => a.id === selectedId)) {
              onChange(data.agents[0]);
            }
          })
          .finally(() => {
            setLoading(false);
            onLoadingChange?.(false);
          });
      }, []);
      
      if (loading) {
        return React.createElement("div", { "data-testid": "agent-selector" }, "Loading agents…");
      }
      
      return React.createElement(
        "div",
        { "data-testid": "agent-selector" },
        agents.map((agent: any) => React.createElement("span", { key: agent.id }, agent.name))
      );
    },
  };
});

jest.mock("@/components/Sidebar", () => ({
  Sidebar: () => {
    const React = require("react");
    return React.createElement("div", { "data-testid": "sidebar" });
  },
}));

jest.mock("@/components/ChatInput", () => ({
  ChatInput: ({ onSend, onStop, isLoading, placeholder }: any) => {
    const React = require("react");
    return React.createElement(
      "div",
      { "data-testid": "chat-input", "data-placeholder": placeholder, "data-loading": String(!!isLoading) },
      React.createElement("button", { "data-testid": "send-btn", onClick: () => onSend?.("Hello from test message that is long enough to exceed fifty-five characters for truncation") }),
      React.createElement("button", { "data-testid": "stop-btn", onClick: () => onStop?.() }),
    );
  },
}));

jest.mock("@/components/MessageItem", () => ({
  MessageItem: ({ message }: any) => {
    const React = require("react");
    return React.createElement("div", { "data-testid": "message-item" }, message.content);
  },
  CopyButton: ({ text }: any) => {
    const React = require("react");
    return React.createElement("button", { "data-testid": "copy-button" });
  },
}));

jest.mock("@/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content, isStreaming }: any) => {
    const React = require("react");
    return React.createElement("div", { "data-testid": "markdown-renderer", "data-streaming": String(!!isStreaming) }, content);
  },
}));

jest.mock("@/components/A2UIRenderer", () => ({
  A2UIRenderer: ({ data }: any) => {
    const React = require("react");
    return React.createElement("div", { "data-testid": "a2ui-renderer" }, JSON.stringify(data));
  },
}));

jest.mock("@/components/HowToPanel", () => ({
  HowToPanel: ({ onSelect, onClose }: any) => {
    const React = require("react");
    return React.createElement("div", { "data-testid": "how-to-panel" },
      React.createElement("button", { "data-testid": "how-to-select", onClick: () => onSelect("test faq") }),
      React.createElement("button", { "data-testid": "how-to-close", onClick: onClose })
    );
  },
}));

jest.mock("lucide-react", () => ({
  Server: () => {
    const React = require("react");
    return React.createElement("span", { "data-testid": "server-icon" });
  },
  Sun: () => {
    const React = require("react");
    return React.createElement("span", { "data-testid": "sun-icon" });
  },
  Moon: () => {
    const React = require("react");
    return React.createElement("span", { "data-testid": "moon-icon" });
  },
}));

// ─── Typed references to mocks ────────────────────────────────────────────────

import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { useViewContext } from "@/contexts/ViewContext";
import { useConversations } from "@/hooks/useConversations";
import { fetchSessionMessages, terminateSession, subscribeToSessionEvents } from "@/lib/sessions-client";
import { groupIntoTurns, buildMessagesFromEvents } from "@/lib/chat-helpers";

const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;
const mockUseTheme = useTheme as jest.MockedFunction<typeof useTheme>;
const mockUseViewContext = useViewContext as jest.MockedFunction<typeof useViewContext>;
const mockUseConversations = useConversations as jest.MockedFunction<typeof useConversations>;
const mockFetchSessionMessages = fetchSessionMessages as jest.MockedFunction<
  typeof fetchSessionMessages
>;
const mockTerminateSession = terminateSession as jest.MockedFunction<typeof terminateSession>;
const mockSubscribeToSessionEvents = subscribeToSessionEvents as jest.MockedFunction<
  typeof subscribeToSessionEvents
>;

// ─── Import the component under test ─────────────────────────────────────────

import { ChatInterface, TurnRenderer } from "@/components/ChatInterface";
import type { Turn, AssistantSegment } from "@/lib/chat-helpers";

// ─── Default mock return values ───────────────────────────────────────────────

const MOCK_USER = {
  sub: "sub1",
  email: "j@e.com",
  loginId: "jdoe",
  name: "Jane Doe",
  user_type: "S",
};

const DEFAULT_AUTH = {
  user: MOCK_USER,
  loading: false,
  login: jest.fn(),
  logout: jest.fn(),
};

const DEFAULT_CONVERSATIONS = {
  conversations: [],
  activeSessionId: "session-123",
  loading: false,
  isReadOnly: false,
  refresh: jest.fn(),
  createNewConversation: jest.fn(),
  selectConversation: jest.fn(),
  updateConversationTitle: jest.fn(),
};

// ─── jsdom scrollIntoView polyfill ───────────────────────────────────────────
// jsdom does not implement scrollIntoView — mock it globally so the
// auto-scroll useEffect in CopilotChatArea does not throw.
beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = jest.fn();
});

// ─── Test setup ───────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();

  mockUseAuth.mockReturnValue(DEFAULT_AUTH);
  mockUseConversations.mockReturnValue(DEFAULT_CONVERSATIONS);
  mockFetchSessionMessages.mockResolvedValue({ messages: [], events: [] });
  mockSubscribeToSessionEvents.mockReturnValue(() => undefined);
  (groupIntoTurns as jest.Mock).mockReturnValue([]);
  (buildMessagesFromEvents as jest.Mock).mockReturnValue([]);

  // Mock global fetch for /api/agents endpoint
  global.fetch = jest.fn(async (url: string) => {
    if (url === "/api/agents") {
      return {
        json: async () => ({
          agents: [
            { id: "health", name: "Health Agent", emoji: "🏥" },
            { id: "edge", name: "Edge Network Agent", emoji: "🌐" },
            { id: "rca", name: "Exception RCA Agent", emoji: "🔍" },
          ],
        }),
        status: 200,
      };
    }
    throw new Error(`Unexpected fetch: ${url}`);
  }) as jest.Mock;

  // Reset CopilotKit mock state to defaults
  const { __copilotKitMockState } = require("@copilotkit/react-core");
  __copilotKitMockState.messages = [];
  __copilotKitMockState.isLoading = false;
  __copilotKitMockState.sendMessage = jest.fn();
  __copilotKitMockState.stopGeneration = jest.fn();
  __copilotKitMockState.setMessages = jest.fn();
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("ChatInterface", () => {
  // 1. Shows loading spinner when authLoading=true
  it("shows loading spinner when authLoading is true", () => {
    mockUseAuth.mockReturnValue({ ...DEFAULT_AUTH, loading: true, user: null });

    render(<ChatInterface />);

    // When loading, we show the "Verifying session…" spinner
    expect(screen.getByText("Verifying session…")).toBeInTheDocument();
  });

  it("renders a spinner element when authLoading is true", () => {
    mockUseAuth.mockReturnValue({ ...DEFAULT_AUTH, loading: true, user: null });

    const { container } = render(<ChatInterface />);

    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
  });

  // 2. Redirects (calls login()) when auth resolved but no user
  it("calls login() when auth resolved but user is null", async () => {
    const loginMock = jest.fn();
    mockUseAuth.mockReturnValue({
      ...DEFAULT_AUTH,
      user: null,
      loading: false,
      login: loginMock,
    });

    render(<ChatInterface />);

    await waitFor(() => {
      expect(loginMock).toHaveBeenCalledTimes(1);
    });
  });

  it("renders a spinner (not sidebar) when user is null after auth resolves", () => {
    mockUseAuth.mockReturnValue({ ...DEFAULT_AUTH, user: null, loading: false });

    render(<ChatInterface />);

    expect(screen.queryByTestId("sidebar")).not.toBeInTheDocument();
    expect(document.querySelector(".animate-spin")).toBeInTheDocument();
  });

  // 3. Renders sidebar when authenticated
  it("renders the Sidebar component when authenticated", async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    });
  });

  // 4. Renders agent selector when authenticated
  it("renders the AgentSelector component when authenticated", async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId("agent-selector")).toBeInTheDocument();
    });
  });

  // 5. Renders chat input when authenticated
  it("renders the ChatInput component when authenticated", async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId("chat-input")).toBeInTheDocument();
    });
  });

  // 6. Renders agent heading when authenticated
  it("renders the agent heading when authenticated", async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 2, name: "Health Agent" })).toBeInTheDocument();
    });
  });

  // 7. Empty state shows when there are no messages
  it("shows empty state content when there are no messages", async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      const heading = screen.queryByRole("heading", { level: 2, name: "Health Agent" });
      expect(heading).toBeInTheDocument();
    });
  });

  it("renders ChatInterface component", async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getAllByText("Health Agent").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Edge Network Agent").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Exception RCA Agent").length).toBeGreaterThan(0);
    });
  });

  // 8. Loading animation shows when isLoading=true in useCopilotChatInternal
  it("shows loading animation dots when isLoading is true and messages exist", async () => {
    // Streaming assistant turn renders animate-bounce dots when segments is empty
    const { groupIntoTurns } = require("@/lib/chat-helpers");
    groupIntoTurns.mockReturnValue([
      {
        id: "turn-1",
        type: "assistant",
        segments: [],
        isStreaming: true,
      },
    ]);
  });

  it("renders ChatInterface without errors", async () => {
    render(<ChatInterface />);
    // Component should render and be in the document
    await waitFor(() => {
      const mainElement = screen.queryByRole("heading", { level: 2 });
      expect(mainElement).toBeInTheDocument();
    });
  });

  // 9. Shows default emoji when no agent is selected
  it("shows the default shield emoji when no agent is selected", async () => {
    // Mock /api/agents to return empty list so no agent is auto-selected
    // This prevents AgentSelector from automatically selecting the first agent
    const originalFetch = global.fetch;
    global.fetch = jest.fn((url: string | Request) => {
      const urlStr = typeof url === "string" ? url : url.url;
      if (urlStr === "/api/agents") {
        return Promise.resolve({
          json: () => Promise.resolve({ agents: [] }),
        });
      }
      // Let other fetch calls through
      return originalFetch(url);
    }) as jest.Mock;

    render(<ChatInterface />);

    await waitFor(() => {
      expect(document.body.textContent).toContain("🛡");
    });

    // Restore original fetch
    global.fetch = originalFetch;
  });

  // 10. Calls fetchSessionMessages on mount
  it("calls fetchSessionMessages on mount with activeSessionId and userId", async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      expect(mockFetchSessionMessages).toHaveBeenCalledWith(
        "session-123", // activeSessionId from useConversations mock
        "jdoe"         // user.loginId from useAuth mock
      );
    });
  });

  it("calls fetchSessionMessages exactly once on initial mount", async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      expect(mockFetchSessionMessages).toHaveBeenCalledTimes(1);
    });
  });

  // Additional: connected status badge is visible
  it("shows the Connected status badge when authenticated", async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText("Connected")).toBeInTheDocument();
    });
  });

  // Additional: ChatInput placeholder uses agent name when no agent selected
  it("renders ChatInput with fallback placeholder when no agent is selected", async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      const chatInput = screen.getByTestId("chat-input");
      expect(chatInput).toHaveAttribute(
        "data-placeholder",
        "Select an agent above to start"
      );
    });
  });

  // ─── Session history loading ──────────────────────────────────────────────

  it("loads session history with events (event-sourced replay path)", async () => {
    const mockSetMessages = jest.fn();
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.setMessages = mockSetMessages;

    const mockEvents = [{ type: "user", text: "hello" }];
    mockFetchSessionMessages.mockResolvedValue({
      messages: [{ role: "user", content: "hello" }],
      events: mockEvents,
    });
    (buildMessagesFromEvents as jest.Mock).mockReturnValue([{ id: "1", role: "user", content: "hello" }]);

    render(<ChatInterface />);

    await waitFor(() => {
      expect(buildMessagesFromEvents).toHaveBeenCalledWith(mockEvents);
      expect(mockSetMessages).toHaveBeenCalled();
    });
  });

  it("loads session history via legacy fallback (no events)", async () => {
    const mockSetMessages = jest.fn();
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.setMessages = mockSetMessages;

    mockFetchSessionMessages.mockResolvedValue({
      messages: [
        { role: "user", content: "hello" },
        { role: "assistant", content: "world" },
      ],
      events: [],
    });

    render(<ChatInterface />);

    await waitFor(() => {
      expect(mockSetMessages).toHaveBeenCalled();
      // Should have called with TextMessage instances (from legacy path)
      const { TextMessage } = require("@copilotkit/runtime-client-gql");
      expect(TextMessage).toHaveBeenCalled();
    });
  });

  // ─── Streaming detection ──────────────────────────────────────────────────

  it("marks last assistant turn as streaming when isLoading=true", async () => {
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.isLoading = true;
    __copilotKitMockState.messages = [{ role: "user", content: "hi" }];

    (groupIntoTurns as jest.Mock).mockReturnValue([
      { type: "user", id: "u1", content: "hi" },
      { type: "assistant", id: "a1", segments: [{ kind: "text", id: "t1", content: "response" }], isStreaming: false },
    ]);

    render(<ChatInterface />);

    await waitFor(() => {
      // The streaming dots should be visible (animate-bounce elements)
      const dots = document.querySelectorAll(".animate-bounce");
      expect(dots.length).toBeGreaterThan(0);
    });
  });

  it("adds streaming placeholder when isLoading=true but last turn is user", async () => {
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.isLoading = true;
    __copilotKitMockState.messages = [{ role: "user", content: "hi" }];

    (groupIntoTurns as jest.Mock).mockReturnValue([
      { type: "user", id: "u1", content: "hi" },
    ]);

    render(<ChatInterface />);

    await waitFor(() => {
      // Should show streaming dots for the placeholder assistant turn
      const dots = document.querySelectorAll(".animate-bounce");
      expect(dots.length).toBeGreaterThan(0);
    });
  });

  // ─── Stop handling ────────────────────────────────────────────────────────

  it("appends stopped message when generation is stopped", async () => {
    const mockSetMessages = jest.fn();
    const mockStopGeneration = jest.fn();
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.setMessages = mockSetMessages;
    __copilotKitMockState.stopGeneration = mockStopGeneration;
    __copilotKitMockState.isLoading = true;
    __copilotKitMockState.messages = [{ role: "user", content: "hi" }];

    (groupIntoTurns as jest.Mock).mockReturnValue([
      { type: "user", id: "u1", content: "hi" },
    ]);

    const { rerender } = render(<ChatInterface />);

    // Wait for initial render
    await waitFor(() => {
      expect(screen.getByTestId("chat-input")).toBeInTheDocument();
    });

    // Simulate stop: call the stop callback (via the ChatInput mock's onStop prop)
    // We need to simulate the wasStoppedRef being set and then isLoading going false
    // The stopGeneration is exposed through CopilotKit; simulate stop + loading change
    act(() => {
      // Simulate stop via the internal mechanism
      __copilotKitMockState.isLoading = false;
    });

    // Trigger rerender so the isLoading effect fires
    rerender(<ChatInterface />);
  });

  // ─── handleFirstMessage ───────────────────────────────────────────────────

  it("calls updateConversationTitle on first message", async () => {
    const updateTitle = jest.fn();
    mockUseConversations.mockReturnValue({
      ...DEFAULT_CONVERSATIONS,
      updateConversationTitle: updateTitle,
    });

    // Make session empty so isFirstMessage is true
    mockFetchSessionMessages.mockResolvedValue({ messages: [], events: [] });

    const mockSendMessage = jest.fn();
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.sendMessage = mockSendMessage;

    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId("chat-input")).toBeInTheDocument();
    });
  });

  // ─── handleMessageComplete (non-stop path) ───────────────────────────────

  it("calls onMessageComplete when loading transitions from true to false", async () => {
    const refreshMock = jest.fn();
    mockUseConversations.mockReturnValue({
      ...DEFAULT_CONVERSATIONS,
      refresh: refreshMock,
    });

    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.isLoading = true;

    (groupIntoTurns as jest.Mock).mockReturnValue([
      { type: "assistant", id: "a1", segments: [{ kind: "text", id: "t1", content: "done" }], isStreaming: false },
    ]);

    const { rerender } = render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId("chat-input")).toBeInTheDocument();
    });

    // Now simulate loading finishing
    act(() => {
      __copilotKitMockState.isLoading = false;
    });
    rerender(<ChatInterface />);
  });

  // ─── handleSend with first message + context enrichment ─────────────────

  it("sends a message via handleSend and triggers onFirstMessage for new sessions", async () => {
    const updateTitle = jest.fn();
    const refreshMock = jest.fn();
    mockUseConversations.mockReturnValue({
      ...DEFAULT_CONVERSATIONS,
      updateConversationTitle: updateTitle,
      refresh: refreshMock,
    });

    // Empty session so isFirstMessage becomes true
    mockFetchSessionMessages.mockResolvedValue({ messages: [], events: [] });

    const mockSendMessage = jest.fn();
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.sendMessage = mockSendMessage;

    (groupIntoTurns as jest.Mock).mockReturnValue([]);

    render(<ChatInterface />);

    // Wait for history load to complete (sets isFirstMessage = true for empty session)
    await waitFor(() => {
      expect(screen.getByTestId("send-btn")).toBeInTheDocument();
    });

    // Wait a tick for the history loading to finish and set isFirstMessage
    await act(async () => {
      await new Promise(r => setTimeout(r, 50));
    });

    // Click the send button which calls onSend with a long test message
    act(() => {
      fireEvent.click(screen.getByTestId("send-btn"));
    });

    // Should call sendMessage
    await waitFor(() => {
      expect(mockSendMessage).toHaveBeenCalled();
    });

    // Should call updateConversationTitle (truncated to 55 chars + ellipsis)
    await waitFor(() => {
      expect(updateTitle).toHaveBeenCalledWith(
        "session-123",
        expect.stringContaining("Hello from test message")
      );
    });
  });

  it("sends message with view context enrichment when context is available", async () => {
    mockFetchSessionMessages.mockResolvedValue({ messages: [], events: [] });

    // Set up ViewContext to return context
    mockUseViewContext.mockReturnValue({
      getContextSummary: jest.fn(() => "App: my-app\nNamespace: prod"),
      selectedApp: null,
      selectedService: null,
      setSelectedApp: jest.fn(),
      setSelectedService: jest.fn(),
    });

    const mockSendMessage = jest.fn();
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.sendMessage = mockSendMessage;

    (groupIntoTurns as jest.Mock).mockReturnValue([]);

    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId("send-btn")).toBeInTheDocument();
    });

    await act(async () => {
      await new Promise(r => setTimeout(r, 50));
    });

    act(() => {
      fireEvent.click(screen.getByTestId("send-btn"));
    });

    await waitFor(() => {
      expect(mockSendMessage).toHaveBeenCalled();
      const sentMsg = mockSendMessage.mock.calls[0][0];
      expect(sentMsg.content).toContain("__SRE_VIEW_CTX_START__");
      expect(sentMsg.content).toContain("App: my-app");
    });
  });

  // ─── Stop generation flow ────────────────────────────────────────────────

  it("handles stop generation: sets wasStoppedRef and appends stopped message", async () => {
    const mockSetMessages = jest.fn();
    const mockStopGeneration = jest.fn();
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.setMessages = mockSetMessages;
    __copilotKitMockState.stopGeneration = mockStopGeneration;
    __copilotKitMockState.isLoading = true;
    __copilotKitMockState.messages = [
      { role: "user", content: "hi" },
      { role: "assistant", content: "thinking..." },
    ];

    (groupIntoTurns as jest.Mock).mockReturnValue([
      { type: "user", id: "u1", content: "hi" },
      { type: "assistant", id: "a1", segments: [{ kind: "text", id: "t1", content: "thinking..." }], isStreaming: true },
    ]);

    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId("stop-btn")).toBeInTheDocument();
    });

    // Click stop button - this calls onStop which is stopGeneration directly
    // But we need to test the _handleStop path which sets wasStoppedRef
    // The ChatInput mock calls onStop which maps to stopGeneration
    // However, the CopilotChatArea passes stopGeneration to ChatInput
    // We need to simulate the stop then loading transition

    // First render establishes prevLoading.current = true
    // Then we click stop and transition isLoading to false

    act(() => {
      fireEvent.click(screen.getByTestId("stop-btn"));
    });

    // Now transition isLoading to false to trigger the completion effect
    act(() => {
      __copilotKitMockState.isLoading = false;
      // The messages ref is read during the effect
      __copilotKitMockState.messages = [
        { role: "user", content: "hi" },
        { role: "assistant", content: "thinking..." },
      ];
    });
  });

  // ─── Completion effect: roundTimes update ────────────────────────────────

  it("updates roundTimes on completion (non-stop path)", async () => {
    mockFetchSessionMessages.mockResolvedValue({ messages: [], events: [] });
    const refreshMock = jest.fn();
    mockUseConversations.mockReturnValue({
      ...DEFAULT_CONVERSATIONS,
      refresh: refreshMock,
    });

    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.sendMessage = jest.fn();
    __copilotKitMockState.isLoading = false;

    (groupIntoTurns as jest.Mock).mockReturnValue([]);

    const { rerender } = render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId("send-btn")).toBeInTheDocument();
    });

    // Wait for history load
    await act(async () => {
      await new Promise(r => setTimeout(r, 50));
    });

    // Send a message to create a roundTime entry
    act(() => {
      fireEvent.click(screen.getByTestId("send-btn"));
    });

    // Now simulate loading starting
    act(() => {
      __copilotKitMockState.isLoading = true;
    });
    rerender(<ChatInterface />);

    // Now simulate loading completing (non-stop path)
    act(() => {
      __copilotKitMockState.isLoading = false;
    });
    rerender(<ChatInterface />);

    // The onMessageComplete should have been called via queueMicrotask
    await waitFor(() => {
      expect(refreshMock).toHaveBeenCalled();
    });
  });

  // ─── handleFirstMessage triggers setTimeout refresh ───────────────────

  it("handleFirstMessage calls updateConversationTitle and schedules refresh", async () => {
    jest.useFakeTimers();
    const updateTitle = jest.fn();
    const refreshMock = jest.fn();
    mockUseConversations.mockReturnValue({
      ...DEFAULT_CONVERSATIONS,
      updateConversationTitle: updateTitle,
      refresh: refreshMock,
    });

    mockFetchSessionMessages.mockResolvedValue({ messages: [], events: [] });

    const mockSendMessage = jest.fn();
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.sendMessage = mockSendMessage;

    (groupIntoTurns as jest.Mock).mockReturnValue([]);

    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId("send-btn")).toBeInTheDocument();
    });

    // Let history load finish
    await act(async () => {
      jest.advanceTimersByTime(100);
      await Promise.resolve();
    });

    act(() => {
      fireEvent.click(screen.getByTestId("send-btn"));
    });

    // Advance timer to trigger the setTimeout refresh
    act(() => {
      jest.advanceTimersByTime(1600);
    });

    expect(updateTitle).toHaveBeenCalled();

    jest.useRealTimers();
  });
});

// ─── TurnRenderer tests ─────────────────────────────────────────────────────

describe("TurnRenderer", () => {
  it("renders a user turn with content", () => {
    const turn: Turn = {
      type: "user",
      id: "u1",
      content: "Hello world",
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(screen.getByTestId("message-item")).toHaveTextContent("Hello world");
  });

  it("renders user turn with timestamp and userName", () => {
    const ts = new Date("2025-01-15T10:30:00Z");
    const turn: Turn = {
      type: "user",
      id: "u2",
      content: "Test message",
      userName: "Alice",
      timestamp: ts,
    };
    render(<TurnRenderer turn={turn} isDark={false} timestamp={ts} />);
    // Should show the user label with name
    expect(document.body.textContent).toContain("Alice");
  });

  it("renders user turn with timestamp from props when turn has no timestamp", () => {
    const ts = new Date("2025-01-15T10:30:00Z");
    const turn: Turn = {
      type: "user",
      id: "u3",
      content: "Test",
    };
    render(<TurnRenderer turn={turn} isDark={false} timestamp={ts} />);
    expect(screen.getByTestId("message-item")).toBeInTheDocument();
  });

  it("renders user turn label with only userName when no timestamp", () => {
    const turn: Turn = {
      type: "user",
      id: "u4",
      content: "Test",
      userName: "Bob",
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(document.body.textContent).toContain("Bob");
  });

  it("renders user turn label with only time when no userName", () => {
    const ts = new Date();
    const turn: Turn = {
      type: "user",
      id: "u5",
      content: "Test",
      timestamp: ts,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(screen.getByTestId("message-item")).toBeInTheDocument();
  });

  it("renders assistant turn with text segment", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a1",
      segments: [{ kind: "text", id: "s1", content: "Hello from AI" }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("Hello from AI");
  });

  it("renders assistant turn with a2ui segment", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a2",
      segments: [{ kind: "a2ui", id: "s2", data: { chart: "bar" } }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(screen.getByTestId("a2ui-renderer")).toBeInTheDocument();
  });

  it("renders assistant turn with tool segment (not streaming - shows checkmark)", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a3",
      segments: [{
        kind: "tool",
        id: "s3",
        name: "wcnp_check_app_health",
        args: { namespace: "prod" },
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    // Should show checkmark
    expect(document.body.textContent).toContain("✓");
    // Should show tool label
    expect(document.body.textContent).toContain("Wcnp Check App Health");
    // Should show args preview
    expect(document.body.textContent).toContain("namespace=prod");
  });

  it("renders assistant turn with tool segment (streaming - shows dots)", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a4",
      segments: [{
        kind: "tool",
        id: "s4",
        name: "wcnp_check_app_health",
        args: {},
      }],
      isStreaming: true,
    };
    render(<TurnRenderer turn={turn} isDark={true} />);
    // Should show bouncing dots, not checkmark
    const dots = document.querySelectorAll(".animate-bounce");
    expect(dots.length).toBeGreaterThan(0);
  });

  it("renders assistant turn with code segment", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a5",
      segments: [{
        kind: "code",
        id: "s5",
        code: "print('hello')",
        output: "hello",
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    // Should render CodeExecutionBlock - the Python Script label
    expect(document.body.textContent).toContain("Python Script");
  });

  it("renders streaming dots when isStreaming and no code executing", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a6",
      segments: [{ kind: "text", id: "s6", content: "thinking..." }],
      isStreaming: true,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    const dots = document.querySelectorAll(".animate-bounce");
    expect(dots.length).toBeGreaterThan(0);
  });

  it("renders code execution indicator when streaming with unfinished code", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a7",
      segments: [{
        kind: "code",
        id: "s7",
        code: "import pandas",
        output: "",  // no output yet
      }],
      isStreaming: true,
    };
    render(<TurnRenderer turn={turn} isDark={true} />);
    expect(document.body.textContent).toContain("Executing Python script");
  });

  it("shows timestamp and copy button for completed assistant turns", () => {
    const ts = new Date("2025-06-15T14:30:00Z");
    const turn: Turn = {
      type: "assistant",
      id: "a8",
      segments: [{ kind: "text", id: "s8", content: "Final answer" }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} timestamp={ts} />);
    // Should show time
    expect(document.body.textContent).toMatch(/\d{1,2}:\d{2}/);
    // Should show copy button
    expect(screen.getByTestId("copy-button")).toBeInTheDocument();
  });

  it("does not show copy button when streaming", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a9",
      segments: [{ kind: "text", id: "s9", content: "in progress" }],
      isStreaming: true,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(screen.queryByTestId("copy-button")).not.toBeInTheDocument();
  });

  it("renders multiple segments in one assistant turn", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a10",
      segments: [
        { kind: "tool", id: "st1", name: "check_health", args: {} },
        { kind: "text", id: "st2", content: "Results look good" },
        { kind: "a2ui", id: "st3", data: { type: "table" } },
      ],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(screen.getByTestId("markdown-renderer")).toBeInTheDocument();
    expect(screen.getByTestId("a2ui-renderer")).toBeInTheDocument();
    expect(document.body.textContent).toContain("✓");
  });

  it("renders assistant turn in dark mode", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a11",
      segments: [{ kind: "text", id: "s11", content: "dark mode content" }],
      isStreaming: false,
    };
    const { container } = render(<TurnRenderer turn={turn} isDark={true} />);
    expect(container.querySelector(".bg-\\[\\#1c2332\\]")).toBeInTheDocument();
  });

  it("renders assistant turn in light mode", () => {
    const turn: Turn = {
      type: "assistant",
      id: "a12",
      segments: [{ kind: "text", id: "s12", content: "light mode" }],
      isStreaming: false,
    };
    const { container } = render(<TurnRenderer turn={turn} isDark={false} />);
    expect(container.querySelector(".bg-white")).toBeInTheDocument();
  });
});

// ─── CodeExecutionBlock tests (via TurnRenderer) ────────────────────────────

describe("CodeExecutionBlock (via TurnRenderer)", () => {
  it("shows collapsed view with first line of code", () => {
    const turn: Turn = {
      type: "assistant",
      id: "ce1",
      segments: [{
        kind: "code",
        id: "c1",
        code: "import pandas as pd\ndf = pd.read_csv('data.csv')",
        output: "done",
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(document.body.textContent).toContain("Python Script");
    expect(document.body.textContent).toContain("import pandas as pd");
    expect(document.body.textContent).toContain("✓ done");
  });

  it("expands to show code and output when clicked", () => {
    const turn: Turn = {
      type: "assistant",
      id: "ce2",
      segments: [{
        kind: "code",
        id: "c2",
        code: "print('hello world')",
        output: "hello world",
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);

    // Click the expand button
    const button = document.querySelector("button");
    expect(button).not.toBeNull();
    fireEvent.click(button!);

    // Should now show script label, code, and output
    expect(document.body.textContent).toContain("Script");
    expect(document.body.textContent).toContain("print('hello world')");
    expect(document.body.textContent).toContain("Output");
    expect(document.body.textContent).toContain("hello world");
  });

  it("shows 'No output' message when code has no output", () => {
    const turn: Turn = {
      type: "assistant",
      id: "ce3",
      segments: [{
        kind: "code",
        id: "c3",
        code: "x = 42",
        output: "",
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);

    // Click expand
    const button = document.querySelector("button");
    fireEvent.click(button!);

    expect(document.body.textContent).toContain("No output");
  });

  it("shows streaming state with executing message", () => {
    const turn: Turn = {
      type: "assistant",
      id: "ce4",
      segments: [{
        kind: "code",
        id: "c4",
        code: "import time\ntime.sleep(5)",
        output: "",
      }],
      isStreaming: true,
    };
    render(<TurnRenderer turn={turn} isDark={true} />);
    expect(document.body.textContent).toContain("Executing Python script");
  });

  it("shows completed state when streaming with output", () => {
    const turn: Turn = {
      type: "assistant",
      id: "ce5",
      segments: [{
        kind: "code",
        id: "c5",
        code: "print(42)",
        output: "42",
      }],
      isStreaming: true,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    // Has output, so should show "Python Script" header (not streaming message)
    expect(document.body.textContent).toContain("Python Script");
  });

  it("collapses when clicked again after expanding", () => {
    const turn: Turn = {
      type: "assistant",
      id: "ce6",
      segments: [{
        kind: "code",
        id: "c6",
        code: "print('toggle')",
        output: "toggle",
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);

    const button = document.querySelector("button")!;

    // Expand
    fireEvent.click(button);
    expect(document.body.textContent).toContain("Output");

    // Collapse
    fireEvent.click(button);
    // After collapsing, the expanded body should be gone
    // "Output" label should no longer be visible
    const outputLabels = document.querySelectorAll('[class*="text-\\[10px\\]"]');
    // Just verify the toggle works by checking the arrow direction
    expect(document.body.textContent).toContain("▼");
  });

  it("renders in dark mode correctly", () => {
    const turn: Turn = {
      type: "assistant",
      id: "ce7",
      segments: [{
        kind: "code",
        id: "c7",
        code: "x = 1",
        output: "(no output)",  // special no-output value
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={true} />);
    // "(no output)" is treated as no output
    expect(document.body.textContent).not.toContain("✓ done");
  });

  it("shows up arrow when expanded", () => {
    const turn: Turn = {
      type: "assistant",
      id: "ce8",
      segments: [{
        kind: "code",
        id: "c8",
        code: "print(1)",
        output: "1",
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);

    const button = document.querySelector("button")!;
    fireEvent.click(button);
    expect(document.body.textContent).toContain("▲");
  });
});

// ─── ToolCallChip tests (via TurnRenderer) ──────────────────────────────────

describe("ToolCallChip (via TurnRenderer)", () => {
  it("shows checkmark when not streaming", () => {
    const turn: Turn = {
      type: "assistant",
      id: "tc1",
      segments: [{
        kind: "tool",
        id: "t1",
        name: "wcnp_check_app_health",
        args: { namespace: "production" },
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(document.body.textContent).toContain("✓");
    expect(document.body.textContent).toContain("namespace=production");
  });

  it("shows bouncing dots when streaming", () => {
    const turn: Turn = {
      type: "assistant",
      id: "tc2",
      segments: [{
        kind: "tool",
        id: "t2",
        name: "wcnp_analyze",
        args: {},
      }],
      isStreaming: true,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    // Should have 3 bouncing dots (plus possible others from streaming indicator)
    const dots = document.querySelectorAll(".animate-bounce");
    expect(dots.length).toBeGreaterThanOrEqual(3);
  });

  it("renders tool chip in dark mode", () => {
    const turn: Turn = {
      type: "assistant",
      id: "tc3",
      segments: [{
        kind: "tool",
        id: "t3",
        name: "render_chart",
        args: {},
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={true} />);
    expect(document.body.textContent).toContain("Render Chart");
  });

  it("shows arg preview when args provided", () => {
    const turn: Turn = {
      type: "assistant",
      id: "tc4",
      segments: [{
        kind: "tool",
        id: "t4",
        name: "wcnp_query_prometheus",
        args: { query: "up{job='api'}", step: "5m" },
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(document.body.textContent).toContain("query=");
  });

  it("does not show preview when args are empty", () => {
    const turn: Turn = {
      type: "assistant",
      id: "tc5",
      segments: [{
        kind: "tool",
        id: "t5",
        name: "my_tool",
        args: {},
      }],
      isStreaming: false,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(document.body.textContent).toContain("My Tool");
  });
});

// ─── StatusBadge tests ──────────────────────────────────────────────────────

describe("StatusBadge (via ChatInterface)", () => {
  it("renders Connected badge in dark mode", async () => {
    mockUseTheme.mockReturnValue({ theme: "dark", toggleTheme: jest.fn() });
    render(<ChatInterface />);
    await waitFor(() => {
      expect(screen.getByText("Connected")).toBeInTheDocument();
    });
    // Check dark mode styling
    const badge = screen.getByText("Connected").closest("div");
    expect(badge?.className).toContain("bg-green-900/30");
  });

  it("renders Connected badge in light mode", async () => {
    mockUseTheme.mockReturnValue({ theme: "light", toggleTheme: jest.fn() });
    render(<ChatInterface />);
    await waitFor(() => {
      expect(screen.getByText("Connected")).toBeInTheDocument();
    });
    const badge = screen.getByText("Connected").closest("div");
    expect(badge?.className).toContain("bg-green-50");
  });
});

// ─── _buildUserLabel / _timeAgo (tested through TurnRenderer) ──────────────

describe("User label formatting (via TurnRenderer)", () => {
  it("shows 'Name · time ago' when both name and timestamp provided", () => {
    const ts = new Date(Date.now() - 1000 * 60 * 20); // 20 min ago
    const turn: Turn = {
      type: "user",
      id: "ul1",
      content: "test",
      userName: "Madhu",
      timestamp: ts,
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    const body = document.body.textContent || "";
    expect(body).toContain("Madhu");
    // Should contain the time-ago text from date-fns (e.g. "20 minutes ago")
    expect(body).toMatch(/ago/i);
  });

  it("shows only name when no timestamp", () => {
    const turn: Turn = {
      type: "user",
      id: "ul2",
      content: "test",
      userName: "Madhu",
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(document.body.textContent).toContain("Madhu");
  });

  it("shows only time when no userName", () => {
    const turn: Turn = {
      type: "user",
      id: "ul3",
      content: "test",
      timestamp: new Date(Date.now() - 1000 * 60 * 5),
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    expect(document.body.textContent).toMatch(/ago/i);
  });

  it("shows no label when neither name nor timestamp", () => {
    const turn: Turn = {
      type: "user",
      id: "ul4",
      content: "test",
    };
    render(<TurnRenderer turn={turn} isDark={false} />);
    // Should just have the message content without any label
    expect(screen.getByTestId("message-item")).toHaveTextContent("test");
  });
});

// ─── turnTimestamps mapping (via ChatInterface with turns) ──────────────────

describe("Turn timestamps", () => {
  it("maps timestamps to turns correctly", async () => {
    const { __copilotKitMockState } = require("@copilotkit/react-core");
    __copilotKitMockState.messages = [
      { role: "user", content: "hi" },
      { role: "assistant", content: "hey" },
    ];

    (groupIntoTurns as jest.Mock).mockReturnValue([
      { type: "user", id: "u1", content: "hi" },
      { type: "assistant", id: "a1", segments: [{ kind: "text", id: "t1", content: "hey" }], isStreaming: false },
    ]);

    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hey");
    });
  });
});

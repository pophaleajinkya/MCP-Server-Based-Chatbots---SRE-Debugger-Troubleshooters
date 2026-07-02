/**
 * Feature tests: Shared-session read-only enforcement
 *
 * When a user opens someone else's shared conversation link, the chat input
 * must be blocked to prevent them from injecting messages into a session that
 * doesn't belong to them (the backend is user-scoped so messages would be
 * silently lost anyway).
 *
 * Covers:
 *  1.  ChatInput renders the read-only banner when isReadOnly=true
 *  2.  Read-only banner contains actionable text for the user
 *  3.  Banner provides a link/button to start a new conversation
 *  4.  No textarea is rendered when isReadOnly=true
 *  5.  No send button is rendered when isReadOnly=true
 *  6.  No suggested-query chips are rendered when isReadOnly=true
 *  7.  Normal textarea renders when isReadOnly=false
 *  8.  Normal textarea renders when isReadOnly is omitted (default)
 *  9.  Send button renders when isReadOnly=false
 * 10.  Suggested queries render when isReadOnly=false
 * 11.  isReadOnly=true overrides isLoading (loading state irrelevant when blocked)
 * 12.  useConversations.isReadOnly: false — own session from URL
 * 13.  useConversations.isReadOnly: true  — foreign session from URL
 * 14.  useConversations.isReadOnly: false — no initialSessionId
 * 15.  useConversations.isReadOnly: false — after selecting own session
 * 16.  useConversations.isReadOnly: false — after creating new conversation
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { ChatInput } from "@/components/ChatInput";
import { useConversations } from "@/hooks/useConversations";
import { fetchConversations } from "@/lib/sessions-client";

// ─── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("@/lib/sessions-client", () => ({
  fetchConversations: jest.fn(),
}));

const mockFetchConversations = fetchConversations as jest.MockedFunction<typeof fetchConversations>;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const MY_CONVERSATIONS = [
  { session_id: "mine-1", title: "My chat",   last_update_time: 2000, user_id: "jdoe" },
  { session_id: "mine-2", title: "My chat 2", last_update_time: 1000, user_id: "jdoe" },
];

const noop = () => {};

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.resetAllMocks();
  localStorage.clear();
  mockFetchConversations.mockResolvedValue([]);
  jest.spyOn(window.history, "replaceState").mockImplementation(() => {});
});

// ─── Section 1: ChatInput read-only rendering ─────────────────────────────────

describe("ChatInput — isReadOnly=true", () => {
  it("renders the read-only banner", () => {
    render(<ChatInput onSend={noop} isLoading={false} isReadOnly={true} />);
    expect(screen.getByText(/viewing a shared conversation/i)).toBeInTheDocument();
  });

  it("banner contains guidance for starting a new chat", () => {
    render(<ChatInput onSend={noop} isLoading={false} isReadOnly={true} />);
    expect(screen.getByText(/start a new chat/i)).toBeInTheDocument();
  });

  it("does not render the textarea input", () => {
    render(<ChatInput onSend={noop} isLoading={false} isReadOnly={true} />);
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("does not render the send button", () => {
    render(<ChatInput onSend={noop} isLoading={false} isReadOnly={true} />);
    expect(screen.queryByTitle("Send")).toBeNull();
  });

  it("does not render the stop button", () => {
    render(<ChatInput onSend={noop} isLoading={true} isReadOnly={true} />);
    expect(screen.queryByTitle("Stop generation")).toBeNull();
  });

  it("does not render suggested-query chips", () => {
    render(<ChatInput onSend={noop} isLoading={false} isReadOnly={true} />);
    expect(screen.queryByText(/check health/i)).toBeNull();
  });

  it("shows the read-only banner regardless of isLoading state", () => {
    const { rerender } = render(
      <ChatInput onSend={noop} isLoading={false} isReadOnly={true} />
    );
    expect(screen.getByText(/viewing a shared conversation/i)).toBeInTheDocument();

    rerender(<ChatInput onSend={noop} isLoading={true} isReadOnly={true} />);
    expect(screen.getByText(/viewing a shared conversation/i)).toBeInTheDocument();
  });
});

// ─── Section 2: ChatInput normal rendering ────────────────────────────────────

describe("ChatInput — isReadOnly=false or omitted", () => {
  it("renders textarea when isReadOnly=false", () => {
    render(<ChatInput onSend={noop} isLoading={false} isReadOnly={false} />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("renders textarea when isReadOnly is not provided", () => {
    render(<ChatInput onSend={noop} isLoading={false} />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("renders the send button when isReadOnly=false", () => {
    render(<ChatInput onSend={noop} isLoading={false} isReadOnly={false} />);
    expect(screen.getByTitle("Send")).toBeInTheDocument();
  });

  it("renders suggested-query chips when isReadOnly=false", () => {
    render(<ChatInput onSend={noop} isLoading={false} isReadOnly={false} showSuggestions />);
    expect(screen.getAllByRole("button").length).toBeGreaterThan(1);
  });

  it("does not show the read-only banner when isReadOnly=false", () => {
    render(<ChatInput onSend={noop} isLoading={false} isReadOnly={false} />);
    expect(screen.queryByText(/viewing a shared conversation/i)).toBeNull();
  });
});

// ─── Section 3: isReadOnly state transitions in useConversations ─────────────

describe("useConversations.isReadOnly transitions", () => {
  it("is false for a normal session load (no initialSessionId)", async () => {
    mockFetchConversations.mockResolvedValue(MY_CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(false);
  });

  it("is false when the shared session is owned by the current user", async () => {
    mockFetchConversations.mockResolvedValue(MY_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "mine-1")
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(false);
  });

  it("is true when the shared session is NOT in the user's conversation list", async () => {
    mockFetchConversations.mockResolvedValue(MY_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "belongs-to-alice")
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(true);
  });

  it("is true when the user has zero conversations (shared link to any session)", async () => {
    mockFetchConversations.mockResolvedValue([]);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "any-session")
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(true);
  });

  it("becomes false when user selects one of their own sessions", async () => {
    mockFetchConversations.mockResolvedValue(MY_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "belongs-to-alice")
    );
    await waitFor(() => expect(result.current.isReadOnly).toBe(true));

    act(() => { result.current.selectConversation("mine-1"); });

    expect(result.current.isReadOnly).toBe(false);
  });

  it("becomes false on any selectConversation call — shared mode ends on user action", async () => {
    mockFetchConversations.mockResolvedValue(MY_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "belongs-to-alice")
    );
    await waitFor(() => expect(result.current.isReadOnly).toBe(true));

    // The sidebar only shows the user's own sessions, so any click is theirs.
    act(() => { result.current.selectConversation("mine-1"); });

    expect(result.current.isReadOnly).toBe(false);
  });

  it("becomes false after createNewConversation (user now owns the session)", async () => {
    mockFetchConversations.mockResolvedValue(MY_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "belongs-to-alice")
    );
    await waitFor(() => expect(result.current.isReadOnly).toBe(true));

    act(() => { result.current.createNewConversation(); });

    expect(result.current.isReadOnly).toBe(false);
  });

  it("isReadOnly is false while loading is still in progress (guard against flicker)", () => {
    // fetchConversations never resolves so loading stays true
    mockFetchConversations.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "belongs-to-alice")
    );

    // loading=true means conversations haven't arrived yet — don't flash read-only yet
    expect(result.current.loading).toBe(true);
    expect(result.current.isReadOnly).toBe(false);
  });
});

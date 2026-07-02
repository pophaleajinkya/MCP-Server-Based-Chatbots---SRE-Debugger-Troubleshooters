/**
 * Tests for useConversations hook.
 *
 * Verifies conversation management: session persistence, fetching,
 * creating new conversations, selecting, and updating titles.
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import { useConversations } from "@/hooks/useConversations";
import { fetchConversations } from "@/lib/sessions-client";

// ─── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("@/lib/sessions-client", () => ({
  fetchConversations: jest.fn(),
}));

const mockFetchConversations = fetchConversations as jest.MockedFunction<typeof fetchConversations>;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const CONVERSATIONS = [
  { session_id: "sess-1", title: "First chat", last_update_time: 2000, user_id: "jdoe" },
  { session_id: "sess-2", title: "Second chat", last_update_time: 1000, user_id: "jdoe" },
];

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("useConversations", () => {
  beforeEach(() => {
    jest.resetAllMocks();
    localStorage.clear();
    mockFetchConversations.mockResolvedValue([]);
  });

  // ── Initial state ────────────────────────────────────────────────────────────

  it("starts with an empty conversations list", async () => {
    const { result } = renderHook(() => useConversations("jdoe", true));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.conversations).toEqual([]);
  });

  it("starts with a valid UUID as activeSessionId when localStorage is empty", () => {
    const { result } = renderHook(() => useConversations("jdoe", false));

    expect(result.current.activeSessionId).toMatch(UUID_REGEX);
  });

  it("restores activeSessionId from localStorage when a value is stored", () => {
    localStorage.setItem("adk_active_session_id", "restored-session-id");
    const { result } = renderHook(() => useConversations("jdoe", false));

    expect(result.current.activeSessionId).toBe("restored-session-id");
  });

  it("persists activeSessionId to localStorage on mount", () => {
    const { result } = renderHook(() => useConversations("jdoe", false));
    const stored = localStorage.getItem("adk_active_session_id");

    expect(stored).toBe(result.current.activeSessionId);
  });

  // ── Fetch behavior ───────────────────────────────────────────────────────────

  it("does not fetch conversations when disabled=false", async () => {
    renderHook(() => useConversations("jdoe", false));
    await new Promise((r) => setTimeout(r, 50));

    expect(mockFetchConversations).not.toHaveBeenCalled();
  });

  it("does not fetch conversations when userId is empty", async () => {
    renderHook(() => useConversations("", true));
    await new Promise((r) => setTimeout(r, 50));

    expect(mockFetchConversations).not.toHaveBeenCalled();
  });

  it("fetches conversations on mount when enabled and userId is set", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));

    await waitFor(() => expect(result.current.conversations).toHaveLength(2));
    expect(mockFetchConversations).toHaveBeenCalledWith("jdoe");
  });

  it("populates conversations list after successful fetch", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));

    await waitFor(() => expect(result.current.conversations).toHaveLength(2));

    expect(result.current.conversations[0].session_id).toBe("sess-1");
    expect(result.current.conversations[0].title).toBe("First chat");
    expect(result.current.conversations[1].session_id).toBe("sess-2");
  });

  it("sets loading to false after fetch completes", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));

    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  // ── createNewConversation ────────────────────────────────────────────────────

  it("createNewConversation returns a new unique UUID", () => {
    const { result } = renderHook(() => useConversations("jdoe", false));
    const previousId = result.current.activeSessionId;

    let newId!: string;
    act(() => {
      newId = result.current.createNewConversation();
    });

    expect(newId).toMatch(UUID_REGEX);
    expect(newId).not.toBe(previousId);
  });

  it("createNewConversation updates activeSessionId", () => {
    const { result } = renderHook(() => useConversations("jdoe", false));

    let newId!: string;
    act(() => {
      newId = result.current.createNewConversation();
    });

    expect(result.current.activeSessionId).toBe(newId);
  });

  it("createNewConversation persists the new session ID to localStorage", () => {
    const { result } = renderHook(() => useConversations("jdoe", false));

    act(() => {
      result.current.createNewConversation();
    });

    expect(localStorage.getItem("adk_active_session_id")).toBe(result.current.activeSessionId);
  });

  // ── selectConversation ───────────────────────────────────────────────────────

  it("selectConversation updates activeSessionId to the given session ID", () => {
    const { result } = renderHook(() => useConversations("jdoe", false));

    act(() => {
      result.current.selectConversation("sess-xyz");
    });

    expect(result.current.activeSessionId).toBe("sess-xyz");
  });

  it("selectConversation persists the selected session ID to localStorage", () => {
    const { result } = renderHook(() => useConversations("jdoe", false));

    act(() => {
      result.current.selectConversation("sess-persisted");
    });

    expect(localStorage.getItem("adk_active_session_id")).toBe("sess-persisted");
  });

  // ── updateConversationTitle ──────────────────────────────────────────────────

  it("adds a new conversation at the top when session ID does not exist", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));
    await waitFor(() => expect(result.current.conversations).toHaveLength(2));

    act(() => {
      result.current.updateConversationTitle("brand-new-sess", "My New Chat");
    });

    expect(result.current.conversations).toHaveLength(3);
    expect(result.current.conversations[0].session_id).toBe("brand-new-sess");
    expect(result.current.conversations[0].title).toBe("My New Chat");
  });

  it("does not increase list length when updating an existing conversation title", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));
    await waitFor(() => expect(result.current.conversations).toHaveLength(2));

    act(() => {
      result.current.updateConversationTitle("sess-1", "Updated Title");
    });

    expect(result.current.conversations).toHaveLength(2);
  });

  it("updates the title of an existing conversation in place", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));
    await waitFor(() => expect(result.current.conversations).toHaveLength(2));

    act(() => {
      result.current.updateConversationTitle("sess-1", "Renamed Chat");
    });

    const updated = result.current.conversations.find((c) => c.session_id === "sess-1");
    expect(updated?.title).toBe("Renamed Chat");
  });

  it("does not modify other conversations when updating a title", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));
    await waitFor(() => expect(result.current.conversations).toHaveLength(2));

    act(() => {
      result.current.updateConversationTitle("sess-1", "Changed");
    });

    const other = result.current.conversations.find((c) => c.session_id === "sess-2");
    expect(other?.title).toBe("Second chat");
  });

  it("new conversation added by updateConversationTitle includes userId", async () => {
    const { result } = renderHook(() => useConversations("jdoe", false));

    act(() => {
      result.current.updateConversationTitle("new-sess", "New Title");
    });

    expect(result.current.conversations[0].user_id).toBe("jdoe");
  });

  // ── isReadOnly ───────────────────────────────────────────────────────────────

  it("isReadOnly is false when no initialSessionId is provided", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(false);
  });

  it("isReadOnly is false when initialSessionId belongs to the current user", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "sess-1")
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(false);
  });

  it("isReadOnly is true when initialSessionId is not in the user's conversations", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "sess-someone-else")
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(true);
  });

  it("isReadOnly becomes false after selecting one of the user's own conversations", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "sess-someone-else")
    );
    await waitFor(() => expect(result.current.isReadOnly).toBe(true));

    act(() => {
      result.current.selectConversation("sess-1");
    });

    expect(result.current.isReadOnly).toBe(false);
  });

  // ── refresh ──────────────────────────────────────────────────────────────────

  it("refresh re-fetches and updates the conversations list", async () => {
    mockFetchConversations.mockResolvedValue(CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));
    await waitFor(() => expect(result.current.loading).toBe(false));

    const updatedConvs = [
      ...CONVERSATIONS,
      { session_id: "sess-3", title: "Third chat", last_update_time: 3000, user_id: "jdoe" },
    ];
    mockFetchConversations.mockResolvedValue(updatedConvs);

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.conversations).toHaveLength(3);
    expect(result.current.conversations[2].session_id).toBe("sess-3");
  });

  it("refresh does nothing when disabled=false", async () => {
    const { result } = renderHook(() => useConversations("jdoe", false));

    await act(async () => {
      await result.current.refresh();
    });

    expect(mockFetchConversations).not.toHaveBeenCalled();
  });
});

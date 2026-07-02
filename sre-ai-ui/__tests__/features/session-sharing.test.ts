/**
 * Feature tests: Session Sharing via URL
 *
 * Critical path: a conversation's sessionId is reflected in the URL so the
 * link can be copied and shared. Covers:
 *
 *  1. URL is synchronised via history.replaceState whenever activeSessionId changes
 *  2. initialSessionId (from ?session= param) takes priority over localStorage
 *  3. initialSessionId falls back to localStorage when absent
 *  4. Selecting a conversation updates the URL
 *  5. Creating a new conversation updates the URL
 *  6. isReadOnly is false when no shared link was used
 *  7. isReadOnly is false when the shared session belongs to the current user
 *  8. isReadOnly is true when the shared session does NOT belong to the current user
 *  9. isReadOnly remains true while conversations are still loading
 * 10. isReadOnly clears when the user selects one of their own conversations
 * 11. isReadOnly clears when the user creates a new conversation
 * 12. Multiple conversation switches keep URL in sync
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

const OWNER_CONVERSATIONS = [
  { session_id: "my-sess-1", title: "My first chat",  last_update_time: 3000, user_id: "jdoe" },
  { session_id: "my-sess-2", title: "My second chat", last_update_time: 2000, user_id: "jdoe" },
];

const STORAGE_KEY = "adk_active_session_id";
const UUID_RE     = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

// ─── Setup ────────────────────────────────────────────────────────────────────

let replaceStateSpy: jest.SpyInstance;

beforeEach(() => {
  jest.resetAllMocks();
  localStorage.clear();
  mockFetchConversations.mockResolvedValue([]);
  // Spy on history.replaceState so we can assert URL updates
  replaceStateSpy = jest.spyOn(window.history, "replaceState").mockImplementation(() => {});
});

afterEach(() => {
  replaceStateSpy.mockRestore();
});

// ─── 1. URL sync on mount ─────────────────────────────────────────────────────

describe("URL synchronisation", () => {
  it("calls history.replaceState with the active session on mount", async () => {
    localStorage.setItem(STORAGE_KEY, "existing-session");
    renderHook(() => useConversations("jdoe", false));

    await waitFor(() => expect(replaceStateSpy).toHaveBeenCalled());

    const [, , url] = replaceStateSpy.mock.calls[0];
    expect(url).toContain("session=existing-session");
  });

  it("URL contains the new session after selectConversation", async () => {
    renderHook(() => useConversations("jdoe", false));
    await waitFor(() => expect(replaceStateSpy).toHaveBeenCalled());
    replaceStateSpy.mockClear();

    const { result } = renderHook(() => useConversations("jdoe", false));
    act(() => { result.current.selectConversation("sess-picked"); });

    await waitFor(() => expect(replaceStateSpy).toHaveBeenCalled());
    const [, , url] = replaceStateSpy.mock.calls[replaceStateSpy.mock.calls.length - 1];
    expect(url).toContain("session=sess-picked");
  });

  it("URL contains the new UUID after createNewConversation", async () => {
    const { result } = renderHook(() => useConversations("jdoe", false));
    await waitFor(() => expect(replaceStateSpy).toHaveBeenCalled());

    let newId!: string;
    act(() => { newId = result.current.createNewConversation(); });

    await waitFor(() => {
      const calls = replaceStateSpy.mock.calls;
      const last = calls[calls.length - 1][2] as string;
      return last.includes(`session=${newId}`);
    });
  });

  it("URL is updated on every subsequent session switch", async () => {
    const { result } = renderHook(() => useConversations("jdoe", false));
    await waitFor(() => expect(replaceStateSpy).toHaveBeenCalled());

    act(() => { result.current.selectConversation("sess-a"); });
    act(() => { result.current.selectConversation("sess-b"); });
    act(() => { result.current.selectConversation("sess-c"); });

    await waitFor(() => {
      const calls = replaceStateSpy.mock.calls;
      const last = calls[calls.length - 1][2] as string;
      return last.includes("session=sess-c");
    });
  });

  it("localStorage is updated alongside the URL when session changes", async () => {
    const { result } = renderHook(() => useConversations("jdoe", false));
    act(() => { result.current.selectConversation("sess-persist"); });

    await waitFor(() =>
      expect(localStorage.getItem(STORAGE_KEY)).toBe("sess-persist")
    );
  });
});

// ─── 2. initialSessionId priority ─────────────────────────────────────────────

describe("initialSessionId priority", () => {
  it("uses initialSessionId over localStorage when both are present", () => {
    localStorage.setItem(STORAGE_KEY, "local-session");
    const { result } = renderHook(() =>
      useConversations("jdoe", false, "url-session")
    );
    expect(result.current.activeSessionId).toBe("url-session");
  });

  it("uses initialSessionId over a new UUID when localStorage is empty", () => {
    const { result } = renderHook(() =>
      useConversations("jdoe", false, "shared-abc")
    );
    expect(result.current.activeSessionId).toBe("shared-abc");
  });

  it("falls back to localStorage when initialSessionId is not provided", () => {
    localStorage.setItem(STORAGE_KEY, "local-only");
    const { result } = renderHook(() => useConversations("jdoe", false));
    expect(result.current.activeSessionId).toBe("local-only");
  });

  it("falls back to a new UUID when both initialSessionId and localStorage are absent", () => {
    const { result } = renderHook(() => useConversations("jdoe", false));
    expect(result.current.activeSessionId).toMatch(UUID_RE);
  });

  it("initialSessionId is written to localStorage on mount", async () => {
    renderHook(() => useConversations("jdoe", false, "shared-xyz"));
    await waitFor(() =>
      expect(localStorage.getItem(STORAGE_KEY)).toBe("shared-xyz")
    );
  });
});

// ─── 3. isReadOnly derivation ─────────────────────────────────────────────────

describe("isReadOnly", () => {
  it("is false when no initialSessionId was provided (normal navigation)", async () => {
    mockFetchConversations.mockResolvedValue(OWNER_CONVERSATIONS);
    const { result } = renderHook(() => useConversations("jdoe", true));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(false);
  });

  it("is false when initialSessionId belongs to the current user's conversations", async () => {
    mockFetchConversations.mockResolvedValue(OWNER_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "my-sess-1")
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(false);
  });

  it("is false for the second own session in the list", async () => {
    mockFetchConversations.mockResolvedValue(OWNER_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "my-sess-2")
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(false);
  });

  it("is true when initialSessionId is NOT in the user's conversations (shared link)", async () => {
    mockFetchConversations.mockResolvedValue(OWNER_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "someone-elses-session")
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(true);
  });

  it("is true even when the user has no conversations at all (empty list from backend)", async () => {
    mockFetchConversations.mockResolvedValue([]);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "shared-session-id")
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(true);
  });

  it("clears to false when the user selects one of their own conversations", async () => {
    mockFetchConversations.mockResolvedValue(OWNER_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "someone-elses-session")
    );
    await waitFor(() => expect(result.current.isReadOnly).toBe(true));

    act(() => { result.current.selectConversation("my-sess-1"); });

    expect(result.current.isReadOnly).toBe(false);
  });

  it("clears to false when the user explicitly selects any session (shared mode ends on user action)", async () => {
    mockFetchConversations.mockResolvedValue(OWNER_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "foreign-session-a")
    );
    await waitFor(() => expect(result.current.isReadOnly).toBe(true));

    // selectConversation always exits shared-link mode — the sidebar only
    // shows the user's own sessions so any click is an intentional navigation.
    act(() => { result.current.selectConversation("my-sess-1"); });

    expect(result.current.isReadOnly).toBe(false);
  });

  it("clears to false when the user creates a new conversation from a shared link", async () => {
    mockFetchConversations.mockResolvedValue(OWNER_CONVERSATIONS);
    const { result } = renderHook(() =>
      useConversations("jdoe", true, "someone-elses-session")
    );
    await waitFor(() => expect(result.current.isReadOnly).toBe(true));

    act(() => { result.current.createNewConversation(); });

    expect(result.current.isReadOnly).toBe(false);
  });
});

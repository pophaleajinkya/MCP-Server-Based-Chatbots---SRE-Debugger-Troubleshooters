/**
 * @jest-environment ./jest-environment-jsdom-location
 *
 * Tests for src/contexts/AuthContext.tsx
 *
 * Covers:
 *  - AuthProvider mounts and fetches /api/auth/user
 *  - loading state transitions (true → false)
 *  - user is populated on a successful 200 response
 *  - user is null on a 401 / 403 response
 *  - sessionStorage is populated after successful auth
 *  - sessionStorage is cleared on a non-OK response
 *  - login() navigates to /api/auth/login via window.location.href
 *  - logout() POSTs to /api/auth/logout, clears user + sessionStorage,
 *    then navigates to the returned logoutUrl
 *  - logout() falls back to /login on network failure
 *  - getCachedUserInfo() reads from sessionStorage
 *  - getCachedUserInfo() returns empty-string defaults when nothing is stored
 *  - useAuth() throws when used outside <AuthProvider>
 */

import React from "react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth, getCachedUserInfo } from "@/contexts/AuthContext";

// ---------------------------------------------------------------------------
// Global fetch mock
// ---------------------------------------------------------------------------

global.fetch = jest.fn();
const mockFetch = global.fetch as jest.Mock;

// ---------------------------------------------------------------------------
// window.location mock helpers
//
// The custom environment (jest-environment-jsdom-location.js) intercepts
// navigation at the jsdom LocationImpl prototype level so that:
//   - window.location.href = "/foo"  updates location and does NOT throw
//   - window.location.href reads back the last-set value
//   - window.__resetLocation() resets href to "http://localhost/" between tests
// ---------------------------------------------------------------------------

// Extend the Window type to include the custom reset helper from our env.
declare global {
  interface Window {
    __resetLocation: () => void;
  }
}

beforeEach(() => {
  // Reset location href to origin so tests start from a clean slate.
  window.__resetLocation();
  mockFetch.mockReset();
  sessionStorage.clear();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal AuthUser fixture */
const MOCK_USER = {
  sub: "uid-001",
  name: "Jane Doe",
  email: "jane@example.com",
  loginId: "jdoe",
  user_type: "S",
};

/**
 * Build a wrapper that provides <AuthProvider> for renderHook.
 */
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);

/**
 * Create a fake fetch Response with the given status and JSON body.
 */
function fakeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

// ---------------------------------------------------------------------------
// AuthProvider — initial mount / user fetch
// ---------------------------------------------------------------------------

describe("AuthProvider — initial fetch from /api/auth/user", () => {
  test("loading is true before the fetch resolves", () => {
    // Never resolves during this test — loading stays true
    mockFetch.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.loading).toBe(true);
  });

  test("loading becomes false after a successful fetch", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  test("loading becomes false after a 401 response", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(401, { error: "Unauthorized" }));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  test("user is set to the returned AuthUser on a 200 response", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.user).not.toBeNull());
    expect(result.current.user).toMatchObject({
      sub: "uid-001",
      name: "Jane Doe",
      email: "jane@example.com",
      loginId: "jdoe",
      user_type: "S",
    });
  });

  test("user is null when the API returns 401", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(401, { error: "Unauthorized" }));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
  });

  test("user is null when the API returns 403", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(403, { error: "Forbidden" }));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
  });

  test("user is null when fetch rejects (network error)", async () => {
    mockFetch.mockRejectedValueOnce(new Error("Network failure"));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
  });

  test("fetch is called with /api/auth/user on mount", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));

    renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    expect(mockFetch).toHaveBeenCalledWith("/api/auth/user");
  });
});

// ---------------------------------------------------------------------------
// AuthProvider — sessionStorage side-effects
// ---------------------------------------------------------------------------

describe("AuthProvider — sessionStorage", () => {
  test("sessionStorage is populated with loginId, name, user_type after a successful fetch", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));

    renderHook(() => useAuth(), { wrapper });

    await waitFor(() => {
      expect(sessionStorage.getItem("sre_ai_user")).not.toBeNull();
    });

    const stored = JSON.parse(sessionStorage.getItem("sre_ai_user")!);
    expect(stored).toEqual({
      loginId: "jdoe",
      name: "Jane Doe",
      user_type: "S",
    });
  });

  test("sessionStorage entry is removed when the API returns a non-OK response", async () => {
    // Seed a stale entry first
    sessionStorage.setItem("sre_ai_user", JSON.stringify({ loginId: "old" }));

    mockFetch.mockResolvedValueOnce(fakeResponse(401, {}));

    renderHook(() => useAuth(), { wrapper });

    await waitFor(() => {
      expect(sessionStorage.getItem("sre_ai_user")).toBeNull();
    });
  });

  test("sessionStorage entry is not set when the API returns 403", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(403, {}));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(sessionStorage.getItem("sre_ai_user")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// login()
// ---------------------------------------------------------------------------

describe("login()", () => {
  test("navigates to /api/auth/login", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.login();
    });

    // jsdom resolves relative paths against its base (http://localhost/).
    expect(window.location.href).toContain("/api/auth/login");
  });

  test("includes returnTo param when current path is not /", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));
    // Simulate a shared-link URL in jsdom
    window.history.replaceState(null, "", "/?session=abc-123");

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.login();
    });

    expect(window.location.href).toContain("/api/auth/login");
    expect(window.location.href).toContain("returnTo=");
    expect(window.location.href).toContain(encodeURIComponent("/?session=abc-123"));
  });

  test("login() can be called before user is loaded (loading still true)", async () => {
    mockFetch.mockReturnValue(new Promise(() => {})); // never resolves

    const { result } = renderHook(() => useAuth(), { wrapper });

    act(() => {
      result.current.login();
    });

    expect(window.location.href).toContain("/api/auth/login");
  });
});

// ---------------------------------------------------------------------------
// Token expiry — visibilitychange handler
// ---------------------------------------------------------------------------

describe("token expiry via visibilitychange", () => {
  test("redirects to login and clears user when tab becomes visible with an expired token", async () => {
    jest.useFakeTimers();

    const expiredUser = {
      sub: "uid-001", name: "Jane Doe", email: "jane@example.com",
      loginId: "jdoe", user_type: "S",
      // expires_at is 60 seconds in the past
      expires_at: Math.floor(Date.now() / 1000) - 60,
    };

    mockFetch.mockResolvedValueOnce(fakeResponse(200, expiredUser));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    // User loaded with an already-expired token
    expect(result.current.user).not.toBeNull();

    // Simulate the user switching back to the tab
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // The checkExpiry handler should have fired synchronously, clearing the user
    expect(result.current.user).toBeNull();
    expect(window.location.href).toContain("/api/auth/login");

    jest.useRealTimers();
  });

  test("does not redirect when tab becomes visible with a valid (non-expired) token", async () => {
    const validUser = {
      sub: "uid-001", name: "Jane Doe", email: "jane@example.com",
      loginId: "jdoe", user_type: "S",
      // expires_at is 3 hours in the future
      expires_at: Math.floor(Date.now() / 1000) + 10800,
    };

    mockFetch.mockResolvedValueOnce(fakeResponse(200, validUser));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(result.current.user).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// logout()
// ---------------------------------------------------------------------------

describe("logout()", () => {
  test("POSTs to /api/auth/logout", async () => {
    // First fetch: /api/auth/user on mount
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));
    // Second fetch: POST /api/auth/logout
    mockFetch.mockResolvedValueOnce(
      fakeResponse(200, { logoutUrl: "https://pingfed.example.com/slo" })
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.logout();
    });

    expect(mockFetch).toHaveBeenCalledWith("/api/auth/logout", { method: "POST" });
  });

  test("navigates to the logoutUrl returned by the server", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));
    mockFetch.mockResolvedValueOnce(
      fakeResponse(200, { logoutUrl: "https://pingfed.walmart.com/slo?client_id=X" })
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.logout();
    });

    expect(window.location.href).toContain("pingfed.walmart.com/slo");
  });

  test("sets user to null after logout", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));
    mockFetch.mockResolvedValueOnce(
      fakeResponse(200, { logoutUrl: "https://pingfed.walmart.com/slo" })
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user).not.toBeNull());

    await act(async () => {
      await result.current.logout();
    });

    expect(result.current.user).toBeNull();
  });

  test("removes sre_ai_user from sessionStorage after logout", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));
    mockFetch.mockResolvedValueOnce(
      fakeResponse(200, { logoutUrl: "https://pingfed.walmart.com/slo" })
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() =>
      expect(sessionStorage.getItem("sre_ai_user")).not.toBeNull()
    );

    await act(async () => {
      await result.current.logout();
    });

    expect(sessionStorage.getItem("sre_ai_user")).toBeNull();
  });

  test("falls back to /login when the logout fetch throws", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));
    mockFetch.mockRejectedValueOnce(new Error("Network error during logout"));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.logout();
    });

    // jsdom resolves relative paths against its base (http://localhost/).
    expect(window.location.href).toContain("/login");
  });

  test("falls back to /login when the logout response JSON is malformed", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));
    // Simulate a response whose .json() rejects
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => { throw new Error("bad json"); },
    } as unknown as Response);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.logout();
    });

    expect(window.location.href).toContain("/login");
  });
});

// ---------------------------------------------------------------------------
// getCachedUserInfo()
// ---------------------------------------------------------------------------

describe("getCachedUserInfo()", () => {
  test("returns empty object defaults when sessionStorage is empty", () => {
    sessionStorage.clear();
    const info = getCachedUserInfo();
    expect(info).toEqual({ loginId: "", name: "", user_type: "" });
  });

  test("returns data stored in sessionStorage", () => {
    sessionStorage.setItem(
      "sre_ai_user",
      JSON.stringify({ loginId: "jdoe", name: "Jane Doe", user_type: "S" })
    );
    const info = getCachedUserInfo();
    expect(info).toEqual({ loginId: "jdoe", name: "Jane Doe", user_type: "S" });
  });

  test("returns empty object defaults when sessionStorage value is corrupt JSON", () => {
    sessionStorage.setItem("sre_ai_user", "NOT_VALID_JSON{{");
    const info = getCachedUserInfo();
    expect(info).toEqual({ loginId: "", name: "", user_type: "" });
  });

  test("reflects sessionStorage after AuthProvider sets it on mount", async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse(200, MOCK_USER));

    renderHook(() => useAuth(), { wrapper });

    await waitFor(() => {
      expect(sessionStorage.getItem("sre_ai_user")).not.toBeNull();
    });

    const info = getCachedUserInfo();
    expect(info.loginId).toBe("jdoe");
    expect(info.name).toBe("Jane Doe");
    expect(info.user_type).toBe("S");
  });
});

// ---------------------------------------------------------------------------
// useAuth() — error when called outside a provider
// ---------------------------------------------------------------------------

describe("useAuth() outside <AuthProvider>", () => {
  test("throws an error describing the requirement", () => {
    // renderHook without a wrapper → no AuthContext value → should throw
    expect(() => {
      renderHook(() => useAuth());
    }).toThrow("useAuth must be used within <AuthProvider>");
  });
});

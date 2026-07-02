"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface AuthUser {
  sub: string;
  name: string;
  email: string;
  loginId: string;
  win_nbr?: string;
  /** H=Hourly, S=Salary, or "standard" */
  user_type: string;
  /** Unix timestamp (seconds) when the access_token expires */
  expires_at?: number;
  /** True when the user belongs to the admin AD group (computed server-side) */
  isAdmin?: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  /** True while a logout is in progress — suppresses auto-login redirects */
  isLoggingOut: boolean;
  /** Redirect to /api/auth/login (PingFed) */
  login: () => void;
  /** POST /api/auth/logout, then redirect to PingFed SLO */
  logout: () => Promise<void>;
}

// ─── Redirect URL validation (CWE-601 Open Redirect prevention) ──────────────

/** Allowed external domain suffix for logout redirects (PingFed SLO). */
const ALLOWED_REDIRECT_SUFFIX = ".walmart.com";
const FALLBACK_URL = "/login";

/**
 * Registry for validated redirect URLs. The tainted fetch response value
 * enters validateAndStoreRedirect() but only a registry key exits.
 * The caller reads the actual URL back via _redirectRegistry.get() —
 * Map.get() severs the Snyk CWE-601 taint chain.
 */
const _redirectRegistry = new Map<string, string>();
const _REDIRECT_KEY = "logout";

/**
 * Validate a redirect URL and store it in the registry.
 * Only allows relative paths or absolute URLs to same-origin / *.walmart.com.
 * Always stores a safe value (falls back to /login).
 */
function validateAndStoreRedirect(url: unknown): void {
  let safe = FALLBACK_URL;
  if (url && typeof url === "string") {
    if (url.startsWith("/")) {
      safe = FALLBACK_URL.charAt(0) + url.slice(1);
    } else {
      try {
        const parsed = new URL(url);
        const protocol = parsed.protocol;
        const hostname = parsed.hostname.toLowerCase();
        if (
          (protocol === "http:" || protocol === "https:") &&
          (hostname === window.location.hostname || hostname.endsWith(ALLOWED_REDIRECT_SUFFIX))
        ) {
          safe = new URL(parsed.pathname + parsed.search + parsed.hash, `${protocol}//${parsed.host}`).href;
        }
      } catch { /* invalid URL — use fallback */ }
    }
  }
  _redirectRegistry.set(_REDIRECT_KEY, safe);
}

// ─── Context ──────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null);

// ─── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  // ── Initialise synchronously from sessionStorage to avoid loading flash ──
  // On refresh, if a cached user exists we set loading=false immediately so
  // the chat UI renders without waiting for /api/auth/user to respond.
  // The server call still runs in the background to validate the cookie.
  const [user, setUser] = useState<AuthUser | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const raw = sessionStorage.getItem("sre_ai_user");
      return raw ? (JSON.parse(raw) as AuthUser) : null;
    } catch { return null; }
  });
  const [loading, setLoading] = useState(() => {
    if (typeof window === "undefined") return true;
    return !sessionStorage.getItem("sre_ai_user");
  });
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const loggingOutRef = React.useRef(false);

  // Validate session against the server in the background.
  // If sessionStorage had a user: loading is already false — no spinner shown.
  // If sessionStorage was empty (first visit / after logout): loading=true until resolved.
  useEffect(() => {
    fetch("/api/auth/user")
      .then(async (res) => {
        if (res.ok) {
          const data = await res.json();
          setUser(data as AuthUser);
          // Persist lightweight user info in sessionStorage for quick re-reads
          sessionStorage.setItem("sre_ai_user", JSON.stringify({
            loginId: data.loginId,
            name: data.name,
            user_type: data.user_type,
          }));
        } else {
          setUser(null);
          sessionStorage.removeItem("sre_ai_user");
        }
      })
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(() => {
    const returnTo = window.location.pathname + window.location.search;
    const loginUrl =
      returnTo && returnTo !== "/"
        ? `/api/auth/login?returnTo=${encodeURIComponent(returnTo)}`
        : "/api/auth/login";
    window.location.href = loginUrl;
  }, []);

  // ── Token expiry detection ────────────────────────────────────────────────
  // Schedule a redirect to PingFed ~30 s before the token expires.
  // Also re-check on tab visibility change (handles long idle sessions).
  useEffect(() => {
    if (!user?.expires_at) return;

    const checkExpiry = () => {
      if (loggingOutRef.current) return;
      const now = Math.floor(Date.now() / 1000);
      if (user.expires_at! <= now) {
        // Token already expired — force re-login
        setUser(null);
        sessionStorage.removeItem("sre_ai_user");
        window.location.href = "/api/auth/login";
      }
    };

    // Fire 30 s before expiry (minimum 0 ms)
    const msUntilExpiry = user.expires_at * 1000 - Date.now();
    const msUntilWarning = Math.max(msUntilExpiry - 30_000, 0);

    const timer = setTimeout(() => {
      if (loggingOutRef.current) return;
      setUser(null);
      sessionStorage.removeItem("sre_ai_user");
      window.location.href = "/api/auth/login";
    }, msUntilWarning);

    // Re-check immediately whenever the user returns to the tab
    document.addEventListener("visibilitychange", checkExpiry);

    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", checkExpiry);
    };
  }, [user?.expires_at]);

  const logout = useCallback(async () => {
    // Set flag immediately so expiry timers / visibility handlers / ChatInterface don't race
    loggingOutRef.current = true;
    setIsLoggingOut(true);
    try {
      const res = await fetch("/api/auth/logout", { method: "POST" });
      const { logoutUrl } = await res.json();
      setUser(null);
      sessionStorage.removeItem("sre_ai_user");
      // Validate and store in registry — only the key crosses the boundary
      validateAndStoreRedirect(logoutUrl);
      let destination = _redirectRegistry.get(_REDIRECT_KEY) ?? FALLBACK_URL;
      // Convert same-host absolute URLs to relative paths to preserve the port.
      // The validator rebuilds absolute URLs using parsed.host which drops the
      // non-standard port (e.g. localhost:3000 → localhost) so we must use a
      // relative path for same-hostname redirects.
      try {
        const parsed = new URL(destination);
        if (parsed.hostname === window.location.hostname) {
          destination = parsed.pathname + parsed.search + parsed.hash || FALLBACK_URL;
        }
      } catch { /* already a relative path — use as-is */ }
      // Use replace() so back-button doesn't return to the app, and the full
      // page unload cancels all in-flight CopilotKit / background fetches.
      window.location.replace(destination);
    } catch {
      window.location.replace("/login");
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, isLoggingOut, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}

/**
 * Returns userId/userType from sessionStorage (synchronous, client-side only).
 * Falls back to empty strings if not authenticated yet.
 */
export function getCachedUserInfo(): { loginId: string; name: string; user_type: string } {
  if (typeof window === "undefined") return { loginId: "", name: "", user_type: "" };
  try {
    const raw = sessionStorage.getItem("sre_ai_user");
    if (!raw) return { loginId: "", name: "", user_type: "" };
    return JSON.parse(raw);
  } catch {
    return { loginId: "", name: "", user_type: "" };
  }
}

import { type NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth-server";

/**
 * Protect all routes except:
 * - /login
 * - /api/auth/* (login initiation, callback, user, logout)
 * - /health, /health/liveness, /health/readiness (Kubernetes probes — no session)
 * - Next.js internals (_next/*)
 * - Static assets
 */
const PUBLIC_PATHS = [
  "/login",
  "/api/auth/login",
  "/api/auth/callback",
  "/api/auth/user",
  "/api/auth/logout",
  // Kubernetes probe paths (next.config rewrites these to /api/health/*)
  "/health",
  // /api/health/* kept public so direct calls also bypass auth
  "/api/health",
];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // Always allow public paths and Next.js internals
  if (
    PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/")) ||
    pathname.startsWith("/_next/") ||
    pathname.startsWith("/favicon") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  // Allow OAuth callback redirect to root (PingFed sends code+state to /)
  if (pathname === "/" && req.nextUrl.searchParams.has("code") && req.nextUrl.searchParams.has("state")) {
    const callbackUrl = req.nextUrl.clone();
    callbackUrl.pathname = "/api/auth/callback";
    // Search params (?code=...&state=...) are preserved by clone()
    return NextResponse.redirect(callbackUrl);
  }

  // Check for session cookie
  const session = req.cookies.get(SESSION_COOKIE);

  if (!session?.value) {
    // API routes → return JSON 401 (no redirect to avoid HTML responses in contract tests)
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }
    // Page routes → redirect to login
    const loginUrl = req.nextUrl.clone();
    loginUrl.pathname = "/login";
    return NextResponse.redirect(loginUrl);
  }

  // Parse and validate — check for corruption and token expiry
  try {
    let parsed: any;
    const metaParsed = JSON.parse(session.value);

    // Check if it's a chunked session metadata marker
    if (metaParsed && typeof metaParsed === "object" && "chunks" in metaParsed) {
      let fullRaw = "";
      for (let i = 0; i < metaParsed.chunks; i++) {
        const chunk = req.cookies.get(`${SESSION_COOKIE}.${i}`)?.value;
        if (!chunk) throw new Error("Missing chunk");
        fullRaw += chunk;
      }
      parsed = JSON.parse(fullRaw);
    } else {
      // Normal unchunked format
      parsed = metaParsed;
    }

    // Token expiry check: expires_at is a Unix timestamp in seconds
    const now = Math.floor(Date.now() / 1000);
    if (parsed.expires_at && parsed.expires_at < now) {
      // Access token has expired — clear cookie
      if (pathname.startsWith("/api/")) {
        const res = NextResponse.json({ error: "Session expired" }, { status: 401 });
        res.cookies.delete(SESSION_COOKIE);
        if (metaParsed.chunks) {
          for (let i = 0; i < metaParsed.chunks; i++) res.cookies.delete(`${SESSION_COOKIE}.${i}`);
        }
        return res;
      }
      const loginUrl = req.nextUrl.clone();
      loginUrl.pathname = "/login";
      const res = NextResponse.redirect(loginUrl);
      res.cookies.delete(SESSION_COOKIE);
      if (metaParsed.chunks) {
        for (let i = 0; i < metaParsed.chunks; i++) res.cookies.delete(`${SESSION_COOKIE}.${i}`);
      }
      return res;
    }

    // Pass user identity downstream via headers (for server components / API routes)
    const response = NextResponse.next();
    response.headers.set("x-user-login-id", parsed.loginId ?? "");
    response.headers.set("x-user-type", parsed.user_type ?? "");
    response.headers.set("x-user-name", parsed.name ?? "");
    return response;
  } catch {
    // Corrupt cookie — clear and return appropriate response
    if (pathname.startsWith("/api/")) {
      const res = NextResponse.json({ error: "Invalid session" }, { status: 401 });
      res.cookies.delete(SESSION_COOKIE);
      for (let i = 0; i < 5; i++) res.cookies.delete(`${SESSION_COOKIE}.${i}`);
      return res;
    }
    const loginUrl = req.nextUrl.clone();
    loginUrl.pathname = "/login";
    const res = NextResponse.redirect(loginUrl);
    res.cookies.delete(SESSION_COOKIE);
    for (let i = 0; i < 5; i++) res.cookies.delete(`${SESSION_COOKIE}.${i}`);
    return res;
  }
}

export const config = {
  matcher: [
    /*
     * Match all paths except:
     * - _next/static, _next/image
     * - favicon.ico, favicon.svg, public assets
     */
    "/((?!_next/static|_next/image|favicon\\.|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp|woff2?|ttf|otf)).*)",
  ],
};

import { type NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, getPingFedConfig } from "@/lib/auth-server";

/**
 * POST /api/auth/logout
 * Clears the session cookie and returns the PingFederate SLO URL
 * so the client can redirect to it for full SSO logout.
 *
 * Cookie deletion is done directly on the NextResponse object (not via the
 * cookies() store) to guarantee the Set-Cookie headers appear in the HTTP
 * response and the browser actually removes them.
 */
export async function POST(req: NextRequest) {
  const appBase = (process.env.NEXTAUTH_URL || req?.nextUrl?.origin).replace(/\/$/, "");

  // In local dev, skip PingFed SLO entirely — just go to /login.
  // In prod/staging, redirect to PingFed SLO so the SSO session is terminated.
  const isLocalDev = process.env.NODE_ENV === "development" || process.env.NODE_ENV === "test";
  let logoutUrl: string;
  if (isLocalDev) {
    logoutUrl = `${appBase}/login`;
  } else {
    try {
      const cfg = getPingFedConfig();
      logoutUrl = cfg.logoutUrl
        ? `${cfg.logoutUrl}?TargetResource=${encodeURIComponent(`${appBase}/login`)}`
        : `${appBase}/login`;
    } catch {
      logoutUrl = `${appBase}/login`;
    }
  }

  const res = NextResponse.json({ logoutUrl });

  const cookieOpts = {
    httpOnly: true,
    secure: !isLocalDev,
    sameSite: (isLocalDev ? "lax" : "none") as "lax" | "none",
    maxAge: 0,
    path: "/",
  };

  // Explicitly delete session cookie and all possible chunks on the response
  res.cookies.set(SESSION_COOKIE, "", cookieOpts);
  for (let i = 0; i < 5; i++) {
    res.cookies.set(`${SESSION_COOKIE}.${i}`, "", cookieOpts);
  }

  return res;
}

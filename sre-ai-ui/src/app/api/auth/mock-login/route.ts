/**
 * GET /api/auth/mock-login
 * LOCAL DEVELOPMENT ONLY — bypasses PingFed SSO for local testing.
 * Disabled in production. Never ships to stage/prod.
 *
 * Usage:
 *   http://localhost:3000/api/auth/mock-login?type=fulltimer
 *   http://localhost:3000/api/auth/mock-login?type=vendor
 *   http://localhost:3000/api/auth/mock-login?type=admin
 */
import { type NextRequest, NextResponse } from "next/server";
import { setSessionCookie } from "@/lib/auth-server";

export async function GET(req: NextRequest) {
  // Hard block in production/stage — this route must never be accessible
  if (process.env.NODE_ENV !== "development") {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const type = req?.nextUrl?.searchParams?.get("type") ?? "fulltimer";
  const appBase = process.env.NEXTAUTH_URL || req?.nextUrl?.origin;

  const mockUsers: Record<string, Parameters<typeof setSessionCookie>[0]> = {
    fulltimer: {
      sub: "m0c0jt",
      name: "Mock Fulltimer",
      email: "m0c0jt@walmart.com",
      loginId: "m0c0jt",
      user_type: "ASSOCIATE",
      isAdmin: false,
      access_token: "mock_fulltimer_token_" + Date.now(),
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    },
    vendor: {
      sub: "vn12345",
      name: "Mock Vendor",
      email: "vn12345@email.wal-mart.com",
      loginId: "vn12345",
      user_type: "VENDOR",
      isAdmin: false,
      access_token: "mock_vendor_token_" + Date.now(),
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    },
    admin: {
      sub: "admin01",
      name: "Mock Admin",
      email: "admin01@walmart.com",
      loginId: "admin01",
      user_type: "ASSOCIATE",
      isAdmin: true,
      access_token: "mock_admin_token_" + Date.now(),
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    },
  };

  const user = mockUsers[type] ?? mockUsers.fulltimer;
  await setSessionCookie(user);

  return NextResponse.redirect(new URL("/", appBase));
}

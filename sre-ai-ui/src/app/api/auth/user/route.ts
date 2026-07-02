import { NextResponse } from "next/server";
import { getSessionCookie, isAdminUser } from "@/lib/auth-server";

/**
 * GET /api/auth/user
 * Returns the current session user.
 * Returns 401 if no valid session exists.
 */
export async function GET() {
  const session = await getSessionCookie();

  if (!session) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  }

  // Strip access_token before sending to the browser;
  // expose only a boolean isAdmin flag.
  const { access_token: _token, ...user } = session as any;

  return NextResponse.json({ ...user, isAdmin: isAdminUser(session) });
}

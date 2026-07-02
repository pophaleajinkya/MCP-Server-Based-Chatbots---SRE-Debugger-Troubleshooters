import { type NextRequest, NextResponse } from "next/server";
import {
  consumePKCECookie,
  exchangeCodeForTokens,
  fetchUserInfo,
  mapUserInfo,
  setSessionCookie,
} from "@/lib/auth-server";
import { createLogger } from "@/lib/logger";
const log = createLogger('api/auth/callback/route.ts');

/**
 * GET /api/auth/callback
 * PingFederate redirects here after user authenticates.
 * Exchanges the authorization code for tokens, fetches userinfo,
 * stores a session cookie, then redirects to the app root.
 */
export async function GET(req: NextRequest) {
  const appBase = process.env.NEXTAUTH_URL || req?.nextUrl?.origin;

  try {
    const { searchParams } = new URL(req.url);
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const error = searchParams.get("error");
    const errorDesc = searchParams.get("error_description");

    if (error) {
      log.error("[/api/auth/callback] PingFed error:", error, errorDesc);
      return NextResponse.redirect(
        `${appBase}/login?error=${encodeURIComponent(errorDesc ?? error)}`
      );
    }

    if (!code || !state) {
      return NextResponse.redirect(`${appBase}/login?error=missing_code_or_state`);
    }

    // Validate state and retrieve code_verifier (+ optional returnTo for shared links)
    const pkce = await consumePKCECookie(state);
    if (!pkce) {
      return NextResponse.redirect(`${appBase}/login?error=invalid_state`);
    }
    const { verifier: codeVerifier, returnTo } = pkce;

    // Exchange authorization code for access token
    const { access_token, expires_in } = await exchangeCodeForTokens(code, codeVerifier);

    // Fetch user claims from userinfo endpoint
    const claims = await fetchUserInfo(access_token);

    // Build and persist session — pass expires_in so the cookie TTL matches the token
    const session = mapUserInfo(claims, access_token, expires_in);
    await setSessionCookie(session);

    // Redirect to the original URL (shared link) if one was stored, otherwise app root
    const destination = returnTo ? `${appBase}${returnTo}` : appBase;
    return NextResponse.redirect(destination);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    log.error("[/api/auth/callback]", message);
    return NextResponse.redirect(
      `${appBase}/login?error=${encodeURIComponent(message)}`
    );
  }
}

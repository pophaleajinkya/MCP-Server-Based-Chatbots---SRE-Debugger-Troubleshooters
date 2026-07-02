import { type NextRequest, NextResponse } from "next/server";
import { generatePKCE, getPingFedConfig, setPKCECookie } from "@/lib/auth-server";
import { createLogger } from "@/lib/logger";
const log = createLogger('api/auth/login/route.ts');

/**
 * GET /api/auth/login
 * Generates PKCE params and redirects the browser to the PingFederate
 * authorization endpoint.
 *
 * Accepts an optional `returnTo` query param (a safe relative URL) so that
 * unauthenticated users following a shared link are sent back to the original
 * URL after authenticating instead of being dropped at the app root.
 */
export async function GET(req: NextRequest) {
  const appBase = process.env.NEXTAUTH_URL || req?.nextUrl?.origin;

  try {
    const rawReturnTo = req.nextUrl.searchParams.get("returnTo") ?? "";
    // Accept only safe relative paths — reject empty, absolute, or protocol-relative URLs
    const returnTo =
      rawReturnTo.startsWith("/") && !rawReturnTo.startsWith("//")
        ? rawReturnTo
        : undefined;

    const cfg = getPingFedConfig();
    const { verifier, challenge, state } = await generatePKCE();

    // Persist state + verifier (+ optional returnTo) so the callback can verify them
    await setPKCECookie(state, verifier, returnTo);

    const params = new URLSearchParams({
      response_type: "code",
      client_id: cfg.clientId,
      redirect_uri: cfg.redirectUri,
      scope: cfg.scope,
      state,
      code_challenge: challenge,
      code_challenge_method: "S256",
    });

    const authorizationUrl = `${cfg.authUrl}?${params.toString()}`;
    return NextResponse.redirect(authorizationUrl);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    log.error("[/api/auth/login]", message);
    return NextResponse.redirect(
      new URL(`/login?error=${encodeURIComponent(message)}`, appBase)
    );
  }
}

import { NextRequest, NextResponse } from "next/server";
import { getSessionCookie, buildLLMGatewayHeaders } from "@/lib/auth-server";
import { createLogger } from "@/lib/logger";

const log = createLogger("api/sessions/[sessionId]/events/subscribe/route.ts");

const BASE = process.env.ADK_AGENT_BASE_URL || "http://localhost:8001";

// Force the Node.js runtime so we can pipe a streaming fetch body through
// without the Edge runtime's stricter body-type constraints.
export const runtime = "nodejs";
// Never cache — this is a live, long-lived SSE channel.
export const dynamic = "force-dynamic";

/**
 * GET /api/sessions/[sessionId]/events/subscribe
 *
 * Long-lived Server-Sent Events (SSE) proxy: forwards super-agent's
 * /sessions/{id}/events/subscribe stream to the browser, piping
 * bytes as they arrive. Used by ChatInterface to receive out-of-band
 * "injection" events (e.g. openclaw monitoring updates pushed via
 * super-agent's POST /sessions/{id}/inject_message).
 *
 * Why proxy instead of hitting super-agent directly from the browser?
 *   1. Browser can't attach our Walmart LLM Gateway headers (loginId,
 *      wm_llm_gw.*, Authorization Bearer) without exposing them.
 *   2. CORS — super-agent is only reachable via the Next.js server.
 *   3. Centralised auth: same PingFed session cookie protects every
 *      /api/sessions/* route.
 *
 * The client aborts via EventSource.close() → AbortController → upstream fetch
 * is cancelled cleanly.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;

  const session = await getSessionCookie();
  const userId = session?.loginId || req.nextUrl.searchParams.get("user_id");
  const ui = userId ?? "-";

  if (!userId) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }

  const upstreamUrl = `${BASE}/sessions/${encodeURIComponent(
    sessionId
  )}/events/subscribe?user_id=${encodeURIComponent(userId)}`;

  // Abort upstream when the browser disconnects (tab close, navigation).
  const abort = new AbortController();
  req.signal.addEventListener("abort", () => abort.abort(), { once: true });

  // EventSource auto-sends the last id it observed on reconnect via the
  // `Last-Event-ID` request header. This proxy must forward it so super-agent
  // can replay missed stream entries instead of starting at "$" every time.
  // Without this, a laptop-sleep / network-blip gap would silently drop live
  // observations until the user reloads the page.
  const lastEventId = req.headers.get("last-event-id");

  // ── Resilient upstream connection ────────────────────────────────────────
  // Instead of returning a 502 when super-agent is down (which makes
  // EventSource close permanently), we return a VALID SSE stream immediately
  // and keep retrying the upstream connection in the background.  The browser
  // stays connected and starts receiving events as soon as super-agent is back.
  const UPSTREAM_RETRY_INTERVAL = 3000; // ms between upstream connect attempts
  const MAX_UPSTREAM_RETRIES = 60;      // give up after ~3 minutes

  const stream = new ReadableStream({
    async start(controller) {
      const encoder = new TextEncoder();
      const push = (text: string) => {
        try { controller.enqueue(encoder.encode(text)); } catch { /* stream closed */ }
      };

      // Tell the browser to retry every 5s if the stream drops mid-flight
      push("retry: 5000\n\n");

      let upstream: Response | null = null;

      for (let attempt = 0; attempt < MAX_UPSTREAM_RETRIES; attempt++) {
        if (abort.signal.aborted) { controller.close(); return; }
        try {
          upstream = await fetch(upstreamUrl, {
            method: "GET",
            headers: {
              ...buildLLMGatewayHeaders(session, req),
              Accept: "text/event-stream",
              "Cache-Control": "no-cache",
              ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
            },
            cache: "no-store",
            signal: abort.signal,
          });
          if (upstream.ok && upstream.body) break; // connected!
          log.warn(`UPSTREAM_BAD attempt=${attempt + 1} ui=${ui} session=${sessionId} status=${upstream.status}`);
          upstream = null;
        } catch (err) {
          if (abort.signal.aborted) { controller.close(); return; }
          const msg = err instanceof Error ? err.message : String(err);
          log.warn(`UPSTREAM_ERR attempt=${attempt + 1} ui=${ui} session=${sessionId} error=${msg}`);
        }
        // Send a heartbeat so the browser knows the stream is alive
        push(": waiting for upstream\n\n");
        await new Promise((r) => setTimeout(r, UPSTREAM_RETRY_INTERVAL));
      }

      if (!upstream?.body) {
        log.error(`UPSTREAM_GAVE_UP ui=${ui} session=${sessionId} after ${MAX_UPSTREAM_RETRIES} retries`);
        push("data: {\"type\":\"error\",\"message\":\"upstream unavailable\"}\n\n");
        controller.close();
        return;
      }

      log.info(`OPEN method=GET ui=${ui} session=${sessionId}`);

      // Pipe upstream bytes straight through
      try {
        const reader = upstream.body.getReader();
        while (true) {
          if (abort.signal.aborted) break;
          const { done, value } = await reader.read();
          if (done) break;
          controller.enqueue(value);
        }
      } catch (err) {
        if (!abort.signal.aborted) {
          const msg = err instanceof Error ? err.message : String(err);
          log.warn(`STREAM_BREAK ui=${ui} session=${sessionId} error=${msg}`);
        }
      }
      controller.close();
    },
  });

  return new NextResponse(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      // Disable buffering on Nginx/ingress layers so updates reach the
      // browser immediately (Walmart's edge often has a default buffer).
      "X-Accel-Buffering": "no",
    },
  });
}

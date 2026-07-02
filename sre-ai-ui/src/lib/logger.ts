/**
 * Server-side structured logger.
 *
 * Log line format (Spring Boot / logfmt style):
 *   YYYY-MM-DD HH:MM:SS.mmm LEVEL [source] message
 *
 * Outbound HTTP calls (via loggedFetch) emit:
 *   2026-04-08 14:23:45.123 INFO  [src] OUTBOUND method=POST lb=http://... ui=m0c00jt status=200 duration=145ms
 *   2026-04-08 14:23:45.456 ERROR [src] OUTBOUND method=GET  lb=http://... ui=m0c00jt status=503 duration=23ms body={"error":"..."}
 *   2026-04-08 14:23:45.789 ERROR [src] OUTBOUND method=POST lb=http://... ui=m0c00jt status=CONN_ERR duration=5ms error=ECONNREFUSED
 *
 * Usage:
 *   import { createLogger, loggedFetch } from '@/lib/logger';
 *   const log = createLogger('my-file.ts');
 *   log.info('server started');
 *   log.error('something broke', err);
 *
 *   const res = await loggedFetch(url, { method: 'POST', body, ui: loginId, tag: 'my-file.ts' });
 */

/** ISO-8601 timestamp without the T/Z separators — matches Java/Spring Boot style. */
function ts(): string {
  return new Date().toISOString().replace('T', ' ').slice(0, 23);
}

/** Build a prefix identical to Spring Boot's default pattern:  DATE TIME LEVEL [source] */
function prefix(level: string, source: string): string {
  return `${ts()} ${level.padEnd(5)} [${source}]`;
}

export function createLogger(source: string) {
  return {
    info:  (msg: string, ...args: unknown[]) => console.log  (prefix('INFO',  source), msg, ...args),
    log:   (msg: string, ...args: unknown[]) => console.log  (prefix('INFO',  source), msg, ...args),
    warn:  (msg: string, ...args: unknown[]) => console.warn (prefix('WARN',  source), msg, ...args),
    error: (msg: string, ...args: unknown[]) => console.error(prefix('ERROR', source), msg, ...args),
    debug: (msg: string, ...args: unknown[]) => console.debug(prefix('DEBUG', source), msg, ...args),
  };
}

// ─── loggedFetch ──────────────────────────────────────────────────────────────

export interface LoggedFetchOptions extends RequestInit {
  /**
   * User identity (loginId / userId) printed as `ui=` in the log line.
   * Defaults to '-' when the caller does not have session context.
   */
  ui?: string;
  /**
   * Logger source tag — typically the calling filename.
   * Defaults to 'http'.
   */
  tag?: string;
  /**
   * Maximum characters of the response body to include in the ERROR log line
   * for non-2XX responses.  Defaults to 500.
   */
  errorBodyLimit?: number;
}

/**
 * Drop-in replacement for `fetch()` that emits one structured log line per call.
 *
 *  • 2XX responses  → INFO  line (no body printed)
 *  • non-2XX        → ERROR line + truncated response body
 *  • network error  → ERROR line + error message, then re-throws
 *
 * The returned `Response` is identical to what native `fetch()` returns —
 * callers can still read `.json()` / `.text()` normally because the error
 * body is read from a `.clone()`.
 */
export async function loggedFetch(
  url: string,
  options: LoggedFetchOptions = {},
): Promise<Response> {
  const { ui = '-', tag = 'http', errorBodyLimit = 500, ...fetchOpts } = options;
  const method = ((fetchOpts.method as string | undefined) ?? 'GET').toUpperCase();
  const log    = createLogger(tag);
  const t0     = Date.now();

  // ── execute ────────────────────────────────────────────────────────────────
  let response: Response;
  try {
    response = await fetch(url, fetchOpts);
  } catch (err) {
    const ms  = Date.now() - t0;
    const msg = err instanceof Error ? err.message : String(err);
    log.error(`OUTBOUND method=${method} lb=${url} ui=${ui} status=CONN_ERR duration=${ms}ms error=${msg}`);
    throw err;
  }

  const ms     = Date.now() - t0;
  const status = response.status;

  // ── log ────────────────────────────────────────────────────────────────────
  if (response.ok) {
    log.info(`OUTBOUND method=${method} lb=${url} ui=${ui} status=${status} duration=${ms}ms`);
  } else {
    // Clone before reading so the caller's body stream is untouched
    let body = '';
    try {
      body = await response.clone().text();
    } catch {
      body = '(unreadable)';
    }
    log.error(
      `OUTBOUND method=${method} lb=${url} ui=${ui} status=${status} duration=${ms}ms body=${body.slice(0, errorBodyLimit)}`,
    );
  }

  return response;
}

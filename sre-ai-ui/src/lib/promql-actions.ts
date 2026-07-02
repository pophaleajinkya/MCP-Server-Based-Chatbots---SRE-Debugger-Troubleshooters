'use server';

/**
 * Server actions for PromQL query-range API
 * These run on the server and have access to process.env
 *
 * Every outbound call is logged as:
 *   DATE TIME LEVEL [promql-actions.ts] OUTBOUND method=POST lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */

import { createLogger, loggedFetch } from '@/lib/logger';
import { getSessionCookie } from '@/lib/auth-server';

const log = createLogger('promql-actions.ts');

export interface PromQLQueryRangePayload {
  promql: string;
  start: string;   // epoch seconds
  end: string;     // epoch seconds
  step: string;    // e.g. "3600s"
}

export interface PromQLQueryRangeResult {
  status?: string;
  data?: {
    resultType?: string;
    result?: Array<{
      metric: Record<string, string>;
      values: [number, string][];   // [epoch, value]
    }>;
  };
  error?: string;
  errorType?: string;
}

type LoggedFetchOpts = Parameters<typeof loggedFetch>[1];

/**
 * Query PromQL query-range endpoint.
 * Reads PROMQL_API_URL from process.env at runtime (not build time).
 */
export async function queryPromQLRange(
  payload: PromQLQueryRangePayload
): Promise<PromQLQueryRangeResult> {
  const promqlApiUrl = process.env.PROMQL_API_URL;
  if (!promqlApiUrl) {
    throw new Error(
      'PROMQL_API_URL is not configured. Set it in .env.local or via environment variables.'
    );
  }

  // Resolve user identity for access log
  const session = await getSessionCookie().catch(() => null);
  const ui = session?.loginId ?? '-';

  const fetchOpts: LoggedFetchOpts = {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
    ui,
    tag: 'promql-actions.ts',
  };

  // Retry up to 3 times on transient gateway errors (502 / 503 / 504)
  const RETRYABLE   = new Set([502, 503, 504]);
  const MAX_RETRIES = 3;
  const RETRY_DELAY = 1000;

  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    let response: Response | null = null;
    try {
      response = await loggedFetch(promqlApiUrl, fetchOpts);

      if (response.ok) {
        return (await response.json()) as PromQLQueryRangeResult;
      }

      // loggedFetch already emitted the ERROR line with status + body
      if (RETRYABLE.has(response.status) && attempt < MAX_RETRIES) {
        lastError = new Error(`PromQL query-range failed: ${response.status} ${response.statusText}`);
        log.warn(`RETRY attempt=${attempt + 1} method=POST lb=${promqlApiUrl} ui=${ui} reason=${response.status}`);
        await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
        continue;
      }

      throw new Error(`PromQL query-range failed: ${response.status} ${response.statusText}`);
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      lastError      = error instanceof Error ? error : new Error(String(error));

      if (attempt < MAX_RETRIES && response && RETRYABLE.has(response.status)) {
        log.warn(`RETRY attempt=${attempt + 1} method=POST lb=${promqlApiUrl} ui=${ui} error=${errorMsg}`);
        await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
        continue;
      }
      throw lastError;
    }
  }
  throw lastError ?? new Error('PromQL query-range failed after retries');
}

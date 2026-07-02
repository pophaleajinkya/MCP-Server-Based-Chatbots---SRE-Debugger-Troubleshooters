 'use server';

import { createLogger, loggedFetch } from '@/lib/logger';
import { getSessionCookie } from '@/lib/auth-server';

const log = createLogger('sre-operator-actions.ts');

/**
 * Server actions for SRE Operator API
 * These run on the server and have access to process.env.
 * This mirrors how ALERTS_URL / PingFed endpoints are accessed (server-side only).
 */

export interface FetchOptions {
  method?: string;
  body?: string;
  headers?: Record<string, string>;
}

/**
 * Fetch from the SRE Operator API.
 * Reads SRE_OPERATOR_URL from process.env at runtime (not build time).
 * This allows Kubernetes init containers to inject the URL from secrets.
 *
 * Every call is logged as:
 *   DATE TIME LEVEL [sre-operator-actions.ts] OUTBOUND method=GET lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */
export async function fetchSreOperator(endpoint: string, options?: FetchOptions): Promise<unknown> {
  const sreOperatorUrl = process.env.SRE_OPERATOR_URL || 'http://localhost:9000';
  const url = `${sreOperatorUrl}${endpoint}`;

  // Resolve user identity for access log (best-effort — no auth required for internal ops)
  const session = await getSessionCookie().catch(() => null);
  const ui = session?.loginId ?? '-';

  let response: Response;
  try {
    response = await loggedFetch(url, {
      method:  options?.method ?? 'GET',
      body:    options?.body,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ui,
      tag: 'sre-operator-actions.ts',
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    // loggedFetch already emitted the CONN_ERR line; re-throw with friendly message
    throw new Error(`Network error reaching SRE Operator: ${msg}`);
  }

  if (!response.ok) {
    let errorMessage = `API Error: ${response.status} ${response.statusText}`;
    try {
      // loggedFetch already logged the body; parse it to extract a structured message
      const text = await response.text();
      const parsed = JSON.parse(text);
      if (parsed.message) errorMessage = parsed.message;
    } catch {
      // Response body is not JSON — keep generic message
    }
    throw new Error(errorMessage);
  }

  if (response.status === 204) {
    return undefined;
  }
  return response.json();
}

'use server';

/**
 * Server actions for alerts API
 * These run on the server and have access to process.env
 * Uses PROMQL_API_URL — same pattern as PINGFED_AUTH_URL and other runtime configs
 *
 * Calls PROMQL_API_URL (which includes the full path) with ALERTS{...} PromQL
 * and transforms the result into AlertQueryResult format consumed by AlertsView.
 */

import { createLogger, loggedFetch } from '@/lib/logger';
import { getSessionCookie } from '@/lib/auth-server';
import {
  type AlertQueryPayload,
  type AlertQueryResult,
  type AlertResultAlert,
} from './api-client';

const log = createLogger('alerts-actions.ts');

/** Base PromQL filter used by the Alerts page — alertstate="firing" to get only currently firing alerts */
const BASE_ALERTS_PROMQL =
  'ALERTS{tool="juno", alert_team="intl_sre_golden_signals", alertstate="firing"}';

/**
 * Query alerts via PromQL query-range endpoint.
 * Reads PROMQL_API_URL from process.env at runtime (not build time).
 * This allows Kubernetes init containers to inject the URL from secrets.
 *
 * Every outbound call is logged as:
 *   DATE TIME LEVEL [alerts-actions.ts] OUTBOUND method=POST lb=<url> ui=<loginId> status=<code> duration=<ms>ms
 */
export async function queryAlerts(payload: AlertQueryPayload): Promise<AlertQueryResult> {
  const promqlApiUrl = process.env.PROMQL_API_URL;
  if (!promqlApiUrl) {
    throw new Error(
      'PROMQL_API_URL is not configured. Set it in .env.local or via environment variables.'
    );
  }

  // Resolve user identity for access log
  const session = await getSessionCookie().catch(() => null);
  const ui = session?.loginId ?? '-';

  const promqlPayload = {
    promql: BASE_ALERTS_PROMQL,
    start: payload.start,
    end: payload.end,
    step: payload.step || '30s',
  };

  const fetchOpts: LoggedFetchOpts = {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(promqlPayload),
    ui,
    tag: 'alerts-actions.ts',
  };

  // Retry up to 3 times on transient errors (500 timeout / 502 / 503 / 504)
  const RETRYABLE    = new Set([500, 502, 503, 504]);
  const MAX_RETRIES  = 3;
  const RETRY_DELAY  = 1000;

  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    let response: Response | null = null;
    try {
      response = await loggedFetch(promqlApiUrl, fetchOpts);

      if (response.ok) {
        const startMs    = performance.now();
        const raw        = await response.json();
        const queryTimeMs = performance.now() - startMs;

        const alerts = transformPromQLToAlerts(raw);
        return {
          status: 'success',
          ok: true,
          alerts,
          total_count:      alerts.length,
          query_time_ms:    queryTimeMs,
          prometheus_query: BASE_ALERTS_PROMQL,
        };
      }

      // loggedFetch already emitted the ERROR line with status + body
      if (RETRYABLE.has(response.status) && attempt < MAX_RETRIES) {
        lastError = new Error(`Alerts query failed: ${response.status} ${response.statusText}`);
        log.warn(`RETRY attempt=${attempt + 1} method=POST lb=${promqlApiUrl} ui=${ui} reason=${response.status}`);
        await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
        continue;
      }

      throw new Error(`Alerts query failed: ${response.status} ${response.statusText}`);
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
  throw lastError ?? new Error('Alerts query failed after retries');
}

// Internal alias so the fetch options type resolves cleanly inside this module
type LoggedFetchOpts = Parameters<typeof loggedFetch>[1];

/**
 * Transform PromQL query-range result into AlertResultAlert[].
 * Each series in the result becomes one alert row, with metric labels
 * mapped to AlertResultAlert fields.
 */
function transformPromQLToAlerts(raw: any): AlertResultAlert[] {
  const results = raw?.data?.result;
  if (!Array.isArray(results)) return [];

  const alerts = results.map((series: any) => {
    const m: Record<string, string> = series.metric || {};
    const values: [number, string][] = Array.isArray(series.values) ? series.values : [];
    const firstTs = values.length > 0 ? values[0][0] : null;

    return {
      alert_id:             m.alert_id || '',
      alertname:            m.alertname || m.__name__ || undefined,
      alert_type:           m.alert_type || undefined,
      alert_sla_name:       m.alert_sla_name || undefined,
      severity:             m.severity || undefined,
      state:                m.alertstate || undefined,
      namespace:            m.namespace || undefined,
      app_name:             m.app_name || undefined,
      tenant:               m.tenant || null,
      assembly:             m.assembly || null,
      platform:             m.platform || null,
      env:                  m.env || null,
      cluster:              m.cluster || m.cluster_id || null,
      subscription_name:    m.subscription_name || null,
      resource_group:       m.resource_group || null,
      market:               m.market || null,
      tier:                 m.tier || null,
      alert_team:           m.alert_team || null,
      alert_owner_category: m.alert_owner_category || null,
      alert_component:      m.alert_component || null,
      mms_slack_channel:    m.mms_slack_channel || null,
      mms_xmatters_group:   m.mms_xmatters_group || null,
      episode_start_ts:     firstTs,
      episode_end_ts:       values.length > 0 ? values[values.length - 1][0] : null,
      episode_is_open:      m.alertstate === 'firing' ? true : null,
      values,
      labels: m,
    } as AlertResultAlert;
  });

  // Pre-sort by start time descending — most recently fired alerts first
  alerts.sort((a, b) => {
    const tsA = a.values?.length ? a.values[0][0] : 0;
    const tsB = b.values?.length ? b.values[0][0] : 0;
    return tsB - tsA;
  });

  return alerts;
}

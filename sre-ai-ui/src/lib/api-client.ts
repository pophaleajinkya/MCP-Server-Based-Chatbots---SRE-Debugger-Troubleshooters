/**
 * API Client for SRE AI UI
 * Matches the sre-operator-ui backend API structure
 */

import { createLogger } from '@/lib/logger';
const log = createLogger('api-client.ts');

import { queryAlerts } from './alerts-actions';
import { fetchSreOperator } from './sre-operator-actions';

// ============ SRE Operator URL Configuration (Runtime) ============
/**
 * Get SRE Operator API URL directly from environment variable.
 * This is read at runtime, not at build time, allowing Kubernetes
 * init containers to inject the URL from secrets.
 * Works the same way as PINGFED_AUTH_URL and other server-side configs.
 */
function getSreOperatorUrl(): string {
  return process.env.SRE_OPERATOR_URL || 'http://localhost:9000';
}

// ============ Alerts URL Configuration (Runtime) ============
/**
 * Get alerts service URL directly from environment variable.
 * This is read at runtime, not at build time, allowing Kubernetes
 * init containers to inject the URL from secrets.
 * Works the same way as PINGFED_AUTH_URL and other server-side configs.
 */
function getAlertsServiceUrl(): string {
  return process.env.ALERTS_URL || 'http://localhost:8020';
}

// ============ Change Requests URL Configuration (Runtime) ============
/**
 * Get change requests API URL directly from environment variable.
 * Points to maof-deployment-agent's GET /crq endpoint.
 * Accepts ?hours_ago=N query parameter.
 */
function getChangeRequestsUrl(): string {
  return process.env.CHANGE_REQUESTS_API_URL || 'http://localhost:8000/crq';
}

// ============ Incidents URL Configuration (Runtime) ============
/**
 * Get incidents API URL directly from environment variable.
 * This is read at runtime, not at build time, allowing Kubernetes
 * init containers to inject the URL from secrets.
 * Works the same way as PINGFED_AUTH_URL and other server-side configs.
 */
function getIncidentsUrl(): string {
  return process.env.INCIDENTS_API_URL || 'http://localhost:9000';
}

// ============ PromQL API URL Configuration (Runtime) ============
/**
 * Get PromQL API URL directly from environment variable.
 * This is read at runtime, not at build time, allowing Kubernetes
 * init containers to inject the URL from secrets.
 * Works the same way as PINGFED_AUTH_URL and other server-side configs.
 */
function getPromqlApiUrl(): string {
  const envValue = process.env.PROMQL_API_URL;
  const promqlApiUrl = envValue;
  if (!promqlApiUrl) {
    throw new Error('PROMQL_API_URL is not set. Add it to your .env.local or Kubernetes secrets.');
  }
  return promqlApiUrl;
}

// Export for use in components
export { getSreOperatorUrl, getAlertsServiceUrl, getChangeRequestsUrl, getIncidentsUrl, getPromqlApiUrl };

// Generic fetch wrapper with error handling
async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  return fetchSreOperator(endpoint, options ? {
    method: options.method,
    body: typeof options.body === 'string' ? options.body : undefined,
    headers: options.headers as Record<string, string> | undefined,
  } : undefined) as Promise<T>;
}

// ============ Application Types ============
export interface TeamMember {
  id: number;
  name: string;
  email: string;
  role?: string;
}

export interface TeamDetails {
  teamId: number;
  jira: string;
  isPrimaryTeam: boolean;
  members: TeamMember[];
}

export interface Application {
  id: number;
  name: string;
  tenant: string;
  tier: string;
  functionalDomain: string;
  active: boolean;
  certified: boolean;
  applicationType: string;
  namespace: string | null;
  appName: string | null;
  cluster: string | null;
  team: TeamDetails | null;
  slackChannels: string[];
  xmattersGroups: string[];
  emails: string[];
  oneOpsPlatformId: number | null;
  wcnpId: number | null;
  pageFlowId: number | null;
  oneOpsOrg: string | null;
  oneOpsAssembly: string | null;
  oneOpsPlatform: string | null;
}

export interface DependencyData {
  // Legacy fields (old API)
  id?: number;
  name?: string;
  tenant?: string;
  tier?: string;
  funcDomain?: string;
  active?: boolean;
  wcnp?: {
    namespace: string;
    app?: string;
  };
  oneOpsPlatform?: {
    name: string;
  };
  pageFlow?: boolean;

  // Current SRE-operator dependency API fields
  application_id?: number;
  application_name?: string;
  managed_service_id?: number | null;
  wcnp_id?: number | null;
  namespace?: string | null;
  app_name?: string | null;
  oneops_id?: number | null;
  org?: string | null;
  assembly?: string | null;
  platform?: string | null;
}

// ============ OneOps Types ============
export interface OneOpsData {
  id: number;
  platform: string;
  assembly: string;
  org: string;
}

// ============ WCNP Types ============
export interface WcnpData {
  id: number;
  app: string;
  namespace: string;
  appName?: string;
  tier?: string;
  tenant?: string;
}

// ============ Managed Services Types ============
export interface ManagedServiceData {
  id: number | string;
  managedServiceId: number;
  name: string;
  serviceType: string;
  appId?: number | null;
  assembly?: string;
  platform?: string;
  subscriptionId?: string;
  resourceGroup?: string;
  databaseName?: string;
  dns?: string;
  topicName?: string;
}

/** Raw response from GET /managed-services/details */
export interface ManagedServiceDetailsResponse {
  managedServiceId: number;
  name: string | null;
  serviceType: string | null;
  appId?: number | null;
  sqlSubscriptionId?: string | null;
  sqlResourceGroup?: string | null;
  sqlServerName?: string | null;
  sqlDns?: string | null;
  cosmosSubscriptionId?: string | null;
  cosmosResourceGroup?: string | null;
  cosmosDatabaseAccount?: string | null;
  cosmosDns?: string | null;
  solrCollectionName?: string | null;
  cassandraClusterName?: string | null;
  cassandraDatabaseName?: string | null;
  kafkaTopicName?: string | null;
  meghaCacheName?: string | null;
  meghaCachePlatform?: string | null;
}

function mapDetailFields(r: ManagedServiceDetailsResponse): Pick<ManagedServiceData, 'assembly' | 'platform' | 'subscriptionId' | 'resourceGroup' | 'databaseName' | 'dns' | 'topicName'> {
  const t = (r.serviceType || '').toLowerCase();
  switch (t) {
    case 'cassandra':
      return { assembly: r.cassandraClusterName ?? '', platform: r.cassandraDatabaseName ?? '' };
    case 'cosmos':
      return { subscriptionId: r.cosmosSubscriptionId ?? '', resourceGroup: r.cosmosResourceGroup ?? '', databaseName: r.cosmosDatabaseAccount ?? '', dns: r.cosmosDns ?? '' };
    case 'kafka':
      return { topicName: r.kafkaTopicName ?? '' };
    case 'meghacache':
      return { assembly: r.meghaCacheName ?? '', platform: r.meghaCachePlatform ?? '' };
    case 'solr':
      return { assembly: r.solrCollectionName ?? '' };
    case 'sql':
      return { subscriptionId: r.sqlSubscriptionId ?? '', resourceGroup: r.sqlResourceGroup ?? '', databaseName: r.sqlServerName ?? '', dns: r.sqlDns ?? '' };
    default:
      return {};
  }
}

// ============ Dependency Approval Types ============
export interface DependencyApproval {
  id: number;
  applicationId: number;
  applicationName: string;
  dependencyId: number;
  dependencyName: string;
  action: "ADD" | "DELETE";
  status: "PENDING" | "APPROVED" | "REJECTED";
  reason: string | null;
  requestedBy: string;
  approvedBy: string | null;
  approvedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface DependencyApprovalResponse {
  status: number;
  message: string;
  data: DependencyApproval;
}

// ============ Dependency Approvals API ============
export const dependencyApprovalsApi = {
  submitRequest: (params: {
    applicationId: number;
    dependencyId: number;
    action: "ADD" | "DELETE";
    requestedBy: string;
    reason?: string;
  }) =>
    fetchAPI<DependencyApprovalResponse>('/dependency-approvals', {
      method: 'POST',
      body: JSON.stringify(params),
    }),

  approve: (id: number, approvedBy: string, reason?: string) =>
    fetchAPI<DependencyApprovalResponse>(`/dependency-approvals/${id}/approve`, {
      method: 'PUT',
      body: JSON.stringify({ approvedBy, reason }),
    }),

  reject: (id: number, approvedBy: string, reason?: string) =>
    fetchAPI<DependencyApprovalResponse>(`/dependency-approvals/${id}/reject`, {
      method: 'PUT',
      body: JSON.stringify({ approvedBy, reason }),
    }),

  getAll: () =>
    fetchAPI<DependencyApproval[]>('/dependency-approvals'),

  getByStatus: (status: "PENDING" | "APPROVED" | "REJECTED") =>
    fetchAPI<DependencyApproval[]>(`/dependency-approvals/status/${status}`),

  getByApplication: (applicationId: number) =>
    fetchAPI<DependencyApproval[]>(`/dependency-approvals/application/${applicationId}`),

  getById: (id: number) =>
    fetchAPI<DependencyApproval>(`/dependency-approvals/${id}`),
};

// ============ Page Flow Types ============
export interface PageFlowApplication {
  id: string;
  name: string;
  description?: string;
}

export interface Dependency {
  id: string;
  name: string;
  type: string;
}

// ============ Alerts Types ============
export interface AlertChannelConfig {
  alert_channel_config_id: number;
  maof_status: string;
  status: string;
  creation_timestamp: string;
  modification_timestamp: string;
}

export interface AlertQueryPayload {
  intent?: string;
  start: string;
  end: string;
  step?: string;
  // WCNP / k8s
  namespace?: string | null;
  app_name?: string | null;
  // OneOps
  org?: string | null;
  assembly?: string | null;
  platform?: string | null;
  // Cosmos
  subscription_name?: string | null;
  resource_group?: string | null;
  // Cassandra
  cluster?: string | null;
  // MegaCache
  megacache_assembly?: string | null;
  // SQL / Oracle
  database?: string | null;
  // Kafka
  topic?: string | null;
  service_type?: string; // service type sent to the backend (wcnp, oneops, cassandra, etc.)
  alert_type?: string;  // kept for backward compatibility
}

export interface AlertQueryResult {
  status?: string;
  error?: string;
  results?: Array<{
    metric: Record<string, string>;
    values: [number, string][];
  }>;
  alerts?: AlertResultAlert[];
  // Additional fields from the API response
  ok?: boolean;
  request_id?: string | null;
  intent?: string;
  service_type?: string | null;
  filters_applied?: Record<string, any>;
  prometheus_query?: string | null;
  total_count?: number;
  query_time_ms?: number;
  cached?: boolean | null;
}

export interface AlertResultAlert {
  alert_id?: string;
  alertname?: string;
  alert_type?: string;
  alert_sla_name?: string;
  severity?: string;
  state?: string;
  timestamp?: number | null;
  epoch_timestamp?: number | null;
  namespace?: string;
  app_name?: string;
  tenant?: string | null;
  assembly?: string | null;
  platform?: string | null;
  env?: string | null;
  cluster?: string | null;
  subscription_name?: string | null;
  resource_group?: string | null;
  market?: string | null;
  tier?: string | null;
  alert_team?: string | null;
  alert_owner_category?: string | null;
  alert_component?: string | null;
  mms_slack_channel?: string | null;
  mms_xmatters_group?: string | null;
  episode_start_ts?: number | null;
  episode_end_ts?: number | null;
  episode_is_open?: boolean | null;
  episode_count?: number | null;
  value?: string | null;
  values?: [number, string][];
  labels?: Record<string, string>;
  annotations?: Record<string, string>;
}

// Helper function to build alerts query payload from an application
export function buildAlertsQueryPayload(
  app: Application | ManagedServiceData,
  startEpoch: string,
  endEpoch: string,
  intent?: string,
  step?: string
): AlertQueryPayload {
  let serviceType: string | undefined = undefined;
  const basePayload: AlertQueryPayload = {
    start: startEpoch,
    end: endEpoch,
    step: step ?? '30s',
  };

  if (intent) {
    basePayload.intent = intent;
  }

  // Check if it's an Application
  if ('applicationType' in app) {
    const application = app as Application;
    if (application.applicationType === 'wcnp') {
      serviceType = 'wcnp';
      return {
        ...basePayload,
        service_type: serviceType,
        namespace: application.namespace,
        app_name: application.appName,
      };
    } else if (application.applicationType === 'oneops') {
      serviceType = 'oneops';
      return {
        ...basePayload,
        service_type: serviceType,
        org: application.oneOpsOrg,
        assembly: application.oneOpsAssembly,
        platform: application.oneOpsPlatform,
      };
    }
  }

  // Check if it's a ManagedServiceData
  if ('serviceType' in app) {
    const service = app as ManagedServiceData;
    serviceType = (service.serviceType || '').toLowerCase();
    switch (serviceType) {
      case 'cassandra':
        return {
          ...basePayload,
          service_type: serviceType,
          cluster: service.assembly,
        };
      case 'cosmos':
        return {
          ...basePayload,
          service_type: serviceType,
          subscription_name: service.subscriptionId,
          resource_group: service.resourceGroup,
        };
      case 'kafka':
        return {
          ...basePayload,
          service_type: serviceType,
          cluster: service.assembly,
          topic: service.topicName,
        };
      case 'meghacache':
        return {
          ...basePayload,
          service_type: serviceType,
          megacache_assembly: service.assembly,
        };
      case 'sql':
        return {
          ...basePayload,
          service_type: serviceType,
          database: service.databaseName,
        };
      case 'oracle':
        return {
          ...basePayload,
          service_type: serviceType,
          database: service.databaseName,
        };
      default:
        return { ...basePayload, service_type: serviceType };
    }
  }

  return { ...basePayload, ...(serviceType ? { service_type: serviceType } : {}) };
}

// ============ Applications API Cache ============
let applicationsCache: Application[] | null = null;
let applicationsCacheTime: number = 0;
const CACHE_DURATION = 10 * 60 * 1000; // 10 minutes

/**
 * Fetch bulk data via the /sre-api rewrite (browser → Next.js proxy → backend).
 * This path benefits from HTTP gzip/brotli compression (30MB → ~3MB).
 * Falls back to server action if the rewrite isn't available.
 */
/**
 * Fetch bulk data via the server action (fetchSreOperator).
 * This ensures ALL errors (4XX/5XX/network) are logged to server stdout.
 * The /sre-api rewrite is a transparent proxy that doesn't log errors.
 */
async function fetchBulkClient<T>(endpoint: string): Promise<T> {
  return fetchAPI<T>(endpoint);
}

// ============ Applications API ============
export const applicationsApi = {
  /**
   * Returns cached data immediately if available (stale-while-revalidate pattern).
   * If cache is expired, returns stale data AND triggers a background refresh.
   * If no cache exists, blocks until fresh data arrives.
   */
  fetchAll: async () => {
    const now = Date.now();

    // Fresh cache — return immediately
    if (applicationsCache && (now - applicationsCacheTime) < CACHE_DURATION) {
      return applicationsCache;
    }

    // Stale cache exists — return stale data, refresh in background (stale-while-revalidate)
    if (applicationsCache) {
      // Fire-and-forget background refresh
      fetchBulkClient<Application[]>('/applications/detailed').then(apps => {
        applicationsCache = apps;
        applicationsCacheTime = Date.now();
      }).catch(() => { /* silent — stale data is better than no data */ });
      return applicationsCache;
    }

    // No cache at all — must block until data arrives
    const apps = await fetchBulkClient<Application[]>('/applications/detailed');
    applicationsCache = apps;
    applicationsCacheTime = now;
    return apps;
  },

  /** Returns cached data synchronously (null if not yet loaded) */
  getCached: () => applicationsCache,

  fetchById: (id: number) => fetchAPI<Application>(`/applications/detailed/${id}`),

  findByWcnp: (namespace: string, appName: string) =>
    fetchAPI<{ applicationId: number }>(`/applications/wcnp?namespace=${encodeURIComponent(namespace)}&appName=${encodeURIComponent(appName)}`),

  findByOneOps: (orgName: string, assemblyName: string, platformName: string) =>
    fetchAPI<{ applicationId: number }>(`/applications/oneops?orgName=${encodeURIComponent(orgName)}&assemblyName=${encodeURIComponent(assemblyName)}&platformName=${encodeURIComponent(platformName)}`),

  fetchUpstream: (id: number) =>
    fetchAPI<DependencyData[]>(`/dependencies/upstream?applicationId=${id}`),

  fetchDownstream: (id: number) =>
    fetchAPI<DependencyData[]>(`/dependencies/downstream?applicationId=${id}`),

  addDependency: (applicationId: number, dependencyId: number) =>
    fetchAPI<{ success: boolean }>('/dependencies', {
      method: 'POST',
      body: JSON.stringify({
        applicationId,
        dependencyId,
        source: 'user',
      }),
    }),

  addUpstreamDependency: (applicationId: number, upstreamId: number) =>
    fetchAPI<{ success: boolean }>('/dependencies', {
      method: 'POST',
      body: JSON.stringify({
        applicationId: upstreamId,
        dependencyId: applicationId,
        source: 'user',
      }),
    }),
  
  deleteDependency: (applicationId: number, dependencyId: number) =>
    fetchAPI<{ success: boolean }>(`/dependencies/application/${applicationId}/dependency/${dependencyId}`, {
      method: 'DELETE',
    }),

  deleteDownstreamDependency: (applicationId: number, dependencyId: number) =>
    fetchAPI<{ success: boolean }>(`/dependencies/application/${applicationId}/dependency/${dependencyId}`, {
      method: 'DELETE',
    }),

  deleteUpstreamDependency: (applicationId: number, upstreamId: number) =>
    fetchAPI<{ success: boolean }>(`/dependencies/application/${upstreamId}/dependency/${applicationId}`, {
      method: 'DELETE',
    }),
  
  getActiveCount: async () => {
    const apps = await applicationsApi.fetchAll();
    return apps.filter(app => app.active).length;
  },
  
  getInactiveCount: async () => {
    const apps = await applicationsApi.fetchAll();
    return apps.filter(app => !app.active).length;
  },
  
  getByType: async () => {
    const apps = await applicationsApi.fetchAll();
    const typeCounts: Record<string, number> = {};
    apps.forEach(app => {
      const type = app.applicationType || 'Unknown';
      typeCounts[type] = (typeCounts[type] || 0) + 1;
    });
    return Object.entries(typeCounts).map(([type, count]) => ({ type, count }));
  },
};

// ============ OneOps API ============
export const oneopsApi = {
  fetchAll: () => fetchAPI<OneOpsData[]>('/oneops/platform/details'),
  
  update: (data: Partial<OneOpsData> & { id: number }) =>
    fetchAPI<OneOpsData>(`/oneops/platform/${data.id}`, {
      method: 'PUT',
      body: JSON.stringify({
        platform: data.platform,
        assembly: data.assembly,
        org: data.org,
      }),
    }),
};

// ============ WCNP API ============
export const wcnpApi = {
  fetchAll: () => fetchAPI<WcnpData[]>('/wcnp'),
  
  update: (data: WcnpData) =>
    fetchAPI<WcnpData>(`/wcnp/${data.id}`, {
      method: 'PUT',
      body: JSON.stringify({
        namespace: data.namespace,
        app: data.app,
      }),
    }),
};

// ============ Managed Services API Cache ============
let managedServicesCache: ManagedServiceDetailsResponse[] | null = null;
let managedServicesCacheTime: number = 0;

function mapManagedServiceRaw(r: ManagedServiceDetailsResponse): ManagedServiceData {
  return {
    id: r.managedServiceId,
    managedServiceId: r.managedServiceId,
    name: r.name ?? '',
    serviceType: r.serviceType ?? '',
    appId: r.appId ?? undefined,
    ...mapDetailFields(r),
  };
}

// ============ Managed Services API ============
export const managedServicesApi = {
  getCached: (): ManagedServiceData[] | null => {
    const now = Date.now();
    if (managedServicesCache && (now - managedServicesCacheTime) < CACHE_DURATION) {
      return managedServicesCache.map(mapManagedServiceRaw);
    }
    return null;
  },

  fetchAll: async (): Promise<ManagedServiceData[]> => {
    const now = Date.now();
    if (managedServicesCache && (now - managedServicesCacheTime) < CACHE_DURATION) {
      return managedServicesCache.map(mapManagedServiceRaw);
    }

    const raw = await fetchBulkClient<ManagedServiceDetailsResponse[]>('/managed-services/details');
    managedServicesCache = raw;
    managedServicesCacheTime = now;
    return raw.map(mapManagedServiceRaw);
  },

  delete: async (id: number) => {
    const result = await fetchAPI<void>(`/managed-services/${id}`, { method: 'DELETE' });
    managedServicesCache = null;
    return result;
  },
};

// ============ Page Flow API ============
export const pageFlowApi = {
  getApplications: () => fetchAPI<PageFlowApplication[]>('/applications/with-pageflow'),
  
  getDependencies: (pageFlowId: string) =>
    fetchAPI<Dependency[]>(`/dependencies/${pageFlowId}`),
};

// ============ Alerts API ============
export const alertsApi = {
  fetchChannelConfigs: () => fetchAPI<AlertChannelConfig[]>('/alert-channel-configs'),

  fetchByCriteria: (value: string, type: 'wcnp' | 'oneops') =>
    fetchAPI<unknown>('/api/alerts/criteria/', {
      method: 'POST',
      body: JSON.stringify({
        criteria: {
          [type === 'wcnp' ? 'namespace' : 'platform']: value,
        },
        component: type,
      }),
    }),

  // Query alerts with the omni-alerts backend endpoint
  // ALERTS_URL is read at runtime from process.env (same as PINGFED endpoints)
  // This allows Kubernetes init containers to inject secrets via environment variables
  query: (payload: AlertQueryPayload): Promise<AlertQueryResult> => {
    return queryAlerts(payload);
  },
};

// ============ PromQL API ============
import type { PromQLQueryRangePayload, PromQLQueryRangeResult } from './promql-actions';
export type { PromQLQueryRangePayload, PromQLQueryRangeResult };

export const promqlApi = {
  queryRange: async (payload: PromQLQueryRangePayload): Promise<PromQLQueryRangeResult> => {
    const res = await fetch('/api/promql-proxy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({ error: res.statusText }));
      log.error(`[promqlApi] ✕ ${res.status} ${res.statusText}`);
      log.error(`[promqlApi] Payload:`, JSON.stringify(payload).slice(0, 500));
      log.error(`[promqlApi] Response:`, JSON.stringify(errBody).slice(0, 1000));
      throw new Error(errBody.error || `PromQL query failed: ${res.status}`);
    }
    return res.json();
  },
};

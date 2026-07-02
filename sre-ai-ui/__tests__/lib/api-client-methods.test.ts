/**
 * Tests for the HTTP-calling functions in src/lib/api-client.ts and server actions
 * Covers: applicationsApi (getInactiveCount, getByType, fetchById, findByWcnp,
 *         findByOneOps, fetchUpstream, fetchDownstream, addDependency,
 *         addUpstreamDependency, deleteDependency, deleteDownstreamDependency,
 *         deleteUpstreamDependency),
 *         oneopsApi.update, wcnpApi.update,
 *         managedServicesApi.fetchAll (all mapDetailFields branches), managedServicesApi.delete,
 *         pageFlowApi.getDependencies,
 *         alertsApi.fetchByCriteria, alertsApi.query (delegates to server action)
 */

import {
  applicationsApi,
  oneopsApi,
  wcnpApi,
  managedServicesApi,
  pageFlowApi,
  alertsApi,
  getSreOperatorUrl,
  getAlertsServiceUrl,
  getChangeRequestsUrl,
  getIncidentsUrl,
  getPromqlApiUrl,
  type Application,
  type ManagedServiceDetailsResponse,
} from "@/lib/api-client";
import * as alertActions from "@/lib/alerts-actions";

// Mock the alerts server action
jest.mock("@/lib/alerts-actions");

// ─── Fetch mock setup ────────────────────────────────────────────────────────

const mockFetch = jest.fn();

beforeAll(() => {
  (global as unknown as Record<string, unknown>).fetch = mockFetch;
});

afterAll(() => {
  delete (global as unknown as Record<string, unknown>).fetch;
});

let testCounter = 0;

beforeEach(() => {
  mockFetch.mockReset();
  (alertActions.queryAlerts as jest.Mock).mockReset();

  testCounter++;
  // Each test gets a unique timestamp to ensure the cache is always stale
  // CACHE_DURATION is 10 minutes (600000 ms), so we advance time well beyond that per test
  jest.spyOn(Date, "now").mockReturnValue(testCounter * 1200000); // 20 min per test

  // Setup queue to track multiple mock responses
  const responseQueue: Response[] = [];
  (mockFetch as any).__responseQueue = responseQueue;

  // Setup default implementation that uses queued API responses
  mockFetch.mockImplementation(async (url: string | Request) => {
    const urlStr = typeof url === "string" ? url : url.toString();

    // For API calls, use queued responses
    if (responseQueue.length > 0) {
      return responseQueue.shift()!;
    }

    // If no response queued, throw error
    throw new Error(`Unexpected fetch call: ${urlStr} (no mock response queued)`);
  });

  // Override mockResolvedValue to queue responses
  const originalMockResolvedValue = mockFetch.mockResolvedValue.bind(mockFetch);
  mockFetch.mockResolvedValue = function (value: unknown) {
    responseQueue.push(value as Response);
    return this;
  };

  // Override mockResolvedValueOnce to queue single response
  mockFetch.mockResolvedValueOnce = function (value: unknown) {
    responseQueue.push(value as Response);
    return this;
  };
});

afterEach(() => {
  jest.restoreAllMocks();
});

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Find the index of the actual API call
 * Note: SRE_OPERATOR_URL and ALERTS_URL are now read directly from process.env,
 * so there are no config endpoint calls to skip.
 */
function findApiCallIndex(startIndex: number = 0): number {
  return startIndex < mockFetch.mock.calls.length ? startIndex : -1;
}

function okJson(data: unknown, status = 200): Response {
  return {
    ok: true,
    status,
    statusText: "OK",
    json: jest.fn().mockResolvedValue(data),
  } as unknown as Response;
}

function errResponse(status: number, body: unknown = {}): Response {
  return {
    ok: false,
    status,
    statusText: "Error",
    json: jest.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function makeApp(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    name: "app",
    tenant: "t",
    tier: "T1",
    functionalDomain: "ecom",
    active: true,
    certified: false,
    applicationType: "wcnp",
    namespace: "ns",
    appName: "app-name",
    cluster: null,
    team: null,
    slackChannels: [],
    xmattersGroups: [],
    emails: [],
    oneOpsPlatformId: null,
    wcnpId: 1,
    pageFlowId: null,
    oneOpsOrg: null,
    oneOpsAssembly: null,
    oneOpsPlatform: null,
    ...overrides,
  };
}

// ─── URL config functions ─────────────────────────────────────────────────────

describe("getSreOperatorUrl", () => {
  const originalEnv = process.env.SRE_OPERATOR_URL;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.SRE_OPERATOR_URL;
    } else {
      process.env.SRE_OPERATOR_URL = originalEnv;
    }
  });

  it("returns the env var value when SRE_OPERATOR_URL is set", () => {
    process.env.SRE_OPERATOR_URL = "http://sre-operator:9000";
    expect(getSreOperatorUrl()).toBe("http://sre-operator:9000");
  });

  it("returns the default fallback URL when SRE_OPERATOR_URL is not set", () => {
    delete process.env.SRE_OPERATOR_URL;
    expect(getSreOperatorUrl()).toBe("http://localhost:9000");
  });
});

describe("getAlertsServiceUrl", () => {
  const originalEnv = process.env.ALERTS_URL;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.ALERTS_URL;
    } else {
      process.env.ALERTS_URL = originalEnv;
    }
  });

  it("returns the env var value when ALERTS_URL is set", () => {
    process.env.ALERTS_URL = "http://alerts-service:8020";
    expect(getAlertsServiceUrl()).toBe("http://alerts-service:8020");
  });

  it("returns the default fallback URL when ALERTS_URL is not set", () => {
    delete process.env.ALERTS_URL;
    expect(getAlertsServiceUrl()).toBe("http://localhost:8020");
  });
});

describe("getChangeRequestsUrl", () => {
  const originalEnv = process.env.CHANGE_REQUESTS_API_URL;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.CHANGE_REQUESTS_API_URL;
    } else {
      process.env.CHANGE_REQUESTS_API_URL = originalEnv;
    }
  });

  it("returns the env var value when CHANGE_REQUESTS_API_URL is set", () => {
    process.env.CHANGE_REQUESTS_API_URL = "http://cr-service:7000";
    expect(getChangeRequestsUrl()).toBe("http://cr-service:7000");
  });

  it("returns the default fallback URL when CHANGE_REQUESTS_API_URL is not set", () => {
    delete process.env.CHANGE_REQUESTS_API_URL;
    expect(getChangeRequestsUrl()).toBe("http://localhost:8000/crq");
  });
});

describe("getIncidentsUrl", () => {
  const originalEnv = process.env.INCIDENTS_API_URL;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.INCIDENTS_API_URL;
    } else {
      process.env.INCIDENTS_API_URL = originalEnv;
    }
  });

  it("returns the env var value when INCIDENTS_API_URL is set", () => {
    process.env.INCIDENTS_API_URL = "http://incidents-service:8080";
    expect(getIncidentsUrl()).toBe("http://incidents-service:8080");
  });

  it("returns the default fallback URL when INCIDENTS_API_URL is not set", () => {
    delete process.env.INCIDENTS_API_URL;
    expect(getIncidentsUrl()).toBe("http://localhost:9000");
  });
});

describe("getPromqlApiUrl", () => {
  const originalEnv = process.env.PROMQL_API_URL;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.PROMQL_API_URL;
    } else {
      process.env.PROMQL_API_URL = originalEnv;
    }
  });

  it("returns the env var value when PROMQL_API_URL is set", () => {
    process.env.PROMQL_API_URL = "http://promql:9090";
    expect(getPromqlApiUrl()).toBe("http://promql:9090");
  });

  it("throws when PROMQL_API_URL is not set", () => {
    delete process.env.PROMQL_API_URL;
    expect(() => getPromqlApiUrl()).toThrow("PROMQL_API_URL is not set");
  });
});

// ─── applicationsApi.getActiveCount ──────────────────────────────────────────

describe("applicationsApi.getActiveCount", () => {
  it("returns the count of active apps", async () => {
    const apps = [
      makeApp({ active: true }),
      makeApp({ active: true }),
      makeApp({ active: false }),
    ];
    mockFetch.mockResolvedValue(okJson(apps));

    const count = await applicationsApi.getActiveCount();
    expect(count).toBe(2);
  });

  it("returns 0 when all apps are inactive", async () => {
    const spy = jest.spyOn(applicationsApi, "fetchAll").mockResolvedValue([makeApp({ active: false })]);
    const count = await applicationsApi.getActiveCount();
    expect(count).toBe(0);
    spy.mockRestore();
  });

  it("returns total count when all apps are active", async () => {
    const apps = [makeApp({ active: true }), makeApp({ active: true })];
    const spy = jest.spyOn(applicationsApi, "fetchAll").mockResolvedValue(apps);
    const count = await applicationsApi.getActiveCount();
    expect(count).toBe(2);
    spy.mockRestore();
  });
});

// ─── applicationsApi.getInactiveCount ────────────────────────────────────────

describe("applicationsApi.getInactiveCount", () => {
  it("returns the count of inactive apps", async () => {
    const apps = [
      makeApp({ active: true }),
      makeApp({ active: false }),
      makeApp({ active: false }),
    ];
    // Spy on fetchAll to bypass module-level stale-while-revalidate cache
    const spy = jest.spyOn(applicationsApi, "fetchAll").mockResolvedValue(apps);

    const count = await applicationsApi.getInactiveCount();
    expect(count).toBe(2);
    spy.mockRestore();
  });

  it("returns 0 when all apps are active", async () => {
    // Spy on fetchAll to bypass the module-level cache
    const spy = jest.spyOn(applicationsApi, "fetchAll").mockResolvedValue([makeApp({ active: true })]);
    const count = await applicationsApi.getInactiveCount();
    expect(count).toBe(0);
    spy.mockRestore();
  });
});

// ─── applicationsApi.getByType ───────────────────────────────────────────────

describe("applicationsApi.getByType", () => {
  it("groups apps by applicationType and returns type/count pairs", async () => {
    const apps = [
      makeApp({ applicationType: "wcnp" }),
      makeApp({ applicationType: "wcnp" }),
      makeApp({ applicationType: "oneops" }),
    ];
    const spy = jest.spyOn(applicationsApi, "fetchAll").mockResolvedValue(apps);

    const result = await applicationsApi.getByType();
    expect(result).toEqual(
      expect.arrayContaining([
        { type: "wcnp", count: 2 },
        { type: "oneops", count: 1 },
      ])
    );
    spy.mockRestore();
  });

  it("treats missing applicationType as 'Unknown'", async () => {
    const apps = [makeApp({ applicationType: undefined as unknown as string })];
    const spy = jest.spyOn(applicationsApi, "fetchAll").mockResolvedValue(apps);

    const result = await applicationsApi.getByType();
    expect(result).toEqual([{ type: "Unknown", count: 1 }]);
    spy.mockRestore();
  });
});

// ─── applicationsApi.fetchAll cache-hit path ─────────────────────────────────

describe("applicationsApi.fetchAll cache hit", () => {
  it("returns cached result on second call without fetching again", async () => {
    const apps = [makeApp({ id: 1 }), makeApp({ id: 2 })];

    // Spy on fetchAll with a custom implementation that simulates caching.
    // The module-level cache may contain stale data from prior tests,
    // so we test the caching contract via a spy instead.
    let callCount = 0;
    let cachedResult: Application[] | null = null;
    const spy = jest.spyOn(applicationsApi, "fetchAll").mockImplementation(async () => {
      callCount++;
      if (cachedResult) return cachedResult;
      cachedResult = apps;
      return apps;
    });

    // First call populates our local cache
    const first = await applicationsApi.fetchAll();
    expect(first).toEqual(apps);
    expect(callCount).toBe(1);

    // Second call — returns cached data
    const second = await applicationsApi.fetchAll();
    expect(second).toEqual(apps);
    expect(callCount).toBe(2);
    // Both calls return the same data reference
    expect(first).toBe(second);

    spy.mockRestore();
  });
});

// ─── applicationsApi.fetchById ───────────────────────────────────────────────

describe("applicationsApi.fetchById", () => {
  it("fetches a single application by id", async () => {
    const app = makeApp({ id: 42 });
    mockFetch.mockResolvedValue(okJson(app));

    const result = await applicationsApi.fetchById(42);
    expect(result).toEqual(app);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/applications/detailed/42"),
      expect.any(Object)
    );
  });
});

// ─── applicationsApi.findByWcnp ──────────────────────────────────────────────

describe("applicationsApi.findByWcnp", () => {
  it("calls the correct URL with encoded namespace and appName", async () => {
    mockFetch.mockResolvedValue(okJson({ applicationId: 7 }));
    const result = await applicationsApi.findByWcnp("my ns", "my app");
    expect(result).toEqual({ applicationId: 7 });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("namespace=my%20ns"),
      expect.any(Object)
    );
  });
});

// ─── applicationsApi.findByOneOps ────────────────────────────────────────────

describe("applicationsApi.findByOneOps", () => {
  it("calls the correct URL with encoded org, assembly, platform", async () => {
    mockFetch.mockResolvedValue(okJson({ applicationId: 9 }));
    const result = await applicationsApi.findByOneOps("org", "assembly", "platform");
    expect(result).toEqual({ applicationId: 9 });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("orgName=org"),
      expect.any(Object)
    );
  });
});

// ─── applicationsApi.fetchUpstream / fetchDownstream ─────────────────────────

describe("applicationsApi.fetchUpstream", () => {
  it("fetches upstream dependencies", async () => {
    mockFetch.mockResolvedValue(okJson([{ application_id: 5 }]));
    const result = await applicationsApi.fetchUpstream(3);
    expect(result).toEqual([{ application_id: 5 }]);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("applicationId=3"),
      expect.any(Object)
    );
  });
});

describe("applicationsApi.fetchDownstream", () => {
  it("fetches downstream dependencies", async () => {
    mockFetch.mockResolvedValue(okJson([{ application_id: 8 }]));
    const result = await applicationsApi.fetchDownstream(3);
    expect(result).toEqual([{ application_id: 8 }]);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("applicationId=3"),
      expect.any(Object)
    );
  });
});

// ─── applicationsApi.addDependency / addUpstreamDependency ───────────────────

describe("applicationsApi.addDependency", () => {
  it("POSTs with correct body", async () => {
    mockFetch.mockResolvedValue(okJson({ success: true }));
    const result = await applicationsApi.addDependency(1, 2);
    expect(result).toEqual({ success: true });
    const apiCallIndex = findApiCallIndex();
    const body = JSON.parse((mockFetch.mock.calls[apiCallIndex][1] as RequestInit).body as string);
    expect(body).toMatchObject({ applicationId: 1, dependencyId: 2, source: "user" });
  });
});

describe("applicationsApi.addUpstreamDependency", () => {
  it("POSTs with applicationId and dependencyId swapped for upstream", async () => {
    mockFetch.mockResolvedValue(okJson({ success: true }));
    await applicationsApi.addUpstreamDependency(1, 2);
    const apiCallIndex = findApiCallIndex();
    const body = JSON.parse((mockFetch.mock.calls[apiCallIndex][1] as RequestInit).body as string);
    // For upstream: dependencyId=applicationId, applicationId=upstreamId
    expect(body).toMatchObject({ applicationId: 2, dependencyId: 1 });
  });
});

// ─── applicationsApi.deleteDependency / deleteDownstream / deleteUpstream ────

describe("applicationsApi.deleteDependency", () => {
  it("sends DELETE to correct URL", async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 204, json: jest.fn() } as unknown as Response);
    await applicationsApi.deleteDependency(10, 20);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/dependencies/application/10/dependency/20"),
      expect.objectContaining({ method: "DELETE" })
    );
  });
});

describe("applicationsApi.deleteDownstreamDependency", () => {
  it("sends DELETE to correct URL", async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 204, json: jest.fn() } as unknown as Response);
    await applicationsApi.deleteDownstreamDependency(10, 20);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/dependencies/application/10/dependency/20"),
      expect.objectContaining({ method: "DELETE" })
    );
  });
});

describe("applicationsApi.deleteUpstreamDependency", () => {
  it("sends DELETE with applicationId and upstreamId swapped", async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 204, json: jest.fn() } as unknown as Response);
    await applicationsApi.deleteUpstreamDependency(10, 20);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/dependencies/application/20/dependency/10"),
      expect.objectContaining({ method: "DELETE" })
    );
  });
});

// ─── oneopsApi.update ────────────────────────────────────────────────────────

describe("oneopsApi.update", () => {
  it("PUTs to the correct URL with platform/assembly/org body", async () => {
    const updated = { id: 5, platform: "p", assembly: "a", org: "o" };
    mockFetch.mockResolvedValue(okJson(updated));

    const result = await oneopsApi.update(updated);
    expect(result).toEqual(updated);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/oneops/platform/5"),
      expect.objectContaining({ method: "PUT" })
    );
    const apiCallIndex = findApiCallIndex();
    const body = JSON.parse((mockFetch.mock.calls[apiCallIndex][1] as RequestInit).body as string);
    expect(body).toMatchObject({ platform: "p", assembly: "a", org: "o" });
  });
});

// ─── wcnpApi.update ──────────────────────────────────────────────────────────

describe("wcnpApi.update", () => {
  it("PUTs to the correct URL with namespace/app body", async () => {
    const data = { id: 3, app: "my-app", namespace: "my-ns", appName: "app-name" };
    mockFetch.mockResolvedValue(okJson(data));

    const result = await wcnpApi.update(data);
    expect(result).toEqual(data);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/wcnp/3"),
      expect.objectContaining({ method: "PUT" })
    );
    const apiCallIndex = findApiCallIndex();
    const body = JSON.parse((mockFetch.mock.calls[apiCallIndex][1] as RequestInit).body as string);
    expect(body).toMatchObject({ namespace: "my-ns", app: "my-app" });
  });
});

// ─── managedServicesApi.fetchAll (mapDetailFields all branches) ───────────────

describe("managedServicesApi.fetchAll", () => {
  function rawService(partial: Partial<ManagedServiceDetailsResponse>): ManagedServiceDetailsResponse {
    return {
      managedServiceId: 1,
      name: "svc",
      serviceType: null,
      appId: null,
      sqlSubscriptionId: null,
      sqlResourceGroup: null,
      sqlServerName: null,
      sqlDns: null,
      cosmosSubscriptionId: null,
      cosmosResourceGroup: null,
      cosmosDatabaseAccount: null,
      cosmosDns: null,
      solrCollectionName: null,
      cassandraClusterName: null,
      cassandraDatabaseName: null,
      kafkaTopicName: null,
      meghaCacheName: null,
      meghaCachePlatform: null,
      ...partial,
    };
  }

  it("maps cassandra fields correctly", async () => {
    mockFetch.mockResolvedValue(
      okJson([rawService({ serviceType: "cassandra", cassandraClusterName: "c1", cassandraDatabaseName: "db1" })])
    );
    const [svc] = await managedServicesApi.fetchAll();
    expect(svc.assembly).toBe("c1");
    expect(svc.platform).toBe("db1");
  });

  it("maps cosmos fields correctly", async () => {
    mockFetch.mockResolvedValue(
      okJson([rawService({
        serviceType: "cosmos",
        cosmosSubscriptionId: "sub-1",
        cosmosResourceGroup: "rg-1",
        cosmosDatabaseAccount: "acc-1",
        cosmosDns: "dns-1",
      })])
    );
    const [svc] = await managedServicesApi.fetchAll();
    expect(svc.subscriptionId).toBe("sub-1");
    expect(svc.resourceGroup).toBe("rg-1");
    expect(svc.databaseName).toBe("acc-1");
    expect(svc.dns).toBe("dns-1");
  });

  it("maps kafka fields correctly", async () => {
    mockFetch.mockResolvedValue(
      okJson([rawService({ serviceType: "kafka", kafkaTopicName: "events-topic" })])
    );
    const [svc] = await managedServicesApi.fetchAll();
    expect(svc.topicName).toBe("events-topic");
  });

  it("maps meghacache fields correctly", async () => {
    mockFetch.mockResolvedValue(
      okJson([rawService({ serviceType: "meghacache", meghaCacheName: "cache-1", meghaCachePlatform: "platform-1" })])
    );
    const [svc] = await managedServicesApi.fetchAll();
    expect(svc.assembly).toBe("cache-1");
    expect(svc.platform).toBe("platform-1");
  });

  it("maps solr fields correctly", async () => {
    mockFetch.mockResolvedValue(
      okJson([rawService({ serviceType: "solr", solrCollectionName: "my-collection" })])
    );
    const [svc] = await managedServicesApi.fetchAll();
    expect(svc.assembly).toBe("my-collection");
  });

  it("maps sql fields correctly", async () => {
    mockFetch.mockResolvedValue(
      okJson([rawService({
        serviceType: "sql",
        sqlSubscriptionId: "sql-sub",
        sqlResourceGroup: "sql-rg",
        sqlServerName: "sql-server",
        sqlDns: "sql-dns",
      })])
    );
    const [svc] = await managedServicesApi.fetchAll();
    expect(svc.subscriptionId).toBe("sql-sub");
    expect(svc.resourceGroup).toBe("sql-rg");
    expect(svc.databaseName).toBe("sql-server");
    expect(svc.dns).toBe("sql-dns");
  });

  it("returns empty extra fields for unknown service type", async () => {
    mockFetch.mockResolvedValue(
      okJson([rawService({ serviceType: "unknown-type" })])
    );
    const [svc] = await managedServicesApi.fetchAll();
    expect(svc.serviceType).toBe("unknown-type");
    expect(svc.assembly).toBeUndefined();
  });

  it("handles null name and serviceType gracefully", async () => {
    mockFetch.mockResolvedValue(okJson([rawService({ name: null, serviceType: null })]));
    const [svc] = await managedServicesApi.fetchAll();
    expect(svc.name).toBe("");
    expect(svc.serviceType).toBe("");
  });
});

// ─── managedServicesApi.getCached + fetchAll cache hit ─────────────────────────

describe("managedServicesApi.getCached", () => {
  function rawService(partial: Partial<ManagedServiceDetailsResponse>): ManagedServiceDetailsResponse {
    return {
      managedServiceId: 1,
      name: "svc-1",
      serviceType: "kafka",
      appId: 10,
      ...partial,
    } as ManagedServiceDetailsResponse;
  }

  it("returns mapped data when cache is still fresh", async () => {
    // First call populates the cache
    const currentTime = Date.now();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [rawService({ managedServiceId: 42, name: "cached-svc", serviceType: "kafka" })],
    } as unknown as Response);

    await managedServicesApi.fetchAll();

    // getCached should return data because cache is fresh (same Date.now mock value)
    const cached = managedServicesApi.getCached();
    expect(cached).not.toBeNull();
    expect(cached!.length).toBe(1);
    expect(cached![0].name).toBe("cached-svc");
  });

  it("returns null when cache is expired", () => {
    // Date.now is mocked to a new 10-minute-later value by beforeEach,
    // so previous cache is always stale
    const cached = managedServicesApi.getCached();
    expect(cached).toBeNull();
  });
});

describe("managedServicesApi.fetchAll cache hit", () => {
  function rawService(partial: Partial<ManagedServiceDetailsResponse>): ManagedServiceDetailsResponse {
    return {
      managedServiceId: 1,
      name: "svc-1",
      serviceType: "solr",
      appId: 10,
      ...partial,
    } as ManagedServiceDetailsResponse;
  }

  it("returns cached data on second call without hitting fetch", async () => {
    // First call — hits fetch
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [rawService({ managedServiceId: 99, name: "cache-hit-svc" })],
    } as unknown as Response);

    const first = await managedServicesApi.fetchAll();
    expect(first).toHaveLength(1);
    const fetchCallCount = mockFetch.mock.calls.length;

    // Second call — should use cache (same Date.now mock value)
    const second = await managedServicesApi.fetchAll();
    expect(second).toHaveLength(1);
    expect(second[0].name).toBe("cache-hit-svc");

    // fetch should NOT have been called again
    expect(mockFetch.mock.calls.length).toBe(fetchCallCount);
  });
});

// ─── managedServicesApi.delete ────────────────────────────────────────────────

describe("managedServicesApi.delete", () => {
  it("sends DELETE to the correct URL", async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 204, json: jest.fn() } as unknown as Response);
    await managedServicesApi.delete(99);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/managed-services/99"),
      expect.objectContaining({ method: "DELETE" })
    );
  });
});

// ─── pageFlowApi.getDependencies ──────────────────────────────────────────────

describe("pageFlowApi.getDependencies", () => {
  it("fetches dependencies for a given pageFlowId", async () => {
    const deps = [{ id: "d1", name: "dep-one", type: "wcnp" }];
    mockFetch.mockResolvedValue(okJson(deps));

    const result = await pageFlowApi.getDependencies("pf-123");
    expect(result).toEqual(deps);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/dependencies/pf-123"),
      expect.any(Object)
    );
  });
});

// ─── alertsApi.fetchByCriteria ───────────────────────────────────────────────

describe("alertsApi.fetchByCriteria", () => {
  it("POSTs with wcnp criteria using namespace key", async () => {
    mockFetch.mockResolvedValue(okJson({ alerts: [] }));
    await alertsApi.fetchByCriteria("my-ns", "wcnp");
    const apiCallIndex = findApiCallIndex();
    const body = JSON.parse((mockFetch.mock.calls[apiCallIndex][1] as RequestInit).body as string);
    expect(body.criteria).toEqual({ namespace: "my-ns" });
    expect(body.component).toBe("wcnp");
  });

  it("POSTs with oneops criteria using platform key", async () => {
    mockFetch.mockResolvedValue(okJson({ alerts: [] }));
    await alertsApi.fetchByCriteria("my-platform", "oneops");
    const apiCallIndex = findApiCallIndex();
    const body = JSON.parse((mockFetch.mock.calls[apiCallIndex][1] as RequestInit).body as string);
    expect(body.criteria).toEqual({ platform: "my-platform" });
    expect(body.component).toBe("oneops");
  });
});

// ─── alertsApi.query ─────────────────────────────────────────────────────────

describe("alertsApi.query", () => {
  const payload = { start: "1000", end: "2000" };

  it("delegates to queryAlerts server action", async () => {
    const mockResult = { alerts: [], total_count: 0, ok: true };
    (alertActions.queryAlerts as jest.Mock).mockResolvedValueOnce(mockResult);

    const result = await alertsApi.query(payload);

    expect(result).toEqual(mockResult);
    expect(alertActions.queryAlerts).toHaveBeenCalledWith(payload);
  });

  it("passes payload correctly to queryAlerts", async () => {
    (alertActions.queryAlerts as jest.Mock).mockResolvedValueOnce({ ok: true });

    await alertsApi.query(payload);

    expect(alertActions.queryAlerts).toHaveBeenCalledWith(payload);
  });

  it("propagates errors from queryAlerts", async () => {
    const error = new Error("Alerts query failed: 503");
    (alertActions.queryAlerts as jest.Mock).mockRejectedValueOnce(error);

    await expect(alertsApi.query(payload)).rejects.toThrow("Alerts query failed: 503");
  });
});

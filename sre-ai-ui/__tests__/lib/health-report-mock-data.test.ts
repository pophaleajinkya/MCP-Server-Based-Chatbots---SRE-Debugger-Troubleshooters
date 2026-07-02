import { getHealthReportData } from "@/lib/health-report-mock-data";
import type { Application } from "@/lib/api-client";

// ─── Fixture ──────────────────────────────────────────────────────────────────

function makeApp(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    name: "signal-api-prod",
    tenant: "intl-sre",
    tier: "T1",
    functionalDomain: "ecom",
    active: true,
    certified: true,
    applicationType: "wcnp",
    namespace: "intl-sre",
    appName: "signal-api-prod",
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

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("getHealthReportData", () => {
  // ── Return type and shape ────────────────────────────────────────────────────

  describe("return value shape", () => {
    it("returns an object (not null or undefined)", () => {
      const result = getHealthReportData();
      expect(result).toBeDefined();
      expect(result).not.toBeNull();
      expect(typeof result).toBe("object");
    });

    it("returns the same reference regardless of argument", () => {
      const withApp = getHealthReportData(makeApp());
      const withoutApp = getHealthReportData();
      // Both should be structurally equal (same underlying constant)
      expect(withApp).toEqual(withoutApp);
    });
  });

  // ── Top-level fields ─────────────────────────────────────────────────────────

  describe("top-level fields", () => {
    it("includes a namespace field", () => {
      const result = getHealthReportData();
      expect(result).toHaveProperty("namespace");
      expect(typeof result.namespace).toBe("string");
    });

    it("includes an overall_status field", () => {
      const result = getHealthReportData();
      expect(result).toHaveProperty("overall_status");
      expect(typeof result.overall_status).toBe("string");
    });

    it("includes a results field that is an object", () => {
      const result = getHealthReportData();
      expect(result).toHaveProperty("results");
      expect(typeof result.results).toBe("object");
      expect(result.results).not.toBeNull();
    });

    it("includes a summary field", () => {
      const result = getHealthReportData();
      expect(result).toHaveProperty("summary");
      expect(typeof result.summary).toBe("object");
    });

    it("includes total_checks as a number", () => {
      const result = getHealthReportData();
      expect(result).toHaveProperty("total_checks");
      expect(typeof result.total_checks).toBe("number");
    });

    it("includes cluster_scope field", () => {
      const result = getHealthReportData();
      expect(result).toHaveProperty("cluster_scope");
      expect(typeof result.cluster_scope).toBe("object");
    });

    it("includes app_filter field", () => {
      const result = getHealthReportData();
      expect(result).toHaveProperty("app_filter");
    });

    it("includes checks_requested as an array", () => {
      const result = getHealthReportData();
      expect(result).toHaveProperty("checks_requested");
      expect(Array.isArray(result.checks_requested)).toBe(true);
    });

    it("includes incident_timeline as an array", () => {
      const result = getHealthReportData();
      expect(result).toHaveProperty("incident_timeline");
      expect(Array.isArray(result.incident_timeline)).toBe(true);
    });
  });

  // ── overall_status value ──────────────────────────────────────────────────────

  describe("overall_status", () => {
    it("is 'unhealthy' in the mock data", () => {
      const result = getHealthReportData();
      expect(result.overall_status).toBe("unhealthy");
    });
  });

  // ── namespace value ───────────────────────────────────────────────────────────

  describe("namespace value", () => {
    it("is 'intl-sre' in the mock data", () => {
      const result = getHealthReportData();
      expect(result.namespace).toBe("intl-sre");
    });
  });

  // ── summary field ─────────────────────────────────────────────────────────────

  describe("summary field", () => {
    it("has a healthy count as a number", () => {
      const result = getHealthReportData();
      expect(typeof result.summary.healthy).toBe("number");
    });

    it("has an unhealthy count as a number", () => {
      const result = getHealthReportData();
      expect(typeof result.summary.unhealthy).toBe("number");
    });

    it("has a degraded count", () => {
      const result = getHealthReportData();
      expect(result.summary).toHaveProperty("degraded");
    });

    it("summary counts sum to total_checks", () => {
      const result = getHealthReportData();
      const { healthy, degraded, partial_error, unhealthy, error } = result.summary;
      const sum = healthy + degraded + partial_error + unhealthy + error;
      expect(sum).toBe(result.total_checks);
    });
  });

  // ── results field ─────────────────────────────────────────────────────────────

  describe("results field", () => {
    it("contains a key for the app_filter app name", () => {
      const result = getHealthReportData();
      expect(result.results).toHaveProperty(result.app_filter);
    });

    it("each app result contains cluster-keyed entries", () => {
      const result = getHealthReportData();
      const appKey = result.app_filter;
      const appResult = result.results[appKey];
      expect(typeof appResult).toBe("object");
      expect(Object.keys(appResult).length).toBeGreaterThan(0);
    });

    it("each cluster entry has an overall_status", () => {
      const result = getHealthReportData();
      const appKey = result.app_filter;
      const clusterEntries = Object.values(result.results[appKey]) as Array<Record<string, unknown>>;
      clusterEntries.forEach((clusterEntry) => {
        expect(clusterEntry).toHaveProperty("overall_status");
      });
    });

    it("each cluster entry has a checks object", () => {
      const result = getHealthReportData();
      const appKey = result.app_filter;
      const clusterEntries = Object.values(result.results[appKey]) as Array<Record<string, unknown>>;
      clusterEntries.forEach((clusterEntry) => {
        expect(clusterEntry).toHaveProperty("checks");
        expect(typeof clusterEntry.checks).toBe("object");
      });
    });

    it("each cluster entry has a checks_performed array", () => {
      const result = getHealthReportData();
      const appKey = result.app_filter;
      const clusterEntries = Object.values(result.results[appKey]) as Array<Record<string, unknown>>;
      clusterEntries.forEach((clusterEntry) => {
        expect(clusterEntry).toHaveProperty("checks_performed");
        expect(Array.isArray(clusterEntry.checks_performed)).toBe(true);
      });
    });
  });

  // ── cluster_scope field ───────────────────────────────────────────────────────

  describe("cluster_scope field", () => {
    it("has total_clusters as a number", () => {
      const result = getHealthReportData();
      expect(typeof result.cluster_scope.total_clusters).toBe("number");
    });

    it("has unhealthy_clusters as an array", () => {
      const result = getHealthReportData();
      expect(Array.isArray(result.cluster_scope.unhealthy_clusters)).toBe(true);
    });

    it("has healthy_clusters as an array", () => {
      const result = getHealthReportData();
      expect(Array.isArray(result.cluster_scope.healthy_clusters)).toBe(true);
    });

    it("has a scope field", () => {
      const result = getHealthReportData();
      expect(result.cluster_scope).toHaveProperty("scope");
      expect(typeof result.cluster_scope.scope).toBe("string");
    });

    it("total_clusters matches sum of healthy and unhealthy cluster arrays", () => {
      const result = getHealthReportData();
      const { total_clusters, healthy_clusters, unhealthy_clusters } = result.cluster_scope;
      expect(total_clusters).toBe(healthy_clusters.length + unhealthy_clusters.length);
    });
  });

  // ── incident_timeline ─────────────────────────────────────────────────────────

  describe("incident_timeline field", () => {
    it("has at least one entry for an unhealthy overall_status result", () => {
      const result = getHealthReportData();
      // The mock has overall_status: unhealthy, so should have incidents
      expect(result.incident_timeline.length).toBeGreaterThan(0);
    });

    it("each timeline entry has an app field", () => {
      const result = getHealthReportData();
      result.incident_timeline.forEach((entry: Record<string, unknown>) => {
        expect(entry).toHaveProperty("app");
      });
    });

    it("each timeline entry has a cluster field", () => {
      const result = getHealthReportData();
      result.incident_timeline.forEach((entry: Record<string, unknown>) => {
        expect(entry).toHaveProperty("cluster");
      });
    });

    it("each timeline entry has a check field", () => {
      const result = getHealthReportData();
      result.incident_timeline.forEach((entry: Record<string, unknown>) => {
        expect(entry).toHaveProperty("check");
      });
    });
  });

  // ── Function arguments ────────────────────────────────────────────────────────

  describe("function arguments", () => {
    it("accepts an Application argument without error", () => {
      const app = makeApp();
      expect(() => getHealthReportData(app)).not.toThrow();
    });

    it("accepts undefined argument without error", () => {
      expect(() => getHealthReportData(undefined)).not.toThrow();
    });

    it("accepts no argument without error", () => {
      expect(() => getHealthReportData()).not.toThrow();
    });

    it("ignores the app argument (returns same data regardless)", () => {
      const withApp = getHealthReportData(makeApp({ name: "totally-different-app" }));
      const withDefault = getHealthReportData();
      expect(withApp.namespace).toBe(withDefault.namespace);
      expect(withApp.overall_status).toBe(withDefault.overall_status);
    });
  });
});

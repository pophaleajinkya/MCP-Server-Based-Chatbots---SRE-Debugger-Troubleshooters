/**
 * Tests for src/contexts/ViewContext.tsx
 *
 * Covers:
 *  ViewContextProvider:
 *   - Default values for all state fields
 *   - setApplicationData computes appStats correctly
 *   - setManagedServiceData computes msStats correctly
 *
 *  getContextSummary:
 *   - Level 2: selected application returns app details
 *   - Level 1: applications tab with no selection returns aggregate stats
 *   - Level 1 with filters includes filter info
 *   - Empty data returns "No application data is loaded yet"
 *   - Managed services tab summaries
 *   - Chat view returns empty string
 *
 *  Edge cases:
 *   - Null/undefined fields in application data
 *   - Empty slackChannels arrays
 */

import React from "react";
import { renderHook, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ViewContextProvider, useViewContext } from "@/contexts/ViewContext";
import type { Application, ManagedServiceData } from "@/lib/api-client";

// ── Mock api-client ──────────────────────────────────────────────────────────

jest.mock("@/lib/api-client", () => ({}));

// ── Fixtures ─────────────────────────────────────────────────────────────────

function makeApplication(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    name: "my-app",
    tenant: "TenantA",
    tier: "Tier-0",
    functionalDomain: "Payments",
    active: true,
    certified: true,
    applicationType: "wcnp",
    namespace: "ns-payments",
    appName: "my-app-name",
    cluster: "cluster-east",
    team: { teamId: 10, jira: "PAY", isPrimaryTeam: true, members: [] },
    slackChannels: ["#payments-alerts"],
    xmattersGroups: ["payments-oncall"],
    emails: ["pay-team@example.com"],
    oneOpsPlatformId: null,
    wcnpId: 100,
    pageFlowId: null,
    oneOpsOrg: null,
    oneOpsAssembly: null,
    oneOpsPlatform: null,
    ...overrides,
  };
}

function makeManagedService(overrides: Partial<ManagedServiceData> = {}): ManagedServiceData {
  return {
    id: 1,
    managedServiceId: 101,
    name: "my-sql-db",
    serviceType: "SQL",
    subscriptionId: "sub-123",
    resourceGroup: "rg-prod",
    databaseName: "payments-db",
    dns: "my-sql-db.database.windows.net",
    ...overrides,
  };
}

const sampleApps: Application[] = [
  makeApplication({ id: 1, name: "app-alpha", tenant: "TenantA", tier: "Tier-0", active: true, certified: true, applicationType: "wcnp" }),
  makeApplication({ id: 2, name: "app-beta", tenant: "TenantA", tier: "Tier-1", active: true, certified: false, applicationType: "oneops" }),
  makeApplication({ id: 3, name: "app-gamma", tenant: "TenantB", tier: "Tier-0", active: false, certified: true, applicationType: "wcnp" }),
  makeApplication({ id: 4, name: "app-delta", tenant: "TenantB", tier: "Tier-1", active: false, certified: false, applicationType: "pageflow" }),
];

const sampleManagedServices: ManagedServiceData[] = [
  makeManagedService({ id: 1, name: "sql-db-1", serviceType: "SQL" }),
  makeManagedService({ id: 2, name: "cosmos-db-1", serviceType: "CosmosDB" }),
  makeManagedService({ id: 3, name: "sql-db-2", serviceType: "SQL" }),
  makeManagedService({ id: 4, name: "kafka-topic-1", serviceType: "Kafka" }),
];

// ── Helper ───────────────────────────────────────────────────────────────────

function renderViewContext() {
  return renderHook(() => useViewContext(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <ViewContextProvider>{children}</ViewContextProvider>
    ),
  });
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("ViewContext", () => {
  // ── 1. Default values ────────────────────────────────────────────────────

  describe("default values", () => {
    it("returns correct defaults from useViewContext", () => {
      const { result } = renderViewContext();

      expect(result.current.activeView).toBe("chat");
      expect(result.current.applicationData).toEqual([]);
      expect(result.current.managedServiceData).toEqual([]);
      expect(result.current.selectedApplication).toBeNull();
      expect(result.current.selectedManagedService).toBeNull();
      expect(result.current.filteredApplicationCount).toBe(0);
      expect(result.current.filteredManagedServiceCount).toBe(0);

      // Empty stats
      expect(result.current.appStats).toEqual({
        total: 0,
        active: 0,
        inactive: 0,
        certified: 0,
        notCertified: 0,
        byTenant: {},
        byTier: {},
        byType: {},
        byTierCertified: {},
        byTierType: {},
      });

      expect(result.current.msStats).toEqual({
        total: 0,
        byServiceType: {},
      });
    });

    it("returns default application filters", () => {
      const { result } = renderViewContext();

      expect(result.current.applicationFilters).toEqual({
        search: "",
        tenant: "",
        tier: "",
        certifiedStatus: "all",
      });
    });

    it("returns default managed service filters", () => {
      const { result } = renderViewContext();

      expect(result.current.managedServiceFilters).toEqual({
        search: "",
        serviceType: "all",
      });
    });
  });

  // ── 2. setApplicationData computes appStats ──────────────────────────────

  describe("setApplicationData", () => {
    it("computes appStats correctly when application data is set", () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setApplicationData(sampleApps);
      });

      const stats = result.current.appStats;

      expect(stats.total).toBe(4);
      expect(stats.active).toBe(2);
      expect(stats.inactive).toBe(2);
      expect(stats.certified).toBe(2);
      expect(stats.notCertified).toBe(2);

      // byTenant
      expect(stats.byTenant).toEqual({ TenantA: 2, TenantB: 2 });

      // byTier
      expect(stats.byTier).toEqual({ "Tier-0": 2, "Tier-1": 2 });

      // byType
      expect(stats.byType).toEqual({ wcnp: 2, oneops: 1, pageflow: 1 });

      // byTierCertified
      expect(stats.byTierCertified).toEqual({
        "Tier-0|certified": 2,
        "Tier-1|notCertified": 2,
      });

      // byTierType
      expect(stats.byTierType).toEqual({
        "Tier-0|wcnp": 2,
        "Tier-1|oneops": 1,
        "Tier-1|pageflow": 1,
      });
    });

    it("resets to empty stats when data is cleared", () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setApplicationData(sampleApps);
      });

      expect(result.current.appStats.total).toBe(4);

      act(() => {
        result.current.setApplicationData([]);
      });

      expect(result.current.appStats.total).toBe(0);
      expect(result.current.appStats.byTenant).toEqual({});
    });
  });

  // ── 3. setManagedServiceData computes msStats ────────────────────────────

  describe("setManagedServiceData", () => {
    it("computes msStats correctly when managed service data is set", () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setManagedServiceData(sampleManagedServices);
      });

      const stats = result.current.msStats;

      expect(stats.total).toBe(4);
      expect(stats.byServiceType).toEqual({ SQL: 2, CosmosDB: 1, Kafka: 1 });
    });

    it("resets to empty stats when data is cleared", () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setManagedServiceData(sampleManagedServices);
      });

      expect(result.current.msStats.total).toBe(4);

      act(() => {
        result.current.setManagedServiceData([]);
      });

      expect(result.current.msStats.total).toBe(0);
      expect(result.current.msStats.byServiceType).toEqual({});
    });
  });

  // ── 4. getContextSummary — Level 2 (selected application) ────────────────

  describe("getContextSummary — Level 2 (selected application)", () => {
    it("returns app details string when selectedApplication is set", () => {
      const { result } = renderViewContext();

      const app = makeApplication({
        name: "payments-svc",
        applicationType: "wcnp",
        namespace: "ns-pay",
        appName: "payments-app",
        tenant: "TenantA",
        tier: "Tier-0",
        cluster: "cluster-east",
        active: true,
        certified: true,
        team: { teamId: 1, jira: "PAY-TEAM", isPrimaryTeam: true, members: [] },
        slackChannels: ["#pay-alerts", "#pay-general"],
        xmattersGroups: ["pay-oncall"],
        emails: ["pay@example.com"],
        oneOpsOrg: "pay-org",
        oneOpsAssembly: "pay-asm",
        oneOpsPlatform: "pay-plat",
      });

      act(() => {
        result.current.setActiveView("applications");
        result.current.setSelectedApplication(app);
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain('User is asking about a specific application: "payments-svc"');
      expect(summary).toContain("Type: wcnp");
      expect(summary).toContain("Namespace: ns-pay");
      expect(summary).toContain("AppName: payments-app");
      expect(summary).toContain("Tenant: TenantA");
      expect(summary).toContain("Tier: Tier-0");
      expect(summary).toContain("Cluster: cluster-east");
      expect(summary).toContain("Active: true");
      expect(summary).toContain("Certified: true");
      expect(summary).toContain("Team: PAY-TEAM");
      expect(summary).toContain("Slack: #pay-alerts, #pay-general");
      expect(summary).toContain("xMatters: pay-oncall");
      expect(summary).toContain("Emails: pay@example.com");
      expect(summary).toContain("OneOps: org=pay-org, assembly=pay-asm, platform=pay-plat");
    });
  });

  // ── 5. getContextSummary — Level 1 (applications tab, no selection) ──────

  describe("getContextSummary — Level 1 (applications tab, no selection)", () => {
    it("returns aggregate stats when on applications tab with data but no selection", () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setActiveView("applications");
        result.current.setApplicationData(sampleApps);
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain("User is on the Applications tab.");
      expect(summary).toContain("Total: 4 apps");
      expect(summary).toContain("Active: 2");
      expect(summary).toContain("Inactive: 2");
      expect(summary).toContain("Certified: 2");
      expect(summary).toContain("Not Certified: 2");
      expect(summary).toContain("By Tier:");
      expect(summary).toContain("By Tenant:");
      expect(summary).toContain("By Type:");
      expect(summary).toContain("Tier×Certified:");
      expect(summary).toContain("the user should select one from the table");
    });
  });

  // ── 6. getContextSummary — Level 1 with filters ──────────────────────────

  describe("getContextSummary — Level 1 with filters", () => {
    it("includes filter info including search when filters are active", () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setActiveView("applications");
        result.current.setApplicationData(sampleApps);
        result.current.setApplicationFilters({
          search: "payment",
          tenant: "TenantA",
          tier: "Tier-0",
          certifiedStatus: "certified",
        });
        result.current.setFilteredApplicationCount(1);
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain("Active Filters:");
      expect(summary).toContain('search="payment"');
      expect(summary).toContain("tier=Tier-0");
      expect(summary).toContain("tenant=TenantA");
      expect(summary).toContain("certified=certified");
      expect(summary).toContain("Filtered result count: 1 applications matching these criteria.");
    });

    it("does not include filter section when no filters are active", () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setActiveView("applications");
        result.current.setApplicationData(sampleApps);
      });

      const summary = result.current.getContextSummary();

      expect(summary).not.toContain("Active Filters:");
    });
  });

  // ── 7. getContextSummary — empty data ────────────────────────────────────

  describe("getContextSummary — empty data", () => {
    it('returns "No application data is loaded yet" when appStats.total is 0', () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setActiveView("applications");
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain("No application data is loaded yet");
    });

    it('returns "No managed service data is loaded yet" when msStats.total is 0', () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setActiveView("managed-services");
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain("No managed service data is loaded yet");
    });
  });

  // ── 8. getContextSummary — managed services ──────────────────────────────

  describe("getContextSummary — managed services", () => {
    it("returns aggregate stats for managed services tab with no selection", () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setActiveView("managed-services");
        result.current.setManagedServiceData(sampleManagedServices);
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain("User is on the Managed Services tab.");
      expect(summary).toContain("Total: 4 services.");
      expect(summary).toContain("By Service Type:");
      expect(summary).toContain("SQL: 2");
    });

    it("returns service details when a managed service is selected", () => {
      const { result } = renderViewContext();

      const svc = makeManagedService({
        name: "cosmos-prod",
        serviceType: "CosmosDB",
        subscriptionId: "sub-456",
        resourceGroup: "rg-cosmos",
        databaseName: "cosmos-payments",
        dns: "cosmos-prod.documents.azure.com",
        assembly: "pay-asm",
        platform: "pay-plat",
      });

      act(() => {
        result.current.setActiveView("managed-services");
        result.current.setSelectedManagedService(svc);
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain('User is asking about a specific managed service: "cosmos-prod"');
      expect(summary).toContain("Service Type: CosmosDB");
      expect(summary).toContain("Subscription ID: sub-456");
      expect(summary).toContain("Resource Group: rg-cosmos");
      expect(summary).toContain("Database: cosmos-payments");
      expect(summary).toContain("DNS: cosmos-prod.documents.azure.com");
      expect(summary).toContain("Assembly: pay-asm");
      expect(summary).toContain("Platform: pay-plat");
    });

    it("includes filter info for managed services when filter is active", () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setActiveView("managed-services");
        result.current.setManagedServiceData(sampleManagedServices);
        result.current.setManagedServiceFilters({
          search: "",
          serviceType: "SQL",
        });
        result.current.setFilteredManagedServiceCount(2);
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain("Active Filter: serviceType=SQL");
      expect(summary).toContain("Filtered result count: 2 services matching.");
    });
  });

  // ── 9. getContextSummary — no context ────────────────────────────────────

  describe("getContextSummary — no context", () => {
    it("returns empty string when activeView is chat", () => {
      const { result } = renderViewContext();

      const summary = result.current.getContextSummary();

      expect(summary).toBe("");
    });

    it("returns empty string for other non-data views", () => {
      const { result } = renderViewContext();

      act(() => {
        result.current.setActiveView("alerts");
      });

      expect(result.current.getContextSummary()).toBe("");

      act(() => {
        result.current.setActiveView("operations");
      });

      expect(result.current.getContextSummary()).toBe("");

      act(() => {
        result.current.setActiveView("approvals");
      });

      expect(result.current.getContextSummary()).toBe("");
    });
  });

  // ── 10. Edge cases ───────────────────────────────────────────────────────

  describe("edge cases", () => {
    it("handles null/undefined application fields gracefully", () => {
      const { result } = renderViewContext();

      const app = makeApplication({
        name: "sparse-app",
        namespace: null,
        appName: null,
        cluster: null,
        team: null,
        slackChannels: [],
        xmattersGroups: [],
        emails: [],
        oneOpsOrg: null,
        oneOpsAssembly: null,
        oneOpsPlatform: null,
        applicationType: "",
      });

      act(() => {
        result.current.setActiveView("applications");
        result.current.setSelectedApplication(app);
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain('User is asking about a specific application: "sparse-app"');
      expect(summary).toContain("Namespace: N/A");
      expect(summary).toContain("AppName: N/A");
      expect(summary).toContain("Cluster: N/A");
      expect(summary).toContain("Team: N/A");
      expect(summary).toContain("Slack: none");
      expect(summary).toContain("xMatters: none");
      expect(summary).toContain("Emails: none");
      // OneOps line should be filtered out since oneOpsOrg is null
      expect(summary).not.toContain("OneOps:");
    });

    it("handles empty slackChannels array", () => {
      const { result } = renderViewContext();

      const app = makeApplication({
        name: "no-slack-app",
        slackChannels: [],
      });

      act(() => {
        result.current.setActiveView("applications");
        result.current.setSelectedApplication(app);
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain("Slack: none");
    });

    it("handles managed service with minimal fields", () => {
      const { result } = renderViewContext();

      const svc: ManagedServiceData = {
        id: 99,
        managedServiceId: 99,
        name: "minimal-svc",
        serviceType: "Kafka",
        topicName: "events-topic",
      };

      act(() => {
        result.current.setActiveView("managed-services");
        result.current.setSelectedManagedService(svc);
      });

      const summary = result.current.getContextSummary();

      expect(summary).toContain('User is asking about a specific managed service: "minimal-svc"');
      expect(summary).toContain("Service Type: Kafka");
      expect(summary).toContain("Topic: events-topic");
      // Optional fields not present should not appear
      expect(summary).not.toContain("Subscription ID:");
      expect(summary).not.toContain("Resource Group:");
      expect(summary).not.toContain("Database:");
      expect(summary).not.toContain("DNS:");
    });

    it("groups applications with missing tier/type under 'Unknown'", () => {
      const { result } = renderViewContext();

      const apps: Application[] = [
        makeApplication({ id: 1, tier: "", applicationType: "" }),
        makeApplication({ id: 2, tier: "", applicationType: "" }),
      ];

      act(() => {
        result.current.setApplicationData(apps);
      });

      const stats = result.current.appStats;

      expect(stats.byTier).toEqual({ Unknown: 2 });
      expect(stats.byType).toEqual({ Unknown: 2 });
    });
  });
});

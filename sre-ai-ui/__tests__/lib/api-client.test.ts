import {
  buildAlertsQueryPayload,
  dependencyApprovalsApi,
  type Application,
  type ManagedServiceData,
  type DependencyApproval,
} from "@/lib/api-client";

// ─── dependencyApprovalsApi tests ─────────────────────────────────────────────
// These tests verify the correct endpoints and payloads are constructed.
// sre-operator-actions is mocked so no real HTTP is made.

jest.mock("@/lib/sre-operator-actions", () => ({
  fetchSreOperator: jest.fn(),
}));

const { fetchSreOperator } = jest.requireMock("@/lib/sre-operator-actions") as {
  fetchSreOperator: jest.Mock;
};

function makeApproval(overrides: Partial<DependencyApproval> = {}): DependencyApproval {
  return {
    id: 1,
    applicationId: 101,
    applicationName: "checkout-service",
    dependencyId: 202,
    dependencyName: "payment-service",
    action: "ADD",
    status: "PENDING",
    reason: "Need for payments",
    requestedBy: "john.doe",
    approvedBy: null,
    approvedAt: null,
    createdAt: "2026-03-27T10:00:00.000Z",
    updatedAt: "2026-03-27T10:00:00.000Z",
    ...overrides,
  };
}

describe("dependencyApprovalsApi", () => {
  beforeEach(() => jest.clearAllMocks());

  describe("submitRequest", () => {
    it("POST /dependency-approvals with correct payload for ADD action", async () => {
      const mockResponse = {
        status: 201,
        message: "Dependency approval request submitted successfully",
        data: makeApproval(),
      };
      fetchSreOperator.mockResolvedValueOnce(mockResponse);

      const result = await dependencyApprovalsApi.submitRequest({
        applicationId: 101,
        dependencyId: 202,
        action: "ADD",
        requestedBy: "john.doe",
        reason: "Need for payments",
      });

      expect(fetchSreOperator).toHaveBeenCalledWith(
        "/dependency-approvals",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            applicationId: 101,
            dependencyId: 202,
            action: "ADD",
            requestedBy: "john.doe",
            reason: "Need for payments",
          }),
        })
      );
      expect(result.data.status).toBe("PENDING");
      expect(result.data.action).toBe("ADD");
    });

    it("POST /dependency-approvals with correct payload for DELETE action", async () => {
      const mockResponse = {
        status: 201,
        message: "Dependency approval request submitted successfully",
        data: makeApproval({ action: "DELETE", status: "PENDING" }),
      };
      fetchSreOperator.mockResolvedValueOnce(mockResponse);

      const result = await dependencyApprovalsApi.submitRequest({
        applicationId: 101,
        dependencyId: 202,
        action: "DELETE",
        requestedBy: "john.doe",
      });

      expect(fetchSreOperator).toHaveBeenCalledWith(
        "/dependency-approvals",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"action":"DELETE"'),
        })
      );
      expect(result.data.action).toBe("DELETE");
    });

    it("returns REJECTED status and system approver when auto-rejected", async () => {
      const autoRejected = {
        status: 201,
        message: "Dependency approval request submitted successfully",
        data: makeApproval({
          status: "REJECTED",
          approvedBy: "system",
          reason: 'Auto-rejected: previous request was rejected by jane.smith with reason: "Not needed"',
          approvedAt: "2026-03-27T10:00:00.000Z",
        }),
      };
      fetchSreOperator.mockResolvedValueOnce(autoRejected);

      const result = await dependencyApprovalsApi.submitRequest({
        applicationId: 101,
        dependencyId: 202,
        action: "ADD",
        requestedBy: "john.doe",
      });

      expect(result.data.status).toBe("REJECTED");
      expect(result.data.approvedBy).toBe("system");
      expect(result.data.reason).toContain("Auto-rejected");
    });

    it("omits reason from payload when not provided", async () => {
      fetchSreOperator.mockResolvedValueOnce({
        status: 201,
        message: "ok",
        data: makeApproval(),
      });

      await dependencyApprovalsApi.submitRequest({
        applicationId: 101,
        dependencyId: 202,
        action: "ADD",
        requestedBy: "john.doe",
        // no reason
      });

      const body = JSON.parse(fetchSreOperator.mock.calls[0][1].body);
      expect(body.reason).toBeUndefined();
    });
  });

  describe("approve", () => {
    it("PUT /dependency-approvals/{id}/approve with approvedBy", async () => {
      const approvedData = makeApproval({ status: "APPROVED", approvedBy: "jane.smith" });
      fetchSreOperator.mockResolvedValueOnce({ status: 200, message: "ok", data: approvedData });

      const result = await dependencyApprovalsApi.approve(1, "jane.smith");

      expect(fetchSreOperator).toHaveBeenCalledWith(
        "/dependency-approvals/1/approve",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ approvedBy: "jane.smith", reason: undefined }),
        })
      );
      expect(result.data.status).toBe("APPROVED");
      expect(result.data.approvedBy).toBe("jane.smith");
    });

    it("includes optional reason in approve payload", async () => {
      const approvedData = makeApproval({ status: "APPROVED", approvedBy: "jane.smith" });
      fetchSreOperator.mockResolvedValueOnce({ status: 200, message: "ok", data: approvedData });

      await dependencyApprovalsApi.approve(1, "jane.smith", "Looks good");

      const body = JSON.parse(fetchSreOperator.mock.calls[0][1].body);
      expect(body.reason).toBe("Looks good");
    });
  });

  describe("reject", () => {
    it("PUT /dependency-approvals/{id}/reject with approvedBy and reason", async () => {
      const rejectedData = makeApproval({ status: "REJECTED", approvedBy: "jane.smith", reason: "Duplicate" });
      fetchSreOperator.mockResolvedValueOnce({ status: 200, message: "ok", data: rejectedData });

      const result = await dependencyApprovalsApi.reject(1, "jane.smith", "Duplicate");

      expect(fetchSreOperator).toHaveBeenCalledWith(
        "/dependency-approvals/1/reject",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ approvedBy: "jane.smith", reason: "Duplicate" }),
        })
      );
      expect(result.data.status).toBe("REJECTED");
      expect(result.data.reason).toBe("Duplicate");
    });

    it("withdraw self-reject uses 'Withdrawn by requester' as reason", async () => {
      const withdrawnData = makeApproval({ status: "REJECTED", approvedBy: "john.doe", reason: "Withdrawn by requester" });
      fetchSreOperator.mockResolvedValueOnce({ status: 200, message: "ok", data: withdrawnData });

      const result = await dependencyApprovalsApi.reject(1, "john.doe", "Withdrawn by requester");

      const body = JSON.parse(fetchSreOperator.mock.calls[0][1].body);
      expect(body.approvedBy).toBe("john.doe");
      expect(body.reason).toBe("Withdrawn by requester");
      expect(result.data.approvedBy).toBe("john.doe");
    });
  });

  describe("getAll", () => {
    it("GET /dependency-approvals", async () => {
      const list = [makeApproval(), makeApproval({ id: 2, status: "APPROVED" })];
      fetchSreOperator.mockResolvedValueOnce(list);

      const result = await dependencyApprovalsApi.getAll();

      expect(fetchSreOperator).toHaveBeenCalledWith("/dependency-approvals", undefined);
      expect(result).toHaveLength(2);
    });
  });

  describe("getByStatus", () => {
    it("GET /dependency-approvals/status/PENDING", async () => {
      fetchSreOperator.mockResolvedValueOnce([makeApproval()]);
      await dependencyApprovalsApi.getByStatus("PENDING");
      expect(fetchSreOperator).toHaveBeenCalledWith("/dependency-approvals/status/PENDING", undefined);
    });

    it("GET /dependency-approvals/status/APPROVED", async () => {
      fetchSreOperator.mockResolvedValueOnce([]);
      await dependencyApprovalsApi.getByStatus("APPROVED");
      expect(fetchSreOperator).toHaveBeenCalledWith("/dependency-approvals/status/APPROVED", undefined);
    });

    it("GET /dependency-approvals/status/REJECTED", async () => {
      fetchSreOperator.mockResolvedValueOnce([]);
      await dependencyApprovalsApi.getByStatus("REJECTED");
      expect(fetchSreOperator).toHaveBeenCalledWith("/dependency-approvals/status/REJECTED", undefined);
    });
  });

  describe("getByApplication", () => {
    it("GET /dependency-approvals/application/{id}", async () => {
      fetchSreOperator.mockResolvedValueOnce([makeApproval()]);
      await dependencyApprovalsApi.getByApplication(101);
      expect(fetchSreOperator).toHaveBeenCalledWith("/dependency-approvals/application/101", undefined);
    });
  });

  describe("getById", () => {
    it("GET /dependency-approvals/{id}", async () => {
      fetchSreOperator.mockResolvedValueOnce(makeApproval());
      const result = await dependencyApprovalsApi.getById(1);
      expect(fetchSreOperator).toHaveBeenCalledWith("/dependency-approvals/1", undefined);
      expect(result.id).toBe(1);
    });
  });
});

// ─── Fixtures ────────────────────────────────────────────────────────────────

function makeWcnpApp(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    name: "my-app",
    tenant: "tenant-a",
    tier: "T1",
    functionalDomain: "ecom",
    active: true,
    certified: true,
    applicationType: "wcnp",
    namespace: "prod-namespace",
    appName: "my-app-name",
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

function makeOneOpsApp(overrides: Partial<Application> = {}): Application {
  return {
    ...makeWcnpApp(),
    applicationType: "oneops",
    namespace: null,
    appName: null,
    wcnpId: null,
    oneOpsPlatformId: 99,
    oneOpsOrg: "my-org",
    oneOpsAssembly: "my-assembly",
    oneOpsPlatform: "my-platform",
    ...overrides,
  };
}

function makeManagedService(
  serviceType: string,
  overrides: Partial<ManagedServiceData> = {}
): ManagedServiceData {
  return {
    id: 10,
    managedServiceId: 10,
    name: `test-${serviceType}`,
    serviceType,
    assembly: "test-assembly",
    platform: "test-platform",
    subscriptionId: "sub-123",
    resourceGroup: "rg-456",
    databaseName: "db-name",
    dns: "test.dns",
    topicName: "my-topic",
    ...overrides,
  };
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("buildAlertsQueryPayload", () => {
  const START = "1700000000";
  const END = "1700003600";

  describe("WCNP application", () => {
    it("returns wcnp service_type with namespace and app_name", () => {
      const app = makeWcnpApp();
      const payload = buildAlertsQueryPayload(app, START, END);

      expect(payload.service_type).toBe("wcnp");
      expect(payload.namespace).toBe("prod-namespace");
      expect(payload.app_name).toBe("my-app-name");
      expect(payload.start).toBe(START);
      expect(payload.end).toBe(END);
      expect(payload.step).toBe("30s");
    });

    it("includes intent when provided", () => {
      const app = makeWcnpApp();
      const payload = buildAlertsQueryPayload(app, START, END, "cpu_alerts");
      expect(payload.intent).toBe("cpu_alerts");
    });

    it("omits intent field when not provided", () => {
      const app = makeWcnpApp();
      const payload = buildAlertsQueryPayload(app, START, END);
      expect(payload.intent).toBeUndefined();
    });
  });

  describe("OneOps application", () => {
    it("returns oneops service_type with org, assembly, platform", () => {
      const app = makeOneOpsApp();
      const payload = buildAlertsQueryPayload(app, START, END);

      expect(payload.service_type).toBe("oneops");
      expect(payload.org).toBe("my-org");
      expect(payload.assembly).toBe("my-assembly");
      expect(payload.platform).toBe("my-platform");
      expect(payload.start).toBe(START);
      expect(payload.end).toBe(END);
    });

    it("does not include namespace or app_name for OneOps app", () => {
      const app = makeOneOpsApp();
      const payload = buildAlertsQueryPayload(app, START, END);
      expect(payload.namespace).toBeUndefined();
      expect(payload.app_name).toBeUndefined();
    });
  });

  describe("Cassandra managed service", () => {
    it("returns cassandra service_type with cluster from assembly", () => {
      const svc = makeManagedService("cassandra", { assembly: "cass-cluster" });
      const payload = buildAlertsQueryPayload(svc, START, END);

      expect(payload.service_type).toBe("cassandra");
      expect(payload.cluster).toBe("cass-cluster");
    });
  });

  describe("Cosmos managed service", () => {
    it("returns cosmos service_type with subscription and resource group", () => {
      const svc = makeManagedService("cosmos", {
        subscriptionId: "cosmos-sub",
        resourceGroup: "cosmos-rg",
      });
      const payload = buildAlertsQueryPayload(svc, START, END);

      expect(payload.service_type).toBe("cosmos");
      expect(payload.subscription_name).toBe("cosmos-sub");
      expect(payload.resource_group).toBe("cosmos-rg");
    });
  });

  describe("Kafka managed service", () => {
    it("returns kafka service_type with cluster and topic", () => {
      const svc = makeManagedService("kafka", {
        assembly: "kafka-cluster",
        topicName: "order-events",
      });
      const payload = buildAlertsQueryPayload(svc, START, END);

      expect(payload.service_type).toBe("kafka");
      expect(payload.cluster).toBe("kafka-cluster");
      expect(payload.topic).toBe("order-events");
    });
  });

  describe("MeghaCache managed service", () => {
    it("returns meghacache service_type with megacache_assembly", () => {
      const svc = makeManagedService("meghacache", { assembly: "cache-001" });
      const payload = buildAlertsQueryPayload(svc, START, END);

      expect(payload.service_type).toBe("meghacache");
      expect(payload.megacache_assembly).toBe("cache-001");
    });
  });

  describe("SQL managed service", () => {
    it("returns sql service_type with database name", () => {
      const svc = makeManagedService("sql", { databaseName: "orders-db" });
      const payload = buildAlertsQueryPayload(svc, START, END);

      expect(payload.service_type).toBe("sql");
      expect(payload.database).toBe("orders-db");
    });
  });

  describe("Oracle managed service", () => {
    it("returns oracle service_type with database name", () => {
      const svc = makeManagedService("oracle", { databaseName: "oracle-db" });
      const payload = buildAlertsQueryPayload(svc, START, END);

      expect(payload.service_type).toBe("oracle");
      expect(payload.database).toBe("oracle-db");
    });
  });

  describe("Unknown / unrecognized service type", () => {
    it("returns base payload with the service_type set", () => {
      const svc = makeManagedService("solr");
      const payload = buildAlertsQueryPayload(svc, START, END);

      expect(payload.service_type).toBe("solr");
      expect(payload.start).toBe(START);
      expect(payload.end).toBe(END);
      expect(payload.step).toBe("30s");
    });
  });

  describe("Common base payload fields", () => {
    it("always includes start, end and step", () => {
      const app = makeWcnpApp();
      const payload = buildAlertsQueryPayload(app, START, END);

      expect(payload.start).toBe(START);
      expect(payload.end).toBe(END);
      expect(payload.step).toBe("30s");
    });
  });

  describe("Fallback for object with neither applicationType nor serviceType", () => {
    it("returns base payload without service_type when object has no type markers", () => {
      // Create a plain object that has neither 'applicationType' nor 'serviceType'
      const plainObj = { id: 1, name: "mystery" } as any;
      const payload = buildAlertsQueryPayload(plainObj, START, END);

      expect(payload.start).toBe(START);
      expect(payload.end).toBe(END);
      expect(payload.step).toBe("30s");
      expect(payload.service_type).toBeUndefined();
    });
  });
});

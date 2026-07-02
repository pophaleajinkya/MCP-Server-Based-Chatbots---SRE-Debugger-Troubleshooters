/**
 * @jest-environment node
 *
 * Integration tests for dependencies API endpoints.
 * Tests add and delete dependency functionality.
 */

import { applicationsApi } from "@/lib/api-client";

// ─── Mocks ────────────────────────────────────────────────────────────────────

const mockFetch = jest.fn();
global.fetch = mockFetch;


// ─── Fixtures ─────────────────────────────────────────────────────────────────

const VALID_APP_ID = 320;
const VALID_DEPENDENCY_ID = 102;
const INVALID_ID = -1;
const NON_EXISTENT_ID = 99999;

const SRE_OPERATOR_URL = process.env.SRE_OPERATOR_URL || "http://localhost:9000";

// ─── Test Suite ───────────────────────────────────────────────────────────────

describe("Dependencies API", () => {
  beforeEach(() => {
    mockFetch.mockClear();

    // Set up a response queue for tracking multiple mocked responses
    const responseQueue: Response[] = [];
    (mockFetch as any).__responseQueue = responseQueue;

    // Set up mockFetch with custom implementation
    mockFetch.mockImplementation(async (url: string | Request) => {
      const urlStr = typeof url === "string" ? url : url.toString();

      // For API calls, use queued responses
      if (responseQueue.length > 0) {
        return responseQueue.shift()!;
      }

      throw new Error(`Unexpected fetch call: ${urlStr} (no mock response queued)`);
    });

    // Helper: Setup mock responses for an API call
    // Simply queues the API response (config endpoint is handled by mockImplementation)
    function setupApiMock(apiResponse: unknown) {
      responseQueue.push(apiResponse as Response);
    }

    // Attach helper to mockFetch for easy access
    (mockFetch as any).setupApiMock = setupApiMock;
  });

  describe("addDependency", () => {
    it("should successfully add a dependency with valid IDs", async () => {
      (mockFetch as any).setupApiMock({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      });

      const result = await applicationsApi.addDependency(
        VALID_APP_ID,
        VALID_DEPENDENCY_ID
      );

      expect(mockFetch).toHaveBeenCalledWith(
        `${SRE_OPERATOR_URL}/dependencies`,
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            applicationId: VALID_APP_ID,
            dependencyId: VALID_DEPENDENCY_ID,
            source: "user",
          }),
          headers: expect.objectContaining({
            "Content-Type": "application/json",
          }),
        })
      );
      expect(result).toEqual({ success: true });
    });

    it("should include source='user' in request body", async () => {
      (mockFetch as any).setupApiMock({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      });

      await applicationsApi.addDependency(VALID_APP_ID, VALID_DEPENDENCY_ID);

      const callBody = JSON.parse(
        mockFetch.mock.calls[0][1]!.body as string
      );
      expect(callBody).toHaveProperty("source", "user");
    });

    it("should throw error on 400 (invalid dependency)", async () => {
      (mockFetch as any).setupApiMock({
        ok: false,
        status: 400,
        statusText: "Bad Request",
      });

      await expect(
        applicationsApi.addDependency(VALID_APP_ID, INVALID_ID)
      ).rejects.toThrow("API Error: 400 Bad Request");
    });

    it("should throw error on 404 (application not found)", async () => {
      (mockFetch as any).setupApiMock({
        ok: false,
        status: 404,
        statusText: "Not Found",
      });

      await expect(
        applicationsApi.addDependency(NON_EXISTENT_ID, VALID_DEPENDENCY_ID)
      ).rejects.toThrow("API Error: 404 Not Found");
    });

    it("should throw error on 409 (dependency already exists)", async () => {
      (mockFetch as any).setupApiMock({
        ok: false,
        status: 409,
        statusText: "Conflict",
      });

      await expect(
        applicationsApi.addDependency(VALID_APP_ID, VALID_DEPENDENCY_ID)
      ).rejects.toThrow("API Error: 409 Conflict");
    });

    it("should throw error on network failure", async () => {
      mockFetch.mockRejectedValueOnce(new Error("Network error"));

      await expect(
        applicationsApi.addDependency(VALID_APP_ID, VALID_DEPENDENCY_ID)
      ).rejects.toThrow("Network error");
    });

    it("should handle zero IDs gracefully", async () => {
      (mockFetch as any).setupApiMock({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      });

      await applicationsApi.addDependency(0, 0);

      const callBody = JSON.parse(
        mockFetch.mock.calls[0][1]!.body as string
      );
      expect(callBody.applicationId).toBe(0);
      expect(callBody.dependencyId).toBe(0);
    });

    it("should handle large IDs (32-bit integers)", async () => {
      const largeId = 2147483647;
      (mockFetch as any).setupApiMock({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      });

      await applicationsApi.addDependency(largeId, largeId);

      const callBody = JSON.parse(
        mockFetch.mock.calls[0][1]!.body as string
      );
      expect(callBody.applicationId).toBe(largeId);
      expect(callBody.dependencyId).toBe(largeId);
    });
  });

  describe("deleteDependency", () => {
    it("should successfully delete a dependency with valid IDs", async () => {
      (mockFetch as any).setupApiMock({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      });

      const result = await applicationsApi.deleteDependency(
        VALID_APP_ID,
        VALID_DEPENDENCY_ID
      );

      expect(mockFetch).toHaveBeenCalledWith(
        `${SRE_OPERATOR_URL}/dependencies/application/${VALID_APP_ID}/dependency/${VALID_DEPENDENCY_ID}`,
        expect.objectContaining({
          method: "DELETE",
          headers: expect.objectContaining({
            "Content-Type": "application/json",
          }),
        })
      );
      expect(result).toEqual({ success: true });
    });

    it("should construct correct DELETE URL", async () => {
      (mockFetch as any).setupApiMock({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      });

      await applicationsApi.deleteDependency(VALID_APP_ID, VALID_DEPENDENCY_ID);

      const callUrl = mockFetch.mock.calls[0][0];
      expect(callUrl).toBe(
        `${SRE_OPERATOR_URL}/dependencies/application/${VALID_APP_ID}/dependency/${VALID_DEPENDENCY_ID}`
      );
    });

    it("should throw error on 404 (dependency not found)", async () => {
      (mockFetch as any).setupApiMock({
        ok: false,
        status: 404,
        statusText: "Not Found",
      });

      await expect(
        applicationsApi.deleteDependency(VALID_APP_ID, NON_EXISTENT_ID)
      ).rejects.toThrow("API Error: 404 Not Found");
    });

    it("should throw error on 400 (invalid IDs)", async () => {
      (mockFetch as any).setupApiMock({
        ok: false,
        status: 400,
        statusText: "Bad Request",
      });

      await expect(
        applicationsApi.deleteDependency(INVALID_ID, INVALID_ID)
      ).rejects.toThrow("API Error: 400 Bad Request");
    });

    it("should throw error on 403 (permission denied)", async () => {
      (mockFetch as any).setupApiMock({
        ok: false,
        status: 403,
        statusText: "Forbidden",
      });

      await expect(
        applicationsApi.deleteDependency(VALID_APP_ID, VALID_DEPENDENCY_ID)
      ).rejects.toThrow("API Error: 403 Forbidden");
    });

    it("should handle 204 No Content response", async () => {
      (mockFetch as any).setupApiMock({
        ok: true,
        status: 204,
        statusText: "No Content",
        json: async () => {
          throw new Error("No body");
        },
      });

      const result = await applicationsApi.deleteDependency(
        VALID_APP_ID,
        VALID_DEPENDENCY_ID
      );

      expect(result).toBeUndefined();
    });

    it("should throw error on network failure", async () => {
      mockFetch.mockRejectedValueOnce(new Error("Network timeout"));

      await expect(
        applicationsApi.deleteDependency(VALID_APP_ID, VALID_DEPENDENCY_ID)
      ).rejects.toThrow("Network timeout");
    });

    it("should throw error on 500 server error", async () => {
      (mockFetch as any).setupApiMock({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
      });

      await expect(
        applicationsApi.deleteDependency(VALID_APP_ID, VALID_DEPENDENCY_ID)
      ).rejects.toThrow("API Error: 500 Internal Server Error");
    });

    it("should handle zero IDs in URL correctly", async () => {
      (mockFetch as any).setupApiMock({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      });

      await applicationsApi.deleteDependency(0, 0);

      const callUrl = mockFetch.mock.calls[0][0];
      expect(callUrl).toBe(
        `${SRE_OPERATOR_URL}/dependencies/application/0/dependency/0`
      );
    });
  });

  describe("Edge Cases - Add & Delete", () => {
    it("should not include extra properties in add request", async () => {
      (mockFetch as any).setupApiMock({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      });

      await applicationsApi.addDependency(VALID_APP_ID, VALID_DEPENDENCY_ID);

      const callBody = JSON.parse(
        mockFetch.mock.calls[0][1]!.body as string
      );
      expect(Object.keys(callBody).sort()).toEqual([
        "applicationId",
        "dependencyId",
        "source",
      ]);
    });

    it("should handle rapid consecutive add requests", async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true }),
        });

      const results = await Promise.all([
        applicationsApi.addDependency(VALID_APP_ID, 100),
        applicationsApi.addDependency(VALID_APP_ID, 101),
      ]);

      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(results).toHaveLength(2);
      expect(results[0]).toEqual({ success: true });
      expect(results[1]).toEqual({ success: true });
    });

    it("should handle rapid consecutive delete requests", async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true }),
        });

      const results = await Promise.all([
        applicationsApi.deleteDependency(VALID_APP_ID, 100),
        applicationsApi.deleteDependency(VALID_APP_ID, 101),
      ]);

      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(results).toHaveLength(2);
    });

    it("should use correct headers for both operations", async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true }),
        });

      await applicationsApi.addDependency(VALID_APP_ID, VALID_DEPENDENCY_ID);
      await applicationsApi.deleteDependency(VALID_APP_ID, VALID_DEPENDENCY_ID);

      const addHeaders = mockFetch.mock.calls[0][1]!.headers;
      const deleteHeaders = mockFetch.mock.calls[1][1]!.headers;

      expect(addHeaders).toEqual(deleteHeaders);
      expect(addHeaders).toHaveProperty("Content-Type", "application/json");
    });
  });
});

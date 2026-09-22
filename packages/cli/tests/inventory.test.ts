import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  inventoryCommand,
  transferOwnershipCommand,
  setGovernanceCommand,
} from "../src/commands/inventory.js";
import { ApiClient } from "../src/client.js";

vi.mock("../src/client.js");

describe("Capsule CLI Inventory & Governance Commands (Prompt 20)", () => {
  let mockClient: any;

  beforeEach(() => {
    vi.clearAllMocks();
    mockClient = {
      request: vi.fn(),
    };
    (ApiClient as any).mockImplementation(function () {
      return mockClient;
    });
  });

  it("should list organization inventory and output JSON", async () => {
    mockClient.request.mockImplementation(async (path: string) => {
      if (path === "/v1/auth/me") {
        return { organization_id: "org-123" };
      }
      if (path.includes("/inventory")) {
        return {
          organization_id: "org-123",
          total: 2,
          items: [
            {
              id: "app-1",
              app_key: "leave-tracker",
              name: "Leave Tracker",
              status: "active",
              governance_state: "normal",
              user_count: 5,
              current_version: "v1",
              owner: { email: "alice@example.com" },
            },
            {
              id: "app-2",
              app_key: "survey-tool",
              name: "Survey Tool",
              status: "suspended",
              governance_state: "grace_period_expired",
              user_count: 1,
              current_version: "v2",
              owner: null,
            },
          ],
        };
      }
      throw new Error(`Unexpected path: ${path}`);
    });

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await inventoryCommand({ json: true });

    expect(mockClient.request).toHaveBeenCalledWith(
      "/v1/organizations/org-123/inventory",
    );
    expect(logSpy).toHaveBeenCalled();
    const result = JSON.parse(logSpy.mock.calls[0][0]);
    expect(result.total).toBe(2);
    expect(result.items[0].app_key).toBe("leave-tracker");

    logSpy.mockRestore();
  });

  it("should transfer ownership to target user", async () => {
    mockClient.request.mockImplementation(
      async (path: string, options?: any) => {
        if (path === "/v1/apps/leave-tracker/transfer-ownership") {
          const body = JSON.parse(options.body);
          expect(body.new_owner_user_id).toBe("user-bob-456");
          return {
            id: "app-1",
            app_key: "leave-tracker",
            owner_user_id: "user-bob-456",
            status: "active",
            governance_state: "normal",
          };
        }
        throw new Error(`Unexpected path: ${path}`);
      },
    );

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await transferOwnershipCommand("leave-tracker", {
      newOwner: "user-bob-456",
      reason: "Reassigning team lead",
      json: true,
    });

    expect(logSpy).toHaveBeenCalled();
    const result = JSON.parse(logSpy.mock.calls[0][0]);
    expect(result.owner_user_id).toBe("user-bob-456");

    logSpy.mockRestore();
  });

  it("should update governance parameters for an app", async () => {
    mockClient.request.mockImplementation(
      async (path: string, options?: any) => {
        if (path === "/v1/apps/leave-tracker/governance") {
          const body = JSON.parse(options.body);
          expect(body.inactivity_days_limit).toBe(60);
          return {
            id: "app-1",
            app_key: "leave-tracker",
            inactivity_days_limit: 60,
            purge_after_days: 30,
          };
        }
        throw new Error(`Unexpected path: ${path}`);
      },
    );

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await setGovernanceCommand("leave-tracker", {
      inactivityLimitDays: 60,
      json: true,
    });

    expect(logSpy).toHaveBeenCalled();
    logSpy.mockRestore();
  });
});

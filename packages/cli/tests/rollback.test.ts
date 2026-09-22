import { describe, it, expect, vi, beforeEach } from "vitest";
import { rollbackCommand } from "../src/commands/rollback.js";
import { versionsCommand } from "../src/commands/versions.js";
import { ApiClient } from "../src/client.js";

vi.mock("../src/client.js");

describe("CLI Rollback & Versions Commands", () => {
  let mockClient: any;

  beforeEach(() => {
    vi.clearAllMocks();
    mockClient = {
      rollback: vi.fn(),
      listVersions: vi.fn(),
    };
    (ApiClient as any).mockImplementation(function () {
      return mockClient;
    });
  });

  it("should reject rollback when --version is missing", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const exitSpy = vi
      .spyOn(process, "exit")
      .mockImplementation((() => {}) as any);

    await rollbackCommand({ app: "test-app", json: true });

    expect(errorSpy).toHaveBeenCalled();
    const errorOutput = JSON.parse(errorSpy.mock.calls[0][0]);
    expect(errorOutput.error.code).toBe("MISSING_VERSION");

    errorSpy.mockRestore();
    exitSpy.mockRestore();
  });

  it("should reject invalid rollback mode", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const exitSpy = vi
      .spyOn(process, "exit")
      .mockImplementation((() => {}) as any);

    await rollbackCommand({
      app: "test-app",
      version: 1,
      mode: "invalid-mode",
      json: true,
    });

    expect(errorSpy).toHaveBeenCalled();
    const errorOutput = JSON.parse(errorSpy.mock.calls[0][0]);
    expect(errorOutput.error.code).toBe("INVALID_MODE");

    errorSpy.mockRestore();
    exitSpy.mockRestore();
  });

  it("should execute code-only rollback successfully", async () => {
    mockClient.rollback.mockResolvedValueOnce({
      operation_id: "op-123",
      type: "rollback",
      status: "succeeded",
      app_id: "app-123",
      version_id: "ver-3",
      version_number: 3,
      target_version_number: 1,
      mode: "code_only",
      recovery_snapshot_ref:
        "capsules/app-123/snapshots/pre_rollback_v3.sqlite",
      data_restored: false,
      created_at: new Date().toISOString(),
    });

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await rollbackCommand({
      app: "test-app",
      version: 1,
      mode: "code-only",
      json: true,
    });

    expect(mockClient.rollback).toHaveBeenCalledWith("test-app", {
      target_version_number: 1,
      mode: "code_only",
      confirm_data_restore: false,
      reason: undefined,
    });

    expect(logSpy).toHaveBeenCalled();
    const result = JSON.parse(logSpy.mock.calls[0][0]);
    expect(result.version_number).toBe(3);
    expect(result.data_restored).toBe(false);

    logSpy.mockRestore();
  });

  it("should execute code-and-data rollback with confirmation", async () => {
    mockClient.rollback.mockResolvedValueOnce({
      operation_id: "op-456",
      type: "rollback",
      status: "succeeded",
      app_id: "app-123",
      version_id: "ver-4",
      version_number: 4,
      target_version_number: 2,
      mode: "code_and_data",
      recovery_snapshot_ref:
        "capsules/app-123/snapshots/pre_rollback_v4.sqlite",
      data_restored: true,
      created_at: new Date().toISOString(),
    });

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await rollbackCommand({
      app: "test-app",
      version: 2,
      mode: "code-and-data",
      confirmDataRestore: true,
      reason: "Restore test",
      json: true,
    });

    expect(mockClient.rollback).toHaveBeenCalledWith("test-app", {
      target_version_number: 2,
      mode: "code_and_data",
      confirm_data_restore: true,
      reason: "Restore test",
    });

    expect(logSpy).toHaveBeenCalled();
    const result = JSON.parse(logSpy.mock.calls[0][0]);
    expect(result.version_number).toBe(4);
    expect(result.data_restored).toBe(true);

    logSpy.mockRestore();
  });

  it("should list versions including publisher information", async () => {
    mockClient.listVersions.mockResolvedValueOnce([
      {
        version_number: 2,
        status: "published",
        published_at: "2026-09-21T10:00:00Z",
        publisher_name: "Alice Owner",
        change_description: "Feature release",
      },
      {
        version_number: 1,
        status: "rolled_back",
        published_at: "2026-09-20T08:00:00Z",
        publisher_name: "Bob Colleague",
        change_description: "Initial commit",
      },
    ]);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await versionsCommand({ app: "test-app" });

    expect(logSpy).toHaveBeenCalled();
    const fullOutput = logSpy.mock.calls.map((c) => c[0]).join("\n");
    expect(fullOutput).toContain("VERSION");
    expect(fullOutput).toContain("STATUS");
    expect(fullOutput).toContain("PUBLISHED");
    expect(fullOutput).toContain("PUBLISHER");
    expect(fullOutput).toContain("Alice Owner");
    expect(fullOutput).toContain("Bob Colleague");

    logSpy.mockRestore();
  });
});

/**
 * DevMockSandboxDriver
 * WARNING: This is a development-only mock driver.
 * It is NOT a security boundary. It exists solely for lightweight unit testing.
 */
import type {
  SandboxDriver,
  SandboxSpec,
  SandboxInstance,
  SandboxStatus,
  LogOptions,
  ForwardRequest,
  ForwardResponse,
} from "../interface.js";

export class DevMockSandboxDriver implements SandboxDriver {
  readonly name = "dev-mock-driver";
  private instances = new Map<string, SandboxInstance>();
  private logsMap = new Map<string, string[]>();
  private mockResponses = new Map<
    string,
    (req: ForwardRequest) => ForwardResponse
  >();

  constructor() {
    console.warn(
      "[WARNING] DevMockSandboxDriver is an in-memory mock for testing only. It is NOT a security boundary.",
    );
  }

  setMockResponse(
    path: string,
    handler: (req: ForwardRequest) => ForwardResponse,
  ): void {
    this.mockResponses.set(path, handler);
  }

  async start(spec: SandboxSpec): Promise<SandboxInstance> {
    const id = `mock-${spec.capsuleId}-${Date.now()}`;
    const now = new Date();
    const instance: SandboxInstance = {
      id,
      capsuleId: spec.capsuleId,
      versionId: spec.versionId,
      status: "running",
      spec,
      assignedPort: spec.port || 3000,
      createdAt: now,
      startedAt: now,
      lastActiveAt: now,
    };
    this.instances.set(id, instance);
    this.logsMap.set(id, [`[mock] Container started for ${spec.capsuleId}`]);
    return instance;
  }

  async stop(instanceId: string): Promise<void> {
    const inst = this.instances.get(instanceId);
    if (!inst) throw new Error(`Instance not found: ${instanceId}`);
    inst.status = "stopped";
    this.logsMap.get(instanceId)?.push(`[mock] Container stopped`);
  }

  async suspend(instanceId: string): Promise<void> {
    const inst = this.instances.get(instanceId);
    if (!inst) throw new Error(`Instance not found: ${instanceId}`);
    inst.status = "suspended";
    this.logsMap.get(instanceId)?.push(`[mock] Container suspended`);
  }

  async resume(instanceId: string): Promise<void> {
    const inst = this.instances.get(instanceId);
    if (!inst) throw new Error(`Instance not found: ${instanceId}`);
    inst.status = "running";
    inst.lastActiveAt = new Date();
    this.logsMap.get(instanceId)?.push(`[mock] Container resumed`);
  }

  async status(instanceId: string): Promise<SandboxStatus> {
    const inst = this.instances.get(instanceId);
    return inst ? inst.status : "stopped";
  }

  async logs(instanceId: string, options?: LogOptions): Promise<string[]> {
    const all = this.logsMap.get(instanceId) || [];
    if (options?.tail) {
      return all.slice(-options.tail);
    }
    return all;
  }

  async forwardRequest(
    instanceId: string,
    req: ForwardRequest,
  ): Promise<ForwardResponse> {
    const inst = this.instances.get(instanceId);
    if (!inst) throw new Error(`Instance not found: ${instanceId}`);
    if (inst.status !== "running") {
      throw new Error(
        `Cannot forward request: instance ${instanceId} is ${inst.status}`,
      );
    }
    inst.lastActiveAt = new Date();

    const handler = this.mockResponses.get(req.path);
    if (handler) {
      return handler(req);
    }

    if (req.path === "/health") {
      return {
        statusCode: 200,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ status: "healthy", capsule: inst.capsuleId }),
      };
    }

    return {
      statusCode: 200,
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        status: "ok",
        method: req.method,
        path: req.path,
        mock: true,
      }),
    };
  }

  async recover(instanceId: string): Promise<SandboxInstance> {
    const inst = this.instances.get(instanceId);
    if (!inst) throw new Error(`Instance not found: ${instanceId}`);
    inst.status = "running";
    inst.lastActiveAt = new Date();
    this.logsMap.get(instanceId)?.push(`[mock] Container recovered from crash`);
    return inst;
  }

  async destroy(instanceId: string): Promise<void> {
    this.instances.delete(instanceId);
    this.logsMap.delete(instanceId);
  }
}

export const MockSandboxDriver = DevMockSandboxDriver;
export type MockSandboxDriver = DevMockSandboxDriver;

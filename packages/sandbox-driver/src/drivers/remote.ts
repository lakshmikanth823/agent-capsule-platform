/**
 * RemoteSandboxDriver (Client for Private Sandbox Runner)
 *
 * Implements SandboxDriver by delegating all operations over an authenticated internal
 * HTTP/mTLS network connection to the dedicated sandbox-host runner service.
 *
 * Security Architecture:
 * - Public/Edge proxy hosts never execute Docker or mount /var/run/docker.sock.
 * - All container spawning, gVisor (runsc) kernel isolation, and cgroups v2 resource
 *   enforcement remain strictly on private sandbox-host EC2 instances.
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

export interface RemoteSandboxDriverOptions {
  runnerUrl: string;
  secret?: string;
  timeoutMs?: number;
}

export class RemoteSandboxDriver implements SandboxDriver {
  readonly name = "remote";
  private runnerUrl: string;
  private secret?: string;
  private timeoutMs: number;

  constructor(options: RemoteSandboxDriverOptions) {
    this.runnerUrl = options.runnerUrl.replace(/\/+$/, "");
    this.secret = options.secret || process.env.RUNNER_SHARED_SECRET;
    this.timeoutMs = options.timeoutMs || 30000;
  }

  private getHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };
    if (this.secret) {
      headers["Authorization"] = `Bearer ${this.secret}`;
    }
    return headers;
  }

  async isAvailable(): Promise<boolean> {
    try {
      const res = await fetch(`${this.runnerUrl}/healthz`, {
        headers: this.getHeaders(),
        signal: AbortSignal.timeout(5000),
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  async start(spec: SandboxSpec): Promise<SandboxInstance> {
    const headers = this.getHeaders();
    if (spec.callerOrgId) {
      headers["x-caller-org-id"] = spec.callerOrgId;
    }
    const res = await fetch(`${this.runnerUrl}/v1/sandboxes/start`, {
      method: "POST",
      headers,
      body: JSON.stringify(spec),
      signal: AbortSignal.timeout(this.timeoutMs),
    });

    if (!res.ok) {
      const errText = await res.text();
      let errJson: any = null;
      try {
        errJson = JSON.parse(errText);
      } catch {}
      const err = new Error(
        errJson?.error
          ? `[${errJson.error}] ${errJson.message}`
          : errJson?.message ||
              `Remote runner failed to start sandbox (HTTP ${res.status}): ${errText}`,
      );
      if (errJson?.code || errJson?.error)
        (err as any).code = errJson.code || errJson.error;
      if (res.status === 503) (err as any).code = "SANDBOX_UNAVAILABLE";
      throw err;
    }

    const instance = (await res.json()) as any;
    return {
      ...instance,
      createdAt: new Date(instance.createdAt),
      startedAt: instance.startedAt ? new Date(instance.startedAt) : undefined,
      lastActiveAt: new Date(instance.lastActiveAt),
    };
  }

  async stop(instanceId: string): Promise<void> {
    const res = await fetch(
      `${this.runnerUrl}/v1/sandboxes/${encodeURIComponent(instanceId)}/stop`,
      {
        method: "POST",
        headers: this.getHeaders(),
        signal: AbortSignal.timeout(15000),
      },
    );
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(
        `Remote runner failed to stop sandbox ${instanceId}: ${errText}`,
      );
    }
  }

  async suspend(instanceId: string): Promise<void> {
    const res = await fetch(
      `${this.runnerUrl}/v1/sandboxes/${encodeURIComponent(instanceId)}/suspend`,
      {
        method: "POST",
        headers: this.getHeaders(),
        signal: AbortSignal.timeout(10000),
      },
    );
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(
        `Remote runner failed to suspend sandbox ${instanceId}: ${errText}`,
      );
    }
  }

  async resume(instanceId: string): Promise<void> {
    const res = await fetch(
      `${this.runnerUrl}/v1/sandboxes/${encodeURIComponent(instanceId)}/resume`,
      {
        method: "POST",
        headers: this.getHeaders(),
        signal: AbortSignal.timeout(10000),
      },
    );
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(
        `Remote runner failed to resume sandbox ${instanceId}: ${errText}`,
      );
    }
  }

  async status(instanceId: string): Promise<SandboxStatus> {
    const res = await fetch(
      `${this.runnerUrl}/v1/sandboxes/${encodeURIComponent(instanceId)}/status`,
      {
        method: "GET",
        headers: this.getHeaders(),
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!res.ok) {
      return "stopped";
    }
    const data = (await res.json()) as any;
    return data.status as SandboxStatus;
  }

  async logs(instanceId: string, options?: LogOptions): Promise<string[]> {
    const query = new URLSearchParams();
    if (options?.tail) query.set("tail", String(options.tail));
    if (options?.since) query.set("since", options.since.toISOString());

    const res = await fetch(
      `${this.runnerUrl}/v1/sandboxes/${encodeURIComponent(instanceId)}/logs?${query.toString()}`,
      {
        method: "GET",
        headers: this.getHeaders(),
        signal: AbortSignal.timeout(10000),
      },
    );
    if (!res.ok) return [];
    const data = (await res.json()) as any;
    return data.logs || [];
  }

  async forwardRequest(
    instanceId: string,
    req: ForwardRequest,
  ): Promise<ForwardResponse> {
    const res = await fetch(
      `${this.runnerUrl}/v1/sandboxes/${encodeURIComponent(instanceId)}/forward`,
      {
        method: "POST",
        headers: this.getHeaders(),
        body: JSON.stringify({
          method: req.method,
          path: req.path,
          headers: req.headers,
          body:
            typeof req.body === "string"
              ? req.body
              : req.body
                ? req.body.toString("base64")
                : undefined,
          isBase64: Buffer.isBuffer(req.body),
        }),
        signal: AbortSignal.timeout(this.timeoutMs),
      },
    );

    if (!res.ok && res.status >= 500) {
      const errText = await res.text();
      let errJson: any = null;
      try {
        errJson = JSON.parse(errText);
      } catch {}
      const err = new Error(
        errJson?.message ||
          `Remote runner error forwarding request: ${errText}`,
      );
      if (errJson?.code) (err as any).code = errJson.code;
      if (res.status === 503) (err as any).code = "SANDBOX_UNAVAILABLE";
      throw err;
    }

    return (await res.json()) as ForwardResponse;
  }

  async recover(instanceId: string): Promise<SandboxInstance> {
    const res = await fetch(
      `${this.runnerUrl}/v1/sandboxes/${encodeURIComponent(instanceId)}/recover`,
      {
        method: "POST",
        headers: this.getHeaders(),
        signal: AbortSignal.timeout(this.timeoutMs),
      },
    );

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(
        `Remote runner failed to recover sandbox ${instanceId}: ${errText}`,
      );
    }

    const instance = (await res.json()) as any;
    return {
      ...instance,
      createdAt: new Date(instance.createdAt),
      startedAt: instance.startedAt ? new Date(instance.startedAt) : undefined,
      lastActiveAt: new Date(instance.lastActiveAt),
    };
  }

  async destroy(instanceId: string): Promise<void> {
    const res = await fetch(
      `${this.runnerUrl}/v1/sandboxes/${encodeURIComponent(instanceId)}/destroy`,
      {
        method: "POST",
        headers: this.getHeaders(),
        signal: AbortSignal.timeout(15000),
      },
    );
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(
        `Remote runner failed to destroy sandbox ${instanceId}: ${errText}`,
      );
    }
  }
}

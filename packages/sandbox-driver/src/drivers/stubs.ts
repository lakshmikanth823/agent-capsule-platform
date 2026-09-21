/**
 * Documented stubs for production Sandbox Drivers.
 *
 * In Phase 0, development uses DockerDevDriver. Production environments
 * require a hardware-virtualized or syscall-intercepting driver to satisfy
 * Security Invariant 1 ("Treat all application code as hostile").
 */
import type {
  SandboxDriver,
  SandboxSpec,
  SandboxInstance,
  SandboxStatus,
  LogOptions,
  ForwardRequest,
  ForwardResponse,
} from '../interface.js';

export class NotImplementedError extends Error {
  constructor(driverName: string, details: string) {
    super(
      `[${driverName}] Production driver is not implemented in Phase 0. ${details} Use DockerDevDriver for development and testing.`
    );
    this.name = 'NotImplementedError';
  }
}

/**
 * GVisorDriver (Production Stub)
 *
 * Architecture:
 * - Runtime: gVisor `runsc` (syscall-intercepting sandbox).
 * - Sentry: Implements a user-space Linux kernel in Go, preventing untrusted
 *   application code from executing raw syscalls against the host kernel.
 * - Gofer: File proxy process mediating all filesystem access.
 * - Netstack: User-space network stack enabling fine-grained egress filtering
 *   and network isolation without host iptables manipulation.
 *
 * Security boundary: Strong process and kernel boundary.
 */
export class GVisorDriver implements SandboxDriver {
  readonly name = 'gvisor';

  async start(_spec: SandboxSpec): Promise<SandboxInstance> {
    throw new NotImplementedError(this.name, 'Configured via `docker run --runtime=runsc`.');
  }

  async stop(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Stops runsc container.');
  }

  async suspend(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Freezes runsc container via cgroups v2 freezer.');
  }

  async resume(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Thaws runsc container.');
  }

  async status(_instanceId: string): Promise<SandboxStatus> {
    throw new NotImplementedError(this.name, 'Queries runsc state.');
  }

  async logs(_instanceId: string, _options?: LogOptions): Promise<string[]> {
    throw new NotImplementedError(this.name, 'Fetches runsc console logs.');
  }

  async forwardRequest(_instanceId: string, _req: ForwardRequest): Promise<ForwardResponse> {
    throw new NotImplementedError(this.name, 'Forwards request via Netstack tap device.');
  }

  async recover(_instanceId: string): Promise<SandboxInstance> {
    throw new NotImplementedError(this.name, 'Recovers runsc sandbox.');
  }

  async destroy(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Destroys runsc sandbox.');
  }
}

/**
 * FirecrackerDriver (Production Stub)
 *
 * Architecture:
 * - Runtime: Firecracker microVMs (KVM-based).
 * - Minimal virtual machine with <5MB memory overhead and cold start <5ms.
 * - Jailer: Strips privileges, drops capabilities, chroots into a read-only jail,
 *   and applies tight seccomp filters to the microVM process.
 * - Storage: Drive images mounted over virtio-block.
 * - Network: TAP devices with strict iptables/nftables egress policy rules.
 * - Communication: vsock (AF_VSOCK) between host control plane and in-VM guest agent.
 *
 * Security boundary: Hardware-assisted virtualization (KVM).
 */
export class FirecrackerDriver implements SandboxDriver {
  readonly name = 'firecracker';

  async start(_spec: SandboxSpec): Promise<SandboxInstance> {
    throw new NotImplementedError(this.name, 'Spawns Firecracker microVM via Jailer.');
  }

  async stop(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Sends shutdown signal to microVM.');
  }

  async suspend(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Pauses microVM vCPUs.');
  }

  async resume(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Resumes microVM vCPUs.');
  }

  async status(_instanceId: string): Promise<SandboxStatus> {
    throw new NotImplementedError(this.name, 'Queries microVM state via Firecracker API socket.');
  }

  async logs(_instanceId: string, _options?: LogOptions): Promise<string[]> {
    throw new NotImplementedError(this.name, 'Streams microVM serial console/log pipe.');
  }

  async forwardRequest(_instanceId: string, _req: ForwardRequest): Promise<ForwardResponse> {
    throw new NotImplementedError(this.name, 'Routes request to microVM via vsock or TAP interface.');
  }

  async recover(_instanceId: string): Promise<SandboxInstance> {
    throw new NotImplementedError(this.name, 'Restarts Firecracker microVM from snapshot.');
  }

  async destroy(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Kills microVM process and unmounts drive.');
  }
}

/**
 * ManagedSandboxDriver (Production Stub)
 *
 * Architecture:
 * - Cloud-managed micro-container or serverless sandbox provider (e.g. AWS Fargate,
 *   GCP Cloud Run with gVisor sandbox, or Fly.io Machines).
 */
export class ManagedSandboxDriver implements SandboxDriver {
  readonly name = 'managed-provider';

  async start(_spec: SandboxSpec): Promise<SandboxInstance> {
    throw new NotImplementedError(this.name, 'Provisions managed container instance.');
  }

  async stop(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Stops managed container instance.');
  }

  async suspend(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Scales instance to zero.');
  }

  async resume(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'Wakes instance from zero.');
  }

  async status(_instanceId: string): Promise<SandboxStatus> {
    throw new NotImplementedError(this.name, 'Queries provider instance health API.');
  }

  async logs(_instanceId: string, _options?: LogOptions): Promise<string[]> {
    throw new NotImplementedError(this.name, 'Streams cloud provider logs.');
  }

  async forwardRequest(_instanceId: string, _req: ForwardRequest): Promise<ForwardResponse> {
    throw new NotImplementedError(this.name, 'Proxies HTTP request to managed endpoint.');
  }

  async recover(_instanceId: string): Promise<SandboxInstance> {
    throw new NotImplementedError(this.name, 'Recreates managed instance.');
  }

  async destroy(_instanceId: string): Promise<void> {
    throw new NotImplementedError(this.name, 'De-provisions managed instance.');
  }
}

export * from './interface.js';

/**
 * DevMockSandboxDriver
 * WARNING: This is a development-only mock driver.
 * It is NOT a security boundary. It exists solely for lightweight unit testing.
 */
export class DevMockSandboxDriver {
  readonly name = 'dev-mock-driver';
  private instances = new Map<string, any>();

  async create(spec: any) {
    const instance = {
      id: `mock-${spec.capsuleId}`,
      capsuleId: spec.capsuleId,
      status: 'pending',
      assignedPort: spec.port || 3000,
      createdAt: new Date(),
    };
    this.instances.set(instance.id, instance);
    return instance;
  }

  async start(id: string) {
    const inst = this.instances.get(id);
    if (inst) inst.status = 'running';
  }

  async stop(id: string) {
    const inst = this.instances.get(id);
    if (inst) inst.status = 'stopped';
  }

  async destroy(id: string) {
    this.instances.delete(id);
  }

  async inspect(id: string) {
    return this.instances.get(id) || null;
  }
}

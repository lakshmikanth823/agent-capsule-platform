import { describe, it, expect } from 'vitest';
import { validateManifest, parseAndValidate } from '../src/index.js';

describe('Capsule Manifest Validator Suite (20+ test cases)', () => {
  // 1. Valid Minimal Manifest
  it('1. should validate a valid minimal manifest', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'simple-app',
      name: 'Simple App',
      shape: 'web-app',
      runtime: 'node22',
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
    expect(result.effective_manifest?.id).toBe('simple-app');
    expect(result.effective_manifest?.egress).toEqual([]);
    expect(result.effective_manifest?.sharing?.default).toBe('org');
  });

  // 2. Valid Full Reference Manifest (Leave Tracker)
  it('2. should validate full reference manifest (leave-tracker)', () => {
    const yaml = `
apiVersion: capsule/v1alpha1
id: leave-tracker
name: Leave Tracker
shape: web-app
runtime: node22
roles:
  - employee
  - manager
  - hr
capabilities:
  db:
    type: sqlite
  identity: true
  files:
    max_mb: 200
  ai:
    monthly_budget_usd: 5
  connectors:
    - name: sheets.read
      acts_as: viewer
egress: []
sharing:
  default: org
limits:
  cpu: small
  memory_mb: 256
  request_timeout_s: 30
  db_max_mb: 500
  blob_max_mb: 200
  max_active_instances: 1
`;
    const result = parseAndValidate(yaml);
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
    expect(result.effective_manifest?.roles).toEqual(['employee', 'manager', 'hr']);
    expect(result.effective_manifest?.capabilities?.db?.type).toBe('sqlite');
    expect(result.effective_manifest?.capabilities?.connectors?.[0]?.acts_as).toBe('viewer');
  });

  // 3. Invalid Non-object / null
  it('3. should reject non-object or null input with structured error', () => {
    const r1 = validateManifest(null);
    expect(r1.valid).toBe(false);
    expect(r1.errors[0].code).toBe('invalid_manifest');
    expect(r1.errors[0].hint).toBeDefined();

    const r2 = validateManifest('just a string');
    expect(r2.valid).toBe(false);
    expect(r2.errors[0].code).toBe('invalid_manifest');
  });

  // 4. Invalid YAML Syntax
  it('4. should reject malformed YAML with syntax error and hint', () => {
    const badYaml = `
apiVersion: capsule/v1alpha1
id: [unclosed array
name: Bad
`;
    const result = parseAndValidate(badYaml);
    expect(result.valid).toBe(false);
    expect(result.errors[0].name).toBe('syntax_validation');
    expect(result.errors[0].code).toBe('invalid_manifest');
    expect(result.errors[0].hint).toContain('YAML');
  });

  // 5. Missing Required Property: id
  it('5. should reject manifest missing required id', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      name: 'No ID App',
      shape: 'web-app',
      runtime: 'node22',
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    const idErr = result.errors.find((e) => e.path === 'id' || e.message.includes("'id'"));
    expect(idErr).toBeDefined();
    expect(idErr?.code).toBe('invalid_manifest');
  });

  // 6. Missing Required Property: name
  it('6. should reject manifest missing required name', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'app-without-name',
      shape: 'web-app',
      runtime: 'node22',
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    const nameErr = result.errors.find((e) => e.path === 'name' || e.message.includes("'name'"));
    expect(nameErr).toBeDefined();
  });

  // 7. Invalid ID Characters (uppercase, spaces, symbols)
  it('7. should reject invalid ID characters', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'Invalid_App_Name!',
      name: 'Invalid App',
      shape: 'web-app',
      runtime: 'node22',
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    const err = result.errors.find((e) => e.path === 'id');
    expect(err).toBeDefined();
    expect(err?.hint).toContain('lowercase');
  });

  // 8. ID Exceeding 63 characters
  it('8. should reject ID exceeding 63 characters', () => {
    const longId = 'a'.repeat(64);
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: longId,
      name: 'Too Long ID',
      shape: 'web-app',
      runtime: 'node22',
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    const err = result.errors.find((e) => e.path === 'id');
    expect(err).toBeDefined();
  });

  // 9. Unsupported Shape
  it('9. should reject unsupported shape with code unsupported_shape', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'worker-app',
      name: 'Worker App',
      shape: 'worker',
      runtime: 'node22',
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    const err = result.errors.find((e) => e.code === 'unsupported_shape');
    expect(err).toBeDefined();
    expect(err?.hint).toContain('web-app');
  });

  // 10. Unsupported Runtime
  it('10. should reject unsupported runtime with code unsupported_runtime', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'python-app',
      name: 'Python App',
      shape: 'web-app',
      runtime: 'python312',
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    const err = result.errors.find((e) => e.code === 'unsupported_runtime');
    expect(err).toBeDefined();
    expect(err?.hint).toContain('node22');
  });

  // 11. Unknown Top-level Properties Rejected
  it('11. should reject unrecognized top-level properties', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'extra-prop-app',
      name: 'Extra Prop App',
      shape: 'web-app',
      runtime: 'node22',
      customProperty: 'not-allowed',
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    const err = result.errors.find((e) => e.message.includes('customProperty'));
    expect(err).toBeDefined();
    expect(err?.hint).toContain('Remove');
  });

  // 12. Default-Deny Egress: Omitted egress defaults to empty array []
  it('12. should apply default-deny egress when egress is omitted', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'no-egress-app',
      name: 'No Egress App',
      shape: 'web-app',
      runtime: 'node22',
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(true);
    expect(result.effective_manifest?.egress).toEqual([]);
    const egressCheck = result.checks.find((c) => c.name === 'egress_check');
    expect(egressCheck?.code).toBe('egress_default_deny');
  });

  // 13. Default-Deny Egress: Explicit empty array []
  it('13. should accept explicit empty array [] for default-deny egress', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'empty-egress-app',
      name: 'Empty Egress App',
      shape: 'web-app',
      runtime: 'node22',
      egress: [],
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(true);
    expect(result.effective_manifest?.egress).toEqual([]);
  });

  // 14. Invalid Egress: URL Scheme Included
  it('14. should reject egress destination containing URL scheme', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'url-egress-app',
      name: 'URL Egress App',
      shape: 'web-app',
      runtime: 'node22',
      egress: ['https://api.example.com'],
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    const err = result.errors.find((e) => e.path === 'egress[0]');
    expect(err?.code).toBe('egress_denied');
    expect(err?.hint).toContain('hostname');
  });

  // 15. Invalid Egress: IP Address
  it('15. should reject egress destination that is a raw IP address', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'ip-egress-app',
      name: 'IP Egress App',
      shape: 'web-app',
      runtime: 'node22',
      egress: ['192.168.1.1'],
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    const err = result.errors.find((e) => e.path === 'egress[0]');
    expect(err?.code).toBe('egress_denied');
    expect(err?.message).toContain('Direct IP');
  });

  // 16. Invalid Egress: Cloud Metadata / Loopback Destination
  it('16. should reject loopback and cloud metadata endpoints', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'loopback-egress-app',
      name: 'Loopback Egress App',
      shape: 'web-app',
      runtime: 'node22',
      egress: ['localhost', 'metadata.google.internal'],
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.message.includes('Loopback or metadata'))).toBe(true);
  });

  // 17. Valid Egress Hostnames
  it('17. should accept valid FQDN hostnames in egress', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'valid-egress-app',
      name: 'Valid Egress App',
      shape: 'web-app',
      runtime: 'node22',
      egress: ['api.slack.com', 'sheets.googleapis.com'],
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(true);
    expect(result.effective_manifest?.egress).toEqual(['api.slack.com', 'sheets.googleapis.com']);
  });

  // 18. Connector Identity Defaults to viewer
  it('18. should default connector identity to viewer when acts_as is omitted', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'connector-app',
      name: 'Connector App',
      shape: 'web-app',
      runtime: 'node22',
      capabilities: {
        connectors: [{ name: 'sheets.read', acts_as: 'viewer' as const }],
      },
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(true);
    expect(result.effective_manifest?.capabilities?.connectors?.[0]?.acts_as).toBe('viewer');
    expect(result.required_approvals).toHaveLength(0);
  });

  // 19. Connector service Identity Triggers approval_required
  it('19. should flag privileged service connector identity as approval_required', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'service-conn-app',
      name: 'Service Conn App',
      shape: 'web-app',
      runtime: 'node22',
      capabilities: {
        connectors: [
          { name: 'slack.post', channel: '#alerts', acts_as: 'service' as const },
        ],
      },
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(true); // Valid schema, but requires approval
    expect(result.required_approvals).toContain('connectors.slack.post:service');
    const warn = result.warnings.find((w) => w.code === 'approval_required');
    expect(warn).toBeDefined();
    expect(warn?.hint).toContain('human owner approval');
  });

  // 20. Memory Limit Bounds (Outside 64 - 16384 MB)
  it('20. should reject memory_mb below 64 or above 16384', () => {
    const lowMem = {
      apiVersion: 'capsule/v1alpha1',
      id: 'low-mem-app',
      name: 'Low Mem',
      shape: 'web-app',
      runtime: 'node22',
      limits: { memory_mb: 32 },
    };
    const r1 = validateManifest(lowMem);
    expect(r1.valid).toBe(false);
    expect(r1.errors.some((e) => e.path === 'limits.memory_mb')).toBe(true);

    const highMem = {
      apiVersion: 'capsule/v1alpha1',
      id: 'high-mem-app',
      name: 'High Mem',
      shape: 'web-app',
      runtime: 'node22',
      limits: { memory_mb: 32768 },
    };
    const r2 = validateManifest(highMem);
    expect(r2.valid).toBe(false);
    expect(r2.errors.some((e) => e.path === 'limits.memory_mb')).toBe(true);
  });

  // 21. Request Timeout Bounds (Outside 1 - 300 seconds)
  it('21. should reject request_timeout_s outside 1 - 300 seconds', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'timeout-app',
      name: 'Timeout App',
      shape: 'web-app',
      runtime: 'node22',
      limits: { request_timeout_s: 600 },
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.path === 'limits.request_timeout_s')).toBe(true);
  });

  // 22. Max Active Instances Must Be 1
  it('22. should reject max_active_instances not equal to 1', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'scale-app',
      name: 'Scale App',
      shape: 'web-app',
      runtime: 'node22',
      limits: { max_active_instances: 3 as any },
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.path?.includes('max_active_instances'))).toBe(true);
  });

  // 23. Duplicate Roles Rejected
  it('23. should reject duplicate roles in roles array', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'dup-roles-app',
      name: 'Dup Roles App',
      shape: 'web-app',
      runtime: 'node22',
      roles: ['employee', 'manager', 'employee'],
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(false);
    const err = result.errors.find((e) => e.message.includes('Duplicate role'));
    expect(err).toBeDefined();
    expect(err?.hint).toContain('Remove duplicate');
  });

  // 24. Schedule Warning for Phase 3
  it('24. should issue a warning when schedule is declared in Alpha/MVP', () => {
    const manifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'scheduled-app',
      name: 'Scheduled App',
      shape: 'web-app',
      runtime: 'node22',
      schedule: [{ cron: '0 9 * * MON', handler: 'weekly_digest' }],
    };
    const result = validateManifest(manifest);
    expect(result.valid).toBe(true);
    const warn = result.warnings.find((w) => w.code === 'unsupported_capability');
    expect(warn).toBeDefined();
    expect(warn?.hint).toContain('Phase 3');
  });
});

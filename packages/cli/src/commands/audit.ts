/**
 * capsule audit
 * Implements tamper-evident audit inspection, hash chain verification, export, and retention commands.
 */
import fs from 'node:fs';
import path from 'node:path';
import { ApiClient } from '../client.js';
import { outputResult, outputError, CliError } from '../errors.js';

async function resolveOrgId(client: ApiClient): Promise<string> {
  try {
    const user = await client.request('/v1/auth/me');
    if (user?.organization_id) {
      return user.organization_id;
    }
  } catch {
    // ignore
  }
  throw new CliError({
    code: 'NOT_AUTHENTICATED',
    message: 'Could not determine caller organization. Please run `capsule login` first.',
    exitCode: 1,
    hint: 'Run `capsule login` to authenticate.',
  });
}

export interface AuditListOptions {
  app?: string;
  action?: string;
  outcome?: string;
  agentOrTool?: string;
  limit?: string | number;
  json?: boolean;
}

export async function auditListCommand(options: AuditListOptions = {}): Promise<void> {
  const client = new ApiClient();
  try {
    const orgId = await resolveOrgId(client);
    const params = new URLSearchParams();
    if (options.app) params.set('app_id', options.app);
    if (options.action) params.set('action', options.action);
    if (options.outcome) params.set('outcome', options.outcome);
    if (options.agentOrTool) params.set('agent_or_tool', options.agentOrTool);
    if (options.limit) params.set('limit', String(options.limit));

    const query = params.toString() ? `?${params.toString()}` : '';
    const res = await client.request(`/v1/organizations/${orgId}/audit/events${query}`);

    outputResult(res, options, () => {
      const items = res.items || [];
      if (items.length === 0) {
        console.log('No audit records found matching criteria.');
        return;
      }
      console.log(`Audit Log for Organization ${orgId} (Total: ${res.total}):`);
      console.log('--------------------------------------------------------------------------------------------------');
      console.log('SEQ #  | TIMESTAMP                 | ACTION               | OUTCOME | ACTOR / TOOL            | EVENT HASH');
      console.log('--------------------------------------------------------------------------------------------------');
      for (const e of items) {
        const seq = String(e.sequence_number ?? '-').padEnd(6);
        const time = new Date(e.occurred_at).toISOString().slice(0, 19).padEnd(25);
        const act = String(e.action).slice(0, 20).padEnd(20);
        const out = String(e.outcome).slice(0, 7).padEnd(7);
        const actor = `${e.actor_agent || 'user'}:${e.actor_tool || 'web'}`.slice(0, 23).padEnd(23);
        const hash = e.event_hash ? e.event_hash.slice(0, 10) + '...' : '-';
        console.log(`${seq} | ${time} | ${act} | ${out} | ${actor} | ${hash}`);
      }
    });
  } catch (err: any) {
    outputError(err, options);
  }
}

export interface AuditVerifyOptions {
  json?: boolean;
}

export async function auditVerifyCommand(options: AuditVerifyOptions = {}): Promise<void> {
  const client = new ApiClient();
  try {
    const orgId = await resolveOrgId(client);
    const report = await client.request(`/v1/organizations/${orgId}/audit/verify`, {
      method: 'POST',
    });

    outputResult(report, options, () => {
      if (report.valid) {
        console.log('Audit Hash Chain Status: VALID [OK]');
        console.log(`Organization: ${report.organization_id}`);
        console.log(`Total Events Verified: ${report.total_events}`);
        console.log(`Sequence Range: #${report.first_sequence ?? 0} to #${report.last_sequence ?? 0}`);
        console.log(
          report.checkpoint
            ? `Anchored Checkpoint: seq #${report.checkpoint.sequence} (hash: ${report.checkpoint.hash.slice(0, 12)}...)`
            : 'Genesis Chain: Continuous from sequence #1'
        );
        console.log('Result: Zero sequence gaps, zero reorderings, and zero data alterations detected.');
      } else {
        console.log('Audit Hash Chain Status: TAMPERED / BROKEN [FAILED]');
        console.log(`Organization: ${report.organization_id}`);
        console.log(`Tampered At Sequence: #${report.tampered_at_sequence}`);
        console.log(`Failure Reason: ${report.reason}`);
        console.log('WARNING: Database mutation or row deletion detected in violation of immutability invariant!');
      }
    });
  } catch (err: any) {
    outputError(err, options);
  }
}

export interface AuditExportOptions {
  format?: 'csv' | 'json';
  output?: string;
  app?: string;
  action?: string;
  outcome?: string;
  json?: boolean;
}

export async function auditExportCommand(options: AuditExportOptions = {}): Promise<void> {
  const client = new ApiClient();
  try {
    const orgId = await resolveOrgId(client);
    const fmt = options.format || 'json';
    const params = new URLSearchParams();
    params.set('format', fmt);
    if (options.app) params.set('app_id', options.app);
    if (options.action) params.set('action', options.action);
    if (options.outcome) params.set('outcome', options.outcome);

    const baseUrl = client.apiUrl.replace(/\/$/, '');
    const url = `${baseUrl}/v1/organizations/${orgId}/audit/export?${params.toString()}`;

    const headers: Record<string, string> = {};
    if (client.token) {
      headers['Authorization'] = `Bearer ${client.token}`;
    }

    const res = await fetch(url, { headers });
    if (!res.ok) {
      throw new CliError({
        code: 'EXPORT_FAILED',
        message: `Export failed with HTTP ${res.status}: ${res.statusText}`,
        exitCode: 1,
      });
    }

    const content = await res.text();
    if (options.output) {
      const target = path.resolve(process.cwd(), options.output);
      fs.writeFileSync(target, content, 'utf8');
      outputResult({ exported_to: target, format: fmt }, options, () => {
        console.log(`Audit log exported to ${target}`);
      });
    } else {
      process.stdout.write(content);
    }
  } catch (err: any) {
    outputError(err, options);
  }
}

export interface AuditRetentionOptions {
  json?: boolean;
}

export async function auditRetentionCommand(options: AuditRetentionOptions = {}): Promise<void> {
  const client = new ApiClient();
  try {
    const orgId = await resolveOrgId(client);
    const res = await client.request(`/v1/organizations/${orgId}/audit/retention/enforce`, {
      method: 'POST',
    });

    outputResult(res, options, () => {
      console.log('Retention Policy Enforcement Complete:');
      console.log(`Organization: ${res.organization_id}`);
      console.log(`Retention Policy: ${res.retention_days} days`);
      console.log(`Pruned Records: ${res.purged_count}`);
      console.log(
        res.checkpoint
          ? `Checkpoint Anchor: seq #${res.checkpoint.sequence} (hash: ${res.checkpoint.hash.slice(0, 12)}...)`
          : 'No records exceeded retention cutoff.'
      );
    });
  } catch (err: any) {
    outputError(err, options);
  }
}

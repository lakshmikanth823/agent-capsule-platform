/**
 * capsule inventory & governance commands (Prompt 20 / FR-033 to FR-036)
 */
import { ApiClient } from '../client.js';
import { outputResult, outputError, CliError } from '../errors.js';

async function resolveOrgId(client: ApiClient, overrideOrg?: string): Promise<string> {
  if (overrideOrg) return overrideOrg;
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

export interface InventoryOptions {
  org?: string;
  status?: string;
  format?: 'table' | 'csv' | 'json';
  json?: boolean;
}

export async function inventoryCommand(options: InventoryOptions = {}): Promise<void> {
  const client = new ApiClient();
  try {
    const orgId = await resolveOrgId(client, options.org);
    const format = options.json ? 'json' : options.format || 'table';

    if (format === 'csv') {
      const csvRes = await client.request(`/v1/organizations/${orgId}/inventory/export?format=csv`);
      console.log(typeof csvRes === 'string' ? csvRes : JSON.stringify(csvRes));
      return;
    }

    const res = await client.request(`/v1/organizations/${orgId}/inventory`);
    let items = res.items || [];
    if (options.status) {
      items = items.filter((i: any) => i.status === options.status);
    }

    outputResult({ organization_id: orgId, total: items.length, items }, options, () => {
      if (items.length === 0) {
        console.log('No applications found in organization inventory.');
        return;
      }
      console.log(`Application Inventory for Org ${orgId} (Total: ${items.length}):`);
      console.log('------------------------------------------------------------------------------------------------------------------------');
      console.log('KEY                  | NAME                     | STATUS    | GOV STATE       | USERS | VERSION | OWNER');
      console.log('------------------------------------------------------------------------------------------------------------------------');
      for (const a of items) {
        const key = (a.app_key || '').padEnd(20).slice(0, 20);
        const name = (a.name || '').padEnd(24).slice(0, 24);
        const status = (a.status || '').padEnd(9).slice(0, 9);
        const gov = (a.governance_state || 'normal').padEnd(15).slice(0, 15);
        const users = String(a.user_count || 1).padEnd(5);
        const ver = (a.current_version || 'v1').padEnd(7);
        const owner = a.owner ? a.owner.email : 'Unowned (Grace Period)';
        console.log(`${key} | ${name} | ${status} | ${gov} | ${users} | ${ver} | ${owner}`);
      }
      console.log('------------------------------------------------------------------------------------------------------------------------');
    });
  } catch (err: any) {
    outputError(err, options);
  }
}

export interface TransferOwnershipOptions {
  newOwner: string;
  reason?: string;
  json?: boolean;
}

export async function transferOwnershipCommand(
  appKey: string,
  options: TransferOwnershipOptions
): Promise<void> {
  const client = new ApiClient();
  try {
    if (!options.newOwner) {
      throw new CliError({
        code: 'MISSING_ARGUMENT',
        message: 'Missing required option --new-owner <userId>',
        exitCode: 1,
      });
    }

    const payload = {
      new_owner_user_id: options.newOwner,
      reason: options.reason || 'Manual transfer via CLI',
    };

    const res = await client.request(`/v1/apps/${appKey}/transfer-ownership`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    outputResult(res, options, () => {
      console.log(`Successfully transferred ownership of '${appKey}' to user '${options.newOwner}'.`);
      console.log(`Status: ${res.status} | Governance State: ${res.governance_state}`);
    });
  } catch (err: any) {
    outputError(err, options);
  }
}

export interface SetGovernanceOptions {
  nominee?: string;
  expiresInDays?: string | number;
  inactivityLimitDays?: string | number;
  purgeDays?: string | number;
  json?: boolean;
}

export async function setGovernanceCommand(
  appKey: string,
  options: SetGovernanceOptions
): Promise<void> {
  const client = new ApiClient();
  try {
    const payload: Record<string, any> = {};
    if (options.nominee) payload.nominated_owner_user_id = options.nominee;
    if (options.expiresInDays) {
      const d = new Date();
      d.setDate(d.getDate() + Number(options.expiresInDays));
      payload.expires_at = d.toISOString();
    }
    if (options.inactivityLimitDays) payload.inactivity_days_limit = Number(options.inactivityLimitDays);
    if (options.purgeDays) payload.purge_after_days = Number(options.purgeDays);

    const res = await client.request(`/v1/apps/${appKey}/governance`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });

    outputResult(res, options, () => {
      console.log(`Successfully updated governance settings for capsule '${appKey}'.`);
      console.log(JSON.stringify(res, null, 2));
    });
  } catch (err: any) {
    outputError(err, options);
  }
}

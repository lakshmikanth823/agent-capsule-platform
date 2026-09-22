/**
 * Software Capsule CLI (`capsule`)
 * The primary agent- and developer-facing interface for the Capsule Platform.
 */
import { Command } from 'commander';
import { loginCommand } from './commands/login.js';
import { initCommand } from './commands/init.js';
import { validateCommand } from './commands/validate.js';
import { devCommand } from './commands/dev.js';
import { publishCommand } from './commands/publish.js';
import { shareAddCommand, shareListCommand, shareRevokeCommand } from './commands/share.js';
import { unshareCommand } from './commands/unshare.js';
import { statusCommand } from './commands/status.js';
import { logsCommand } from './commands/logs.js';
import { versionsCommand } from './commands/versions.js';
import { rollbackCommand } from './commands/rollback.js';
import { suspendCommand } from './commands/suspend.js';
import { resumeCommand } from './commands/resume.js';
import {
  auditListCommand,
  auditVerifyCommand,
  auditExportCommand,
  auditRetentionCommand,
} from './commands/audit.js';
import {
  inventoryCommand,
  transferOwnershipCommand,
  setGovernanceCommand,
} from './commands/inventory.js';

export function createProgram(): Command {
  const program = new Command();

  program
    .name('capsule')
    .description('Software Capsule Platform CLI for publishing, sharing, and managing small apps')
    .version('0.1.0');

  // 1. login
  program
    .command('login')
    .description('Authenticate with the Capsule Platform')
    .option('--user <email>', 'User email for local dev / mock authentication')
    .option('--url <apiUrl>', 'Control-plane API base URL')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => loginCommand(opts));

  // 2. init
  program
    .command('init [name]')
    .description('Initialize a new capsule in the current or named directory')
    .option('--json', 'Output machine-readable JSON')
    .action((name, opts) => initCommand(name, opts));

  // 3. validate
  program
    .command('validate')
    .description('Validate capsule.manifest.yaml offline without deploying')
    .option('--manifest <path>', 'Path to manifest file (defaults to capsule.manifest.yaml)')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => validateCommand(opts));

  // 4. dev
  program
    .command('dev')
    .description('Start local emulator for the blessed application shape')
    .option('--port <port>', 'Local port to listen on (default 3000)')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => devCommand(opts));

  // 5. publish
  program
    .command('publish')
    .description('Idempotently publish the current capsule project')
    .option('--description <desc>', 'Version release notes or description')
    .option('--expected-version <n>', 'Enforce optimistic concurrency against current version')
    .option('--dry-run', 'Run validation and admission checks without deploying')
    .option('--wait', 'Wait for deployment to become active')
    .option('--manifest <path>', 'Path to manifest file')
    .option('--idempotency-key <key>', 'Custom idempotency key (defaults to UUIDv4)')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => publishCommand(opts));

  // 6. share command tree
  const shareCmd = program
    .command('share')
    .description('Manage capsule sharing and application role assignments');

  shareCmd
    .command('add')
    .description('Share a capsule with a user or group and assign an application role')
    .requiredOption('--role <role>', 'Application role to assign (e.g. employee, manager)')
    .option('--user <email>', 'User email to share with')
    .option('--group <group>', 'Group name to share with')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--expires-at <timestamp>', 'Optional expiration timestamp (ISO 8601)')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => shareAddCommand(opts));

  shareCmd
    .command('list')
    .description('List current sharing assignments for a capsule')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => shareListCommand(opts));

  shareCmd
    .command('revoke <shareId>')
    .description('Revoke an existing sharing assignment by share ID')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--json', 'Output machine-readable JSON')
    .action((shareId, opts) => shareRevokeCommand(shareId, opts));

  // 7. unshare alias
  program
    .command('unshare <shareId>')
    .description('Revoke an existing sharing assignment (alias for `capsule share revoke`)')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--json', 'Output machine-readable JSON')
    .action((shareId, opts) => unshareCommand(shareId, opts));

  // 8. status
  program
    .command('status')
    .description('Query current capsule status and active deployment')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => statusCommand(opts));

  // 9. logs
  program
    .command('logs')
    .description('Retrieve logs from the capsule container')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--tail <n>', 'Number of lines to return')
    .option('--follow', 'Follow log output')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => logsCommand(opts));

  // 10. versions
  program
    .command('versions')
    .description('List published version history for a capsule')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => versionsCommand(opts));

  // 11. rollback
  program
    .command('rollback')
    .description('Roll back to a previous version')
    .requiredOption('--version <n>', 'Target version number', (v) => parseInt(v, 10))
    .option('--mode <mode>', 'Rollback mode: code-only or code-and-data (default: code-only)', 'code-only')
    .option('--confirm-data-restore', 'Confirm destructive data restore')
    .option('--reason <msg>', 'Reason for rollback')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => rollbackCommand(opts));

  // 12. suspend
  program
    .command('suspend [app]')
    .description('Instantly suspend an application')
    .option('--reason <msg>', 'Required reason for suspension')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--json', 'Output machine-readable JSON')
    .action((app, opts) => suspendCommand(app, opts));

  // 13. resume
  program
    .command('resume [app]')
    .description('Resume a suspended application')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--json', 'Output machine-readable JSON')
    .action((app, opts) => resumeCommand(app, opts));

  // 14. audit command tree
  const auditCmd = program
    .command('audit')
    .description('Inspect, verify, export, and manage tamper-evident audit logs');

  auditCmd
    .command('list')
    .description('List audit events with filters')
    .option('--app <appId>', 'Filter by capsule application ID')
    .option('--action <action>', 'Filter by action name')
    .option('--outcome <outcome>', 'Filter by outcome (success, denied, failed)')
    .option('--agent-or-tool <val>', 'Filter by agent or tool')
    .option('--limit <n>', 'Maximum records to return', '50')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => auditListCommand(opts));

  auditCmd
    .command('verify')
    .description('Cryptographically verify hash chain continuity and tamper evidence')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => auditVerifyCommand(opts));

  auditCmd
    .command('export')
    .description('Export audit logs in CSV or JSON format')
    .option('--format <format>', 'Export format (csv or json)', 'json')
    .option('--output <path>', 'Output file path (default: stdout)')
    .option('--app <appId>', 'Filter by capsule application ID')
    .option('--action <action>', 'Filter by action name')
    .option('--outcome <outcome>', 'Filter by outcome')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => auditExportCommand(opts));

  auditCmd
    .command('retention')
    .description('Enforce organization audit retention policy')
    .option('--enforce', 'Execute retention policy and prune expired records')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => auditRetentionCommand(opts));

  // 15. inventory
  program
    .command('inventory')
    .description('List and inspect application inventory across your organization (FR-036)')
    .option('--org <orgId>', 'Filter by organization ID')
    .option('--status <status>', 'Filter by application status (active, suspended, archived)')
    .option('--format <format>', 'Output format (table, csv, json)', 'table')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => inventoryCommand(opts));

  // 16. transfer-ownership
  program
    .command('transfer-ownership <appKey>')
    .description('Transfer application ownership to another user (FR-033)')
    .requiredOption('--new-owner <userId>', 'Target new owner user ID')
    .option('--reason <msg>', 'Reason for ownership transfer')
    .option('--json', 'Output machine-readable JSON')
    .action((appKey, opts) => transferOwnershipCommand(appKey, opts));

  // 17. set-governance
  program
    .command('set-governance <appKey>')
    .description('Configure governance lifecycle parameters for a capsule (FR-034/35)')
    .option('--nominee <userId>', 'Nominated backup owner user ID')
    .option('--expires-in <days>', 'Set expiry relative to now in days')
    .option('--inactivity-limit <days>', 'Inactivity limit in days')
    .option('--purge-days <days>', 'Retention window in days between archival and purge')
    .option('--json', 'Output machine-readable JSON')
    .action((appKey, opts) => setGovernanceCommand(appKey, opts));

  return program;
}


export function runCli(argv: string[]) {
  const program = createProgram();
  program.parse(argv);
}

export { ApiClient, type RequestOptions } from './client.js';
export { loadConfig, saveConfig, clearConfig, type CliConfig } from './config.js';
export { CliError, outputError, outputResult } from './errors.js';
export { validateCommand } from './commands/validate.js';
export { publishCommand } from './commands/publish.js';
export { shareAddCommand, shareListCommand, shareRevokeCommand } from './commands/share.js';
export { unshareCommand } from './commands/unshare.js';
export { statusCommand } from './commands/status.js';
export { logsCommand } from './commands/logs.js';
export { versionsCommand } from './commands/versions.js';
export { rollbackCommand } from './commands/rollback.js';

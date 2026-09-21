import { Command } from 'commander';

export function createProgram(): Command {
  const program = new Command();

  program
    .name('capsule')
    .description('Software Capsule Platform CLI for publishing, sharing, and managing small apps')
    .version('0.1.0');

  program
    .command('init')
    .description('Initialize a new capsule in the current directory')
    .action(() => {
      console.log('Initializing capsule project...');
    });

  program
    .command('validate')
    .description('Validate capsule.manifest.yaml without deploying')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => {
      if (opts.json) {
        console.log(JSON.stringify({ valid: true, errors: [] }));
      } else {
        console.log('Manifest is valid.');
      }
    });

  program
    .command('publish')
    .description('Publish the current capsule project')
    .option('--dry-run', 'Run validation and admission checks without deploying')
    .option('--json', 'Output machine-readable JSON')
    .action(() => {
      console.log('Publishing capsule...');
    });

  // Sharing command tree per API/CLI spec
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
    .action((opts) => {
      const result = {
        action: 'share_added',
        app: opts.app || 'current-app',
        user: opts.user,
        group: opts.group,
        role: opts.role,
        expires_at: opts.expiresAt,
        status: 'active',
      };
      if (opts.json) {
        console.log(JSON.stringify(result));
      } else {
        const target = opts.user ? `user ${opts.user}` : `group ${opts.group}`;
        console.log(`Shared capsule with ${target} as role '${opts.role}'.`);
      }
    });

  shareCmd
    .command('list')
    .description('List current sharing assignments for a capsule')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--json', 'Output machine-readable JSON')
    .action((opts) => {
      const result = {
        app: opts.app || 'current-app',
        shares: [],
        default_scope: 'org',
      };
      if (opts.json) {
        console.log(JSON.stringify(result));
      } else {
        console.log('Current shares: (none or org-default)');
      }
    });

  shareCmd
    .command('revoke <shareId>')
    .description('Revoke an existing sharing assignment by share ID')
    .option('--app <appKey>', 'Target capsule ID or key')
    .option('--json', 'Output machine-readable JSON')
    .action((shareId, opts) => {
      const result = {
        action: 'share_revoked',
        share_id: shareId,
        status: 'revoked',
      };
      if (opts.json) {
        console.log(JSON.stringify(result));
      } else {
        console.log(`Revoked share ${shareId}.`);
      }
    });

  return program;
}

export function runCli(argv: string[]) {
  const program = createProgram();
  program.parse(argv);
}

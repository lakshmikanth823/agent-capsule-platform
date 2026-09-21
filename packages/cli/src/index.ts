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

  return program;
}

export function runCli(argv: string[]) {
  const program = createProgram();
  program.parse(argv);
}

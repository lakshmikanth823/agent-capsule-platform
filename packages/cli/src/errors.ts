/**
 * CLI Structured Error Handling and Output Formatting
 * Implements error codes and machine-readable output per docs/api-cli-spec/CLI_SPEC.md.
 */

export interface StructuredError {
  code: string;
  message: string;
  field?: string | null;
  hint?: string;
  details?: any;
}

export class CliError extends Error {
  public readonly code: string;
  public readonly exitCode: number;
  public readonly field?: string | null;
  public readonly hint?: string;
  public readonly details?: any;

  constructor(options: {
    message: string;
    code: string;
    exitCode?: number;
    field?: string | null;
    hint?: string;
    details?: any;
  }) {
    super(options.message);
    this.name = 'CliError';
    this.code = options.code;
    this.exitCode = options.exitCode ?? 1;
    this.field = options.field;
    this.hint = options.hint;
    this.details = options.details;
  }
}

/**
 * Output data as machine-readable JSON or human-friendly text.
 */
export function outputResult(
  data: any,
  options: { json?: boolean } = {},
  humanMessage?: string | (() => void)
): void {
  if (options.json) {
    console.log(JSON.stringify(data, null, 2));
  } else if (typeof humanMessage === 'function') {
    humanMessage();
  } else if (humanMessage) {
    console.log(humanMessage);
  } else if (typeof data === 'string') {
    console.log(data);
  } else {
    console.log(JSON.stringify(data, null, 2));
  }
}

/**
 * Output structured error and exit process with appropriate code.
 */
export function outputError(
  err: any,
  options: { json?: boolean } = {},
  defaultExitCode = 1
): never {
  const code = err?.code || 'UNKNOWN_ERROR';
  const message = err?.message || String(err);
  const field = err?.field || null;
  const hint = err?.hint || undefined;
  const exitCode = err?.exitCode ?? defaultExitCode;

  if (options.json) {
    const errorPayload: Record<string, any> = {
      code,
      message,
    };
    if (field) errorPayload.field = field;
    if (hint) errorPayload.hint = hint;
    if (err?.details) errorPayload.details = err.details;

    console.error(JSON.stringify({ error: errorPayload }, null, 2));
  } else {
    console.error(`\x1b[31mError [${code}]:\x1b[0m ${message}`);
    if (field) {
      console.error(`  \x1b[33mField:\x1b[0m ${field}`);
    }
    if (hint) {
      console.error(`  \x1b[36mNext steps:\x1b[0m ${hint}`);
    }
  }

  process.exit(exitCode);
}

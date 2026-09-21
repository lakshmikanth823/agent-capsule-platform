import { describe, it, expect } from 'vitest';
import { createProgram } from '../src/index.js';

describe('Capsule CLI Package', () => {
  it('should initialize commander program with correct name and version', () => {
    const program = createProgram();
    expect(program.name()).toBe('capsule');
    expect(program.version()).toBe('0.1.0');
  });

  it('should register required core commands', () => {
    const program = createProgram();
    const commandNames = program.commands.map((cmd) => cmd.name());
    expect(commandNames).toContain('init');
    expect(commandNames).toContain('validate');
    expect(commandNames).toContain('publish');
  });
});

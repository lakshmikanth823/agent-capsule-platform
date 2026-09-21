/**
 * capsule init
 * Scaffolds a new Capsule project with starter files and manifest.
 */
import fs from 'node:fs';
import path from 'node:path';
import { outputResult, outputError, CliError } from '../errors.js';

export interface InitOptions {
  name?: string;
  json?: boolean;
}

export async function initCommand(appName?: string, options: InitOptions = {}): Promise<void> {
  const targetDir = appName ? path.resolve(process.cwd(), appName) : process.cwd();
  const rawName = appName || path.basename(targetDir) || 'my-capsule-app';
  const name =
    rawName
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, '-')
      .replace(/^-+|-+$/g, '') || 'my-capsule-app';

  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true });
  }

  const manifestPath = path.join(targetDir, 'capsule.manifest.yaml');
  const packageJsonPath = path.join(targetDir, 'package.json');
  const tsconfigPath = path.join(targetDir, 'tsconfig.json');
  const srcDir = path.join(targetDir, 'src');
  const indexTsPath = path.join(srcDir, 'index.ts');

  // Check if manifest already exists
  if (fs.existsSync(manifestPath)) {
    outputError(
      new CliError({
        code: 'PROJECT_ALREADY_INITIALIZED',
        message: `Capsule project already exists at ${targetDir} (capsule.manifest.yaml found).`,
        exitCode: 1,
        hint: 'Use `capsule validate` or `capsule dev` to work with this project.',
      }),
      options
    );
  }

  // 1. capsule.manifest.yaml
  const manifestContent = `apiVersion: capsule/v1alpha1
id: ${name}
name: ${name.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
shape: web-app
runtime: node22
roles:
  - employee
  - manager
capabilities:
  db:
    type: sqlite
  identity: true
egress: []
sharing:
  default: org
limits:
  cpu: small
  memory_mb: 256
  request_timeout_s: 30
`;

  // 2. package.json
  const packageJsonContent = JSON.stringify(
    {
      name,
      version: '0.1.0',
      type: 'module',
      scripts: {
        build: 'tsc',
        start: 'node dist/index.js',
        dev: 'capsule dev',
      },
      dependencies: {
        '@capsule/sdk': '^0.1.0',
      },
      devDependencies: {
        typescript: '^5.4.0',
      },
    },
    null,
    2
  );

  // 3. tsconfig.json
  const tsconfigContent = JSON.stringify(
    {
      compilerOptions: {
        target: 'ES2022',
        module: 'NodeNext',
        moduleResolution: 'NodeNext',
        outDir: './dist',
        rootDir: './src',
        strict: true,
        esModuleInterop: true,
        skipLibCheck: true,
      },
      include: ['src/**/*'],
    },
    null,
    2
  );

  // 4. src/index.ts
  const indexTsContent = `import http from 'node:http';
import { getDatabase, getIdentity, type IdentityContext } from '@capsule/sdk';

const port = Number(process.env.PORT) || 3000;
const db = getDatabase();

// Initialize schema
db.exec(\`
  CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
  );
\`);

const server = http.createServer(async (req, res) => {
  const identity: IdentityContext | null = getIdentity(req);
  const url = new URL(req.url || '/', \`http://\${req.headers.host || 'localhost'}\`);

  if (url.pathname === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'healthy', app: '${name}' }));
    return;
  }

  if (url.pathname === '/api/identity') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ authenticated: identity !== null, identity }));
    return;
  }

  if (url.pathname === '/api/items') {
    if (req.method === 'GET') {
      const items = db.query('SELECT * FROM items ORDER BY id DESC');
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ items }));
      return;
    }
  }

  res.writeHead(200, { 'Content-Type': 'text/html' });
  res.end(\`<h1>\${name}</h1><p>Running on Capsule Platform</p><p>User: \${identity?.userId || 'Anonymous'}</p>\`);
});

server.listen(port, () => {
  console.log(\`[${name}] Server listening on port \${port}\`);
});
`;

  try {
    fs.writeFileSync(manifestPath, manifestContent, 'utf8');
    fs.writeFileSync(packageJsonPath, packageJsonContent, 'utf8');
    fs.writeFileSync(tsconfigPath, tsconfigContent, 'utf8');
    fs.mkdirSync(srcDir, { recursive: true });
    fs.writeFileSync(indexTsPath, indexTsContent, 'utf8');
  } catch (err: any) {
    outputError(
      new CliError({
        code: 'FILE_WRITE_ERROR',
        message: `Failed to scaffold project: ${err.message}`,
        exitCode: 1,
      }),
      options
    );
  }

  const createdFiles = [
    'capsule.manifest.yaml',
    'package.json',
    'tsconfig.json',
    'src/index.ts',
  ];

  outputResult(
    {
      initialized: true,
      name,
      targetDir,
      files: createdFiles,
    },
    options,
    () => {
      console.log(`\x1b[32m✔ Initialized new Capsule project in ${targetDir}\x1b[0m`);
      console.log('\nCreated files:');
      for (const f of createdFiles) {
        console.log(`  + ${f}`);
      }
      console.log('\nNext steps:');
      console.log('  1. Run `capsule validate` to check manifest syntax');
      console.log('  2. Run `capsule dev` to start the local emulator');
      console.log('  3. Run `capsule publish` to deploy to the platform');
    }
  );
}

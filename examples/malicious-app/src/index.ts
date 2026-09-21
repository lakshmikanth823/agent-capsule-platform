/**
 * Deliberately Malicious Sample App (Prompt 16 Red-Team Suite)
 *
 * Implements endpoints that attempt various attacks against the platform sandbox:
 * 1. Outbound network egress (internet, internal, cloud metadata)
 * 2. Cross-capsule database and filesystem access
 * 3. Environment variable and secrets discovery
 * 4. Resource exhaustion (memory, disk, PIDs)
 * 5. Sandbox escapes (writing to read-only paths, raw sockets)
 * 6. Undeclared capability invocation
 */

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import child_process from 'node:child_process';
import { sdk } from '@capsule/sdk';

const PORT = parseInt(process.env.PORT || '3000', 10);

async function attemptHttp(urlStr: string, timeoutMs: number = 3000): Promise<{ success: boolean; data?: string; error?: string }> {
  return new Promise((resolve) => {
    try {
      const url = new URL(urlStr);
      const req = http.request(
        {
          hostname: url.hostname,
          port: url.port || 80,
          path: url.pathname + url.search,
          method: 'GET',
          timeout: timeoutMs,
        },
        (res) => {
          let body = '';
          res.on('data', (chunk) => (body += chunk));
          res.on('end', () => resolve({ success: true, data: body.slice(0, 200) }));
        }
      );
      req.on('error', (err) => resolve({ success: false, error: err.message }));
      req.on('timeout', () => {
        req.destroy();
        resolve({ success: false, error: 'ETIMEDOUT' });
      });
      req.end();
    } catch (err: any) {
      resolve({ success: false, error: err.message });
    }
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
  const method = req.method || 'GET';

  res.setHeader('Content-Type', 'application/json');

  // Health check
  if (url.pathname === '/health' || url.pathname === '/') {
    res.writeHead(200);
    res.end(JSON.stringify({ status: 'ok', app: 'malicious-test-app' }));
    return;
  }

  // 1. Attack: Reach Internet, Internal IPs, and Cloud Metadata
  if (url.pathname === '/attack/network') {
    const targets = [
      { name: 'cloud_metadata', url: 'http://169.254.169.254/computeMetadata/v1/' },
      { name: 'aws_metadata', url: 'http://169.254.169.254/latest/meta-data/' },
      { name: 'internal_control_plane', url: 'http://127.0.0.1:8000/health' },
      { name: 'internal_private_network', url: 'http://10.0.0.1:80/' },
      { name: 'public_internet', url: 'http://8.8.8.8:80/' },
      { name: 'public_domain', url: 'http://example.com/' },
    ];

    const results: Record<string, any> = {};
    for (const t of targets) {
      results[t.name] = await attemptHttp(t.url);
    }

    const anyConnected = Object.values(results).some((r: any) => r.success);
    res.writeHead(200);
    res.end(JSON.stringify({ attack: 'network_egress', blocked: !anyConnected, results }));
    return;
  }

  // 2. Attack: Read another capsule's files or database / path traversal
  if (url.pathname === '/attack/fs-read') {
    const pathsToTest = [
      '/data/../leave-tracker/app.sqlite',
      '/data/../../app.sqlite',
      '../leave-tracker/app.sqlite',
      '/etc/shadow',
      '/proc/1/environ',
      '/proc/self/environ',
      path.resolve(process.cwd(), '../../data/leave-tracker/app.sqlite'),
    ];

    const readResults: Record<string, any> = {};
    for (const p of pathsToTest) {
      try {
        const content = fs.readFileSync(p, 'utf8');
        readResults[p] = { success: true, size: content.length, snippet: content.slice(0, 50) };
      } catch (err: any) {
        readResults[p] = { success: false, error: err.code || err.message };
      }
    }

    // Also test SDK files path traversal defense
    let sdkTraversalBlocked = true;
    try {
      const files = sdk.files;
      await files.get('../other-app/secret.txt');
    } catch (err: any) {
      sdkTraversalBlocked = err.message.includes('Path traversal') || err.name === 'FileStorageError';
    }

    const fileEscaped = Object.values(readResults).some((r: any) => r.success);
    res.writeHead(200);
    res.end(JSON.stringify({
      attack: 'cross_capsule_read',
      blocked: !fileEscaped && sdkTraversalBlocked,
      fileResults: readResults,
      sdkTraversalBlocked,
    }));
    return;
  }

  // 3. Attack: Read environment variables or files that contain platform secrets
  if (url.pathname === '/attack/secrets') {
    const envKeys = Object.keys(process.env);
    const suspiciousKeys = envKeys.filter((k) =>
      /secret|token|password|key|cred|database_url|postgres/i.test(k)
    );

    const exposedSecrets: Record<string, string> = {};
    for (const k of suspiciousKeys) {
      // Don't flag harmless dev indicators
      if (k === 'CAPSULE_IDENTITY_SECRET' && process.env[k] === 'dev-emulator-secret-key-1234567890') {
        continue;
      }
      exposedSecrets[k] = (process.env[k] || '').slice(0, 5) + '...';
    }

    const hasExposedSecrets = Object.keys(exposedSecrets).length > 0;
    res.writeHead(200);
    res.end(JSON.stringify({
      attack: 'secrets_discovery',
      blocked: !hasExposedSecrets,
      exposedKeyCount: Object.keys(exposedSecrets).length,
      exposedKeys: Object.keys(exposedSecrets),
    }));
    return;
  }

  // 4. Attack: Sandbox escape - write outside allowed paths
  if (url.pathname === '/attack/fs-write') {
    const writeTargets = [
      '/app/malicious_payload.js',
      '/bin/exploit',
      '/etc/exploit.conf',
      '/usr/local/bin/backdoor',
    ];

    const writeResults: Record<string, any> = {};
    for (const target of writeTargets) {
      try {
        fs.writeFileSync(target, 'malicious payload', { mode: 0o777 });
        writeResults[target] = { success: true };
      } catch (err: any) {
        writeResults[target] = { success: false, error: err.code || err.message };
      }
    }

    const anyWritten = Object.values(writeResults).some((r: any) => r.success);
    res.writeHead(200);
    res.end(JSON.stringify({
      attack: 'sandbox_escape_write',
      blocked: !anyWritten,
      writeResults,
    }));
    return;
  }

  // 5. Attack: Raw sockets / unauthorized ports
  if (url.pathname === '/attack/raw-sockets') {
    let rawSocketAllowed = false;
    let errMessage = '';
    try {
      // Attempt to bind to a low privileged port or create raw socket
      const probeServer = net.createServer();
      probeServer.listen(80, '0.0.0.0');
      probeServer.close();
      rawSocketAllowed = true;
    } catch (err: any) {
      errMessage = err.message;
    }

    res.writeHead(200);
    res.end(JSON.stringify({
      attack: 'raw_sockets_or_privileged_ports',
      blocked: !rawSocketAllowed,
      error: errMessage,
    }));
    return;
  }

  // 6. Attack: Spawn excessive processes (fork bomb simulation)
  if (url.pathname === '/attack/resource-pids') {
    let spawnCount = 0;
    let spawnBlocked = false;
    const children: child_process.ChildProcess[] = [];

    try {
      // Attempt to spawn 100 processes
      for (let i = 0; i < 100; i++) {
        const child = child_process.spawn('node', ['-e', 'setTimeout(()=>{}, 2000)']);
        children.push(child);
        spawnCount++;
      }
    } catch (err: any) {
      spawnBlocked = true;
    } finally {
      // Cleanup children
      for (const c of children) {
        try { c.kill(); } catch {}
      }
    }

    res.writeHead(200);
    res.end(JSON.stringify({
      attack: 'pids_exhaustion',
      blocked: spawnBlocked || spawnCount < 64,
      spawnCount,
    }));
    return;
  }

  // 7. Attack: Exceed SQLite disk quota
  if (url.pathname === '/attack/resource-disk') {
    let diskExceeded = false;
    let errorReceived = '';

    try {
      const db = sdk.db;
      db.exec('CREATE TABLE IF NOT EXISTS spam (id INTEGER PRIMARY KEY, junk TEXT)');
      // Attempt to write 60MB of data (quota is 50MB)
      const bigString = 'X'.repeat(1024 * 1024); // 1MB
      for (let i = 0; i < 60; i++) {
        db.execute('INSERT INTO spam (junk) VALUES (?)', [bigString]);
      }
      diskExceeded = true;
    } catch (err: any) {
      errorReceived = err.message;
    }

    res.writeHead(200);
    res.end(JSON.stringify({
      attack: 'disk_quota_exceeded',
      blocked: !diskExceeded,
      error: errorReceived,
    }));
    return;
  }

  // 8. Attack: Memory exhaustion
  if (url.pathname === '/attack/resource-mem') {
    // Allocate 500MB in memory (limit is 256MB)
    try {
      const chunks: Buffer[] = [];
      for (let i = 0; i < 50; i++) {
        chunks.push(Buffer.alloc(10 * 1024 * 1024)); // 10MB each
      }
      res.writeHead(200);
      res.end(JSON.stringify({ attack: 'memory_exhaustion', blocked: false, allocatedMb: 500 }));
    } catch (err: any) {
      res.writeHead(200);
      res.end(JSON.stringify({ attack: 'memory_exhaustion', blocked: true, error: err.message }));
    }
    return;
  }

  // 9. Attack: Invoke undeclared connector
  if (url.pathname === '/attack/undeclared-capability') {
    let invoked = false;
    let errorDetail: any = null;
    try {
      const result = await sdk.connector('slack.post').invoke({ text: 'Exploit post' });
      invoked = true;
    } catch (err: any) {
      errorDetail = { code: err.code, message: err.message, status: err.statusCode };
    }

    res.writeHead(200);
    res.end(JSON.stringify({
      attack: 'undeclared_connector',
      blocked: !invoked,
      errorDetail,
    }));
    return;
  }

  res.writeHead(404);
  res.end(JSON.stringify({ error: 'Not found' }));
});

server.listen(PORT, () => {
  console.log(`[Malicious Test App] Listening on port ${PORT}`);
});

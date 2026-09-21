import http from 'node:http';
import { parseIdentityHeader, getDatabase, type IdentityContext } from '@capsule/sdk';

const port = Number(process.env.PORT) || 3000;
const db = getDatabase();

// Initialize SQLite schema
db.exec(`
  CREATE TABLE IF NOT EXISTS leave_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  );
`);

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
    });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  const identity: IdentityContext | null = parseIdentityHeader(
    req.headers['x-capsule-identity'] as string | undefined
  );
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
  const pathname = url.pathname;

  // 1. Health check
  if (pathname === '/health' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'healthy', app: 'leave-tracker', version: '0.1.0' }));
    return;
  }

  // 2. Identity inspection route
  if (pathname === '/api/identity' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify({
        authenticated: identity !== null,
        identity: identity || null,
      })
    );
    return;
  }

  // 3. Leaves CRUD
  if (pathname === '/api/leaves') {
    if (req.method === 'GET') {
      const stmt = db.prepare('SELECT * FROM leave_requests ORDER BY id DESC');
      const rows = stmt.all();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ leaves: rows }));
      return;
    }

    if (req.method === 'POST') {
      try {
        const rawBody = await readBody(req);
        const data = rawBody ? JSON.parse(rawBody) : {};
        const userId = identity?.sub || data.user_id || 'anonymous';
        const startDate = data.start_date || new Date().toISOString().split('T')[0];
        const endDate = data.end_date || startDate;
        const reason = data.reason || 'Personal leave';

        const insertStmt = db.prepare(`
          INSERT INTO leave_requests (user_id, start_date, end_date, reason)
          VALUES (?, ?, ?, ?)
        `);
        const result = insertStmt.run(userId, startDate, endDate, reason);

        res.writeHead(201, { 'Content-Type': 'application/json' });
        res.end(
          JSON.stringify({
            id: Number(result.lastInsertRowid),
            user_id: userId,
            start_date: startDate,
            end_date: endDate,
            reason,
            status: 'pending',
          })
        );
        return;
      } catch (err: any) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Invalid request body', details: err.message }));
        return;
      }
    }
  }

  // 4. HTML root view
  if (pathname === '/' && req.method === 'GET') {
    const stmt = db.prepare('SELECT * FROM leave_requests ORDER BY id DESC LIMIT 10');
    const rows = (stmt.all() as any[]) || [];

    const rowsHtml = rows
      .map(
        (r) =>
          `<tr><td>${r.id}</td><td>${r.user_id}</td><td>${r.start_date} to ${r.end_date}</td><td>${r.reason}</td><td>${r.status}</td></tr>`
      )
      .join('');

    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(`<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Leave Tracker - Software Capsule</title>
    <style>
      body { font-family: system-ui, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.5; }
      table { width: 100%; border-collapse: collapse; margin-top: 20px; }
      th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
      th { background-color: #f4f4f4; }
      .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; background: #e0e7ff; color: #3730a3; font-size: 12px; }
      .card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 20px; background: #f9fafb; }
    </style>
  </head>
  <body>
    <h1>Leave Tracker Capsule</h1>
    <div class="card">
      <h3>Current Identity</h3>
      <p><strong>User:</strong> ${identity?.sub || 'Anonymous'}</p>
      <p><strong>Org:</strong> ${identity?.org_id || 'None'}</p>
      <p><strong>Roles:</strong> ${identity?.roles?.join(', ') || 'None'}</p>
      <p><strong>Groups:</strong> ${identity?.groups?.join(', ') || 'None'}</p>
    </div>

    <h3>Recent Leave Requests</h3>
    <table>
      <thead>
        <tr><th>ID</th><th>User</th><th>Dates</th><th>Reason</th><th>Status</th></tr>
      </thead>
      <tbody>
        ${rowsHtml || '<tr><td colspan="5">No leave requests found.</td></tr>'}
      </tbody>
    </table>
  </body>
</html>`);
    return;
  }

  // 404 Fallback
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not Found', path: pathname }));
});

server.listen(port, () => {
  console.log(`[leave-tracker] Running on port ${port}`);
});

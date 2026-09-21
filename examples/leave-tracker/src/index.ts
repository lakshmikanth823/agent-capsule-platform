import http from 'node:http';
import { parseIdentityHeader } from '@capsule/sdk';

const port = Number(process.env.PORT) || 3000;

const server = http.createServer((req, res) => {
  const identity = parseIdentityHeader(req.headers['x-capsule-identity'] as string);

  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'healthy', app: 'leave-tracker' }));
    return;
  }

  res.writeHead(200, { 'Content-Type': 'text/html' });
  res.end(`
    <!DOCTYPE html>
    <html>
      <head><title>Leave Tracker</title></head>
      <body>
        <h1>Leave Tracker Capsule</h1>
        <p>User: ${identity?.sub || 'Anonymous'}</p>
        <p>Roles: ${identity?.roles?.join(', ') || 'None'}</p>
      </body>
    </html>
  `);
});

server.listen(port, () => {
  console.log(`Leave tracker running on port ${port}`);
});

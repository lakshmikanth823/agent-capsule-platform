#!/usr/bin/env node
/**
 * Capsule MCP Server CLI Entrypoint
 *
 * Usage:
 *   capsule-mcp              (runs stdio transport, default for desktop AI tools)
 *   capsule-mcp --http --port 3333  (runs HTTP SSE transport)
 */
import http from "node:http";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { createCapsuleMcpServer } from "./server.js";

async function main() {
  const args = process.argv.slice(2);
  const isHttp = args.includes("--http") || args.includes("--sse");
  const portIndex = args.indexOf("--port");
  const port =
    portIndex !== -1 && args[portIndex + 1]
      ? parseInt(args[portIndex + 1], 10)
      : 3333;

  if (args.includes("--help") || args.includes("-h")) {
    console.log(`
Capsule MCP Server (Model Context Protocol adapter)

Usage:
  capsule-mcp                       Run in stdio mode (default for Claude Desktop, Cursor, Antigravity)
  capsule-mcp --http [--port 3333]  Run HTTP SSE server for remote AI integrations

Environment Variables:
  CONTROL_PLANE_URL  Control-plane API base URL (default: http://localhost:8000)
  CAPSULE_TOKEN      Authentication session or publish token
  CAPSULE_CONFIG_DIR Path to directory containing config.json (default: ~/.capsule)
`);
    process.exit(0);
  }

  if (isHttp) {
    let transport: SSEServerTransport | null = null;
    const httpServer = http.createServer(async (req, res) => {
      // CORS headers
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
      res.setHeader(
        "Access-Control-Allow-Headers",
        "Content-Type, Authorization",
      );

      if (req.method === "OPTIONS") {
        res.writeHead(204);
        res.end();
        return;
      }

      if (req.url === "/sse" && req.method === "GET") {
        transport = new SSEServerTransport("/messages", res);
        const server = createCapsuleMcpServer();
        await server.connect(transport);
        return;
      }

      if (req.url?.startsWith("/messages") && req.method === "POST") {
        if (!transport) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(
            JSON.stringify({
              error:
                "SSE connection must be established before sending messages.",
            }),
          );
          return;
        }
        await transport.handlePostMessage(req, res);
        return;
      }

      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Not found. Connect via GET /sse" }));
    });

    httpServer.listen(port, () => {
      console.log(
        `Capsule MCP Server listening on SSE at http://localhost:${port}/sse`,
      );
    });
  } else {
    // Default stdio transport
    const server = createCapsuleMcpServer();
    const transport = new StdioServerTransport();
    await server.connect(transport);
  }
}

main().catch((err) => {
  console.error("Fatal error in Capsule MCP server:", err);
  process.exit(1);
});

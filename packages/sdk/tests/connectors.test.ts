import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { sdk, getConnector, ConnectorError } from "../src/index.js";
import http from "node:http";

describe("Capsule SDK Connectors Suite (Prompt 15)", () => {
  const originalEnv = process.env;

  beforeEach(() => {
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  describe("1. Emulator Mode", () => {
    beforeEach(() => {
      process.env.CAPSULE_EMULATOR = "true";
      delete process.env.CAPSULE_BROKER_URL;
    });

    it("should emulate fake.echo connector locally without external credentials", async () => {
      const result = await sdk.connector("fake.echo").invoke({
        testMessage: "Hello from emulator",
        count: 42,
      });

      expect(result.connector).toBe("fake.echo");
      expect(result.status).toBe("success");
      expect(result.echo.testMessage).toBe("Hello from emulator");
      expect(result.echo.count).toBe(42);
      expect(result.credential_attached).toBe(true);
      expect(result.emulator).toBe(true);
      expect(result.identity?.userId).toBe("dev-user-001");
    });

    it("should emulate slack.post connector locally without real API credentials", async () => {
      const result = await sdk.connector("slack.post").invoke({
        channel: "#hr-leave",
        text: "Alice submitted leave request",
      });

      expect(result.connector).toBe("slack.post");
      expect(result.status).toBe("success");
      expect(result.ok).toBe(true);
      expect(result.channel).toBe("#hr-leave");
      expect(result.emulator).toBe(true);
      expect(result.echo_text).toBe("Alice submitted leave request");
    });

    it("should emulate sheets.read connector locally with mock sheet rows", async () => {
      const result = await sdk.connector("sheets.read").invoke({
        spreadsheet_id: "sheet-leave-balances",
        range: "A1:C10",
      });

      expect(result.connector).toBe("sheets.read");
      expect(result.status).toBe("success");
      expect(result.spreadsheet_id).toBe("sheet-leave-balances");
      expect(result.range).toBe("A1:C10");
      expect(result.major_dimension).toBe("ROWS");
      expect(result.values).toBeInstanceOf(Array);
      expect(result.values.length).toBeGreaterThan(0);
      expect(result.emulator).toBe(true);
    });

    it("should verify apps have NO raw secrets in process.env", () => {
      // Invariant: no raw connector credentials in application env
      expect(process.env.SLACK_BOT_TOKEN).toBeUndefined();
      expect(process.env.SLACK_WEBHOOK_URL).toBeUndefined();
      expect(process.env.CONNECTOR_CREDENTIAL).toBeUndefined();
      expect(process.env.CONNECTOR_SECRET).toBeUndefined();
    });
  });

  describe("2. Platform Mode HTTP Dispatch", () => {
    let mockBrokerServer: http.Server;
    let brokerPort: number;
    let lastReceivedRequest: any = null;

    beforeEach(async () => {
      process.env.CAPSULE_EMULATOR = "false";

      mockBrokerServer = http.createServer((req, res) => {
        let body = "";
        req.on("data", (chunk) => (body += chunk));
        req.on("end", () => {
          lastReceivedRequest = {
            url: req.url,
            method: req.method,
            headers: req.headers,
            body: body ? JSON.parse(body) : null,
          };

          if (req.url === "/v1/connectors/fake.echo/invoke") {
            if (!req.headers["x-capsule-identity"]) {
              res.writeHead(401, { "Content-Type": "application/json" });
              res.end(
                JSON.stringify({
                  code: "VIEWER_IDENTITY_REQUIRED",
                  message: "Viewer identity required",
                }),
              );
              return;
            }

            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                connector: "fake.echo",
                status: "success",
                echo: lastReceivedRequest.body,
                credential_attached: true,
              }),
            );
          } else if (req.url === "/v1/connectors/sheets.read/invoke") {
            if (!req.headers["x-capsule-identity"]) {
              res.writeHead(401, { "Content-Type": "application/json" });
              res.end(
                JSON.stringify({
                  code: "VIEWER_IDENTITY_REQUIRED",
                  message: "Viewer identity required for sheets.read",
                }),
              );
              return;
            }

            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                connector: "sheets.read",
                status: "success",
                spreadsheet_id: lastReceivedRequest.body?.spreadsheet_id,
                range: lastReceivedRequest.body?.range || "A1:Z100",
                major_dimension: "ROWS",
                values: [
                  ["Name", "Hours"],
                  ["Alice", 40],
                ],
              }),
            );
          } else if (req.url === "/v1/connectors/forbidden.service/invoke") {
            res.writeHead(403, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                code: "SERVICE_IDENTITY_FORBIDDEN",
                message: "Organization policy prohibits service identity",
              }),
            );
          } else {
            res.writeHead(404, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                code: "NOT_FOUND",
                message: "Unknown connector",
              }),
            );
          }
        });
      });

      await new Promise<void>((resolve) => {
        mockBrokerServer.listen(0, "127.0.0.1", () => {
          const addr = mockBrokerServer.address() as any;
          brokerPort = addr.port;
          resolve();
        });
      });

      process.env.CAPSULE_BROKER_URL = `http://127.0.0.1:${brokerPort}`;
      process.env.CAPSULE_KEY = "leave-tracker";
    });

    afterEach(async () => {
      await new Promise((resolve) => mockBrokerServer.close(resolve));
    });

    it("should forward app key and identity header to credential broker", async () => {
      const result = await sdk
        .connector("fake.echo")
        .invoke(
          { message: "platform test" },
          { identityHeader: "mock-viewer-token" },
        );

      expect(result.connector).toBe("fake.echo");
      expect(result.credential_attached).toBe(true);
      expect(lastReceivedRequest.headers["x-capsule-key"]).toBe(
        "leave-tracker",
      );
      expect(lastReceivedRequest.headers["x-capsule-identity"]).toBe(
        "mock-viewer-token",
      );
      expect(lastReceivedRequest.body.message).toBe("platform test");
    });

    it("should invoke sheets.read with viewer identity in platform mode", async () => {
      const result = await sdk
        .connector("sheets.read")
        .invoke(
          { spreadsheet_id: "sheet-q3-okr", range: "Sheet1!A1:B5" },
          { identityHeader: "mock-viewer-token" },
        );

      expect(result.connector).toBe("sheets.read");
      expect(result.status).toBe("success");
      expect(result.spreadsheet_id).toBe("sheet-q3-okr");
      expect(result.values).toEqual([
        ["Name", "Hours"],
        ["Alice", 40],
      ]);
      expect(lastReceivedRequest.headers["x-capsule-identity"]).toBe(
        "mock-viewer-token",
      );
    });

    it("should throw typed ConnectorError on broker rejection (e.g. VIEWER_IDENTITY_REQUIRED)", async () => {
      await expect(
        sdk.connector("fake.echo").invoke({ message: "without identity" }),
      ).rejects.toThrow(ConnectorError);

      try {
        await sdk
          .connector("fake.echo")
          .invoke({ message: "without identity" });
      } catch (err: any) {
        expect(err).toBeInstanceOf(ConnectorError);
        expect(err.code).toBe("VIEWER_IDENTITY_REQUIRED");
        expect(err.statusCode).toBe(401);
      }
    });

    it("should throw typed ConnectorError on policy rejection (e.g. SERVICE_IDENTITY_FORBIDDEN)", async () => {
      try {
        await sdk.connector("forbidden.service").invoke({});
      } catch (err: any) {
        expect(err).toBeInstanceOf(ConnectorError);
        expect(err.code).toBe("SERVICE_IDENTITY_FORBIDDEN");
        expect(err.statusCode).toBe(403);
      }
    });
  });
});

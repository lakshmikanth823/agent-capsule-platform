/**
 * @capsule/mcp-server
 * Model Context Protocol (MCP) server adapter for the Software Capsule Platform.
 */

export { createCapsuleMcpServer, type McpServerOptions } from "./server.js";
export {
  assertConfirmation,
  formatUntrustedData,
  formatUntrustedText,
  buildMcpErrorResponse,
  buildMcpSuccessResponse,
  extractStructuredError,
  McpConfirmationError,
  type StructuredErrorEnvelope,
} from "./security.js";

/**
 * capsule unshare
 * Convenience alias for `capsule share revoke`.
 */
import { shareRevokeCommand, type ShareRevokeOptions } from "./share.js";

export async function unshareCommand(
  shareId: string,
  options: ShareRevokeOptions = {},
): Promise<void> {
  return shareRevokeCommand(shareId, options);
}

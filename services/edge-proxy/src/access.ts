/**
 * Access Control and Role Mapping
 *
 * Implements TRD Sections 15 & 17:
 * - Checks user authorization against the app and organization.
 * - Maps user to platform role (Owner, Editor, User) and application role (declared by app).
 * - Manages active/revoked user and group shares with immediate enforcement.
 */

export interface AppMetadata {
  id: string;
  appKey: string;
  name: string;
  organizationId: string;
  status: string;
  orgStatus?: string;
  currentVersionId?: string;
  manifest: Record<string, any>;
  bundlePath?: string;
  dataDir?: string;
  defaultScope?: "org" | "restricted";
}

export interface UserContext {
  id: string;
  email: string;
  orgId: string;
  platformRole: string;
  groups?: string[];
}

export interface ShareRecord {
  id: string;
  appKey: string;
  userId?: string;
  userEmail?: string;
  groupName?: string;
  appRole: string;
  status: "active" | "revoked" | "expired";
  grantedAt: Date;
  expiresAt?: Date;
}

export interface AccessEvaluation {
  allowed: boolean;
  reason?: string;
  platformRole?: string;
  appRoles?: string[];
}

export class AccessManager {
  private appRegistry = new Map<string, AppMetadata>();
  private shares = new Map<string, ShareRecord>(); // shareId -> ShareRecord

  registerApp(app: AppMetadata): void {
    this.appRegistry.set(app.appKey, {
      defaultScope: "org",
      ...app,
    });
  }

  getApp(appKey: string): AppMetadata | undefined {
    return this.appRegistry.get(appKey);
  }

  setAppDefaultScope(appKey: string, scope: "org" | "restricted"): void {
    const app = this.appRegistry.get(appKey);
    if (app) {
      app.defaultScope = scope;
    }
  }

  addShare(params: {
    appKey: string;
    userId?: string;
    userEmail?: string;
    groupName?: string;
    appRole: string;
    expiresAt?: Date;
  }): ShareRecord {
    const id = `share-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
    const share: ShareRecord = {
      id,
      appKey: params.appKey,
      userId: params.userId,
      userEmail: params.userEmail,
      groupName: params.groupName,
      appRole: params.appRole,
      status: "active",
      grantedAt: new Date(),
      expiresAt: params.expiresAt,
    };
    this.shares.set(id, share);
    return share;
  }

  revokeShare(shareId: string): boolean {
    const share = this.shares.get(shareId);
    if (share) {
      share.status = "revoked";
      return true;
    }
    return false;
  }

  revokeUserShares(appKey: string, userEmailOrId: string): void {
    for (const share of this.shares.values()) {
      if (
        share.appKey === appKey &&
        (share.userEmail === userEmailOrId || share.userId === userEmailOrId)
      ) {
        share.status = "revoked";
      }
    }
  }

  listShares(appKey: string): ShareRecord[] {
    const results: ShareRecord[] = [];
    for (const share of this.shares.values()) {
      if (share.appKey === appKey) {
        results.push(share);
      }
    }
    return results;
  }

  evaluateAccess(user: UserContext, app: AppMetadata): AccessEvaluation {
    // 0. Organization must be active
    if (app.orgStatus === "suspended") {
      return {
        allowed: false,
        reason: "Organization is suspended.",
      };
    }

    // 1. App must be active
    if (app.status !== "active") {
      return {
        allowed: false,
        reason: `Capsule ${app.appKey} is ${app.status}.`,
      };
    }

    // 2. Organization check
    if (user.orgId !== app.organizationId) {
      return {
        allowed: false,
        reason:
          "User does not belong to the organization that owns this capsule.",
      };
    }

    const platformRole = user.platformRole === "owner" ? "owner" : "user";
    const declaredRoles: string[] = Array.isArray(app.manifest?.roles)
      ? app.manifest.roles
      : [];

    // 3. App Owner always has full access
    if (platformRole === "owner") {
      return {
        allowed: true,
        platformRole: "owner",
        appRoles: declaredRoles.length > 0 ? declaredRoles : ["admin"],
      };
    }

    const now = new Date();
    const appShares = this.listShares(app.appKey);

    // 4. Check individual user shares
    const userShares = appShares.filter(
      (s) =>
        (s.userId && s.userId === user.id) ||
        (s.userEmail && s.userEmail.toLowerCase() === user.email.toLowerCase()),
    );

    // If user has explicitly revoked shares and NO active shares, block them immediately
    const activeUserShares = userShares.filter(
      (s) => s.status === "active" && (!s.expiresAt || s.expiresAt > now),
    );
    const hasRevokedUserShare = userShares.some((s) => s.status === "revoked");

    if (activeUserShares.length > 0) {
      const mappedRoles = activeUserShares.map((s) => s.appRole);
      return {
        allowed: true,
        platformRole,
        appRoles: mappedRoles,
      };
    }

    if (hasRevokedUserShare) {
      return {
        allowed: false,
        reason: "Access to this capsule has been revoked.",
      };
    }

    // 5. Check group shares
    if (user.groups && user.groups.length > 0) {
      const activeGroupShares = appShares.filter(
        (s) =>
          s.groupName &&
          user.groups!.includes(s.groupName) &&
          s.status === "active" &&
          (!s.expiresAt || s.expiresAt > now),
      );

      if (activeGroupShares.length > 0) {
        const groupRoles = activeGroupShares.map((s) => s.appRole);
        return {
          allowed: true,
          platformRole,
          appRoles: groupRoles,
        };
      }
    }

    // 6. Check default org policy
    const defaultScope = app.defaultScope || "org";
    if (defaultScope === "org" && user.orgId === app.organizationId) {
      const defaultRole =
        declaredRoles.length > 0 ? declaredRoles[0] : "employee";
      return {
        allowed: true,
        platformRole,
        appRoles: [defaultRole],
      };
    }

    return {
      allowed: false,
      reason: "No active share or permission found for this user.",
    };
  }
}

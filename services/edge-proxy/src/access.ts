/**
 * Access Control and Role Mapping
 *
 * Implements TRD Sections 15 & 17:
 * - Checks user authorization against the app and organization.
 * - Maps user to platform role (Owner, Editor, User) and application role (declared by app).
 */

export interface AppMetadata {
  id: string;
  appKey: string;
  name: string;
  organizationId: string;
  status: string;
  currentVersionId?: string;
  manifest: Record<string, any>;
  bundlePath?: string;
  dataDir?: string;
}

export interface UserContext {
  id: string;
  email: string;
  orgId: string;
  platformRole: string;
  groups?: string[];
}

export interface AccessEvaluation {
  allowed: boolean;
  reason?: string;
  platformRole?: string;
  appRoles?: string[];
}

export class AccessManager {
  private appRegistry = new Map<string, AppMetadata>();

  registerApp(app: AppMetadata): void {
    this.appRegistry.set(app.appKey, app);
  }

  getApp(appKey: string): AppMetadata | undefined {
    return this.appRegistry.get(appKey);
  }

  evaluateAccess(user: UserContext, app: AppMetadata): AccessEvaluation {
    // 1. App must be active
    if (app.status !== 'active') {
      return {
        allowed: false,
        reason: `Capsule ${app.appKey} is ${app.status}.`,
      };
    }

    // 2. Organization check (Alpha: org-scoped by default)
    if (user.orgId !== app.organizationId) {
      return {
        allowed: false,
        reason: 'User does not belong to the organization that owns this capsule.',
      };
    }

    // 3. Platform role mapping
    const platformRole = user.platformRole === 'owner' ? 'owner' : 'user';

    // 4. Application role mapping
    // Declared roles in manifest
    const declaredRoles: string[] = Array.isArray(app.manifest?.roles)
      ? app.manifest.roles
      : [];

    let appRoles: string[] = [];

    // Owner gets all declared roles or manager/hr if present
    if (platformRole === 'owner') {
      appRoles = declaredRoles.length > 0 ? declaredRoles : ['admin'];
    } else {
      // Default org member gets the base role (e.g. employee)
      if (declaredRoles.includes('employee')) {
        appRoles = ['employee'];
      } else if (declaredRoles.length > 0) {
        appRoles = [declaredRoles[0]];
      } else {
        appRoles = ['viewer'];
      }
    }

    return {
      allowed: true,
      platformRole,
      appRoles,
    };
  }
}

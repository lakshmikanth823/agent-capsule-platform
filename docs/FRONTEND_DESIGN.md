# Frontend Design — Software Capsule

Version: 0.1  
Scope: simple wireframes for the Dashboard, Share screen, and Permission Preview.

## 1. Dashboard
- Capsule list with status, version, owner, weekly active viewers, and last published time.
- Primary action: **Publish app**.
- Navigation: Capsules, Activity, Environment, Audit, Settings.
- App actions: Open and More.
- Statuses shown: Active and Suspended.

## 2. Share Screen
- App URL with copy-link action.
- People/groups input.
- One application-role selector.
- Platform role is displayed as context.
- Existing assignments show user/group, application role, and revoke action.
- External/guest access is explicitly shown as disabled by default.
- Only Owner/Editor can change assignments.

## 3. Permission Preview
Plain-language preview of:
- Identity
- SQLite database
- Files
- Network egress
- Connectors
- AI capability/budget

The preview highlights service-identity access and capability escalation. A new or broadened capability, new service identity, or newly restricted connector requires human approval before deployment.

## Design constraints
- Consistent with PRD v0.2, TRD v0.1, Manifest Spec v1alpha1, backend schema v0.1, and API/CLI Spec v0.1.
- Wireframes are intentionally low-fidelity; they do not define final visual styling.
- Environment Profiles, enterprise SSO/SCIM, scheduling, previews, and other later-phase features are not presented as MVP functionality.

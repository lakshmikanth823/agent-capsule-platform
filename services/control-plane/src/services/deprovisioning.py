"""
Deprovisioning Cascade & Prompt 20 Owner-Left Lifecycle Hook.
Ensures immediate revocation of sessions, tokens, and connector credentials,
and enforces FR-034 owner deprovisioning policies so apps never run silently unmanaged.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy import select, update, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, Organization, OrganizationMember, App, AuditEvent, SCIMGroupMember
from db.dal import UserDAL, OrganizationDAL, ConnectorCredentialDAL, AppShareDAL, AuditDAL
from services.governance import GovernanceService


async def handle_owner_left(
    db: AsyncSession,
    org_id: uuid.UUID,
    user: User,
    reason: str = "SCIM directory sync",
) -> List[Dict[str, Any]]:
    """
    Prompt 20 Owner-Left Hook (FR-034).
    Delegates to GovernanceService for nominee transfer or grace-period lifecycle management.
    """
    gov_service = GovernanceService(db)
    return await gov_service.handle_owner_left(
        deprovisioned_user_id=user.id,
        org_id=org_id,
        reason=reason,
    )


async def deprovision_user(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str = "SCIM directory sync",
) -> Dict[str, Any]:
    """
    Executes atomic deprovisioning cascade:
    1. Mark user as 'deprovisioned'
    2. Revoke user sessions (sessions_revoked_at = now)
    3. Revoke publish tokens (tokens_revoked_at = now)
    4. Wipe all connector credentials (OAuth tokens, API keys)
    5. Revoke direct AppShares
    6. Remove from SCIM groups
    7. Update organization membership status
    8. Trigger Prompt 20 Owner-Left Hook (suspend or transfer orphaned apps)
    """
    user_dal = UserDAL(db)
    cred_dal = ConnectorCredentialDAL(db)
    share_dal = AppShareDAL(db)

    user = await user_dal.get_by_id(user_id)
    if not user:
        raise ValueError(f"User {user_id} not found.")

    # 1. Update user status to deprovisioned
    await user_dal.set_status(user_id, "deprovisioned")

    # 2. Revoke sessions immediately
    sessions_revoked_at = await user_dal.revoke_sessions(user_id)

    # 3. Revoke publish tokens immediately
    tokens_revoked_at = await user_dal.revoke_tokens(user_id)

    # 4. Wipe all connector credentials (e.g. Google Sheets tokens)
    deleted_creds_count = await cred_dal.delete_all_credentials_for_user(org_id, user_id)

    # 5. Revoke direct application shares
    revoked_shares_count = await share_dal.revoke_all_shares_for_user(user_id)

    # 6. Remove user from all SCIM groups
    await db.execute(delete(SCIMGroupMember).where(SCIMGroupMember.user_id == user_id))

    # 7. Mark org membership deprovisioned
    await user_dal.update_org_member_status(org_id, user_id, "deprovisioned")

    # 8. Prompt 20 Owner-Left Hook
    affected_apps = await handle_owner_left(db, org_id, user, reason=reason)

    # Log audit event for user deprovisioning
    await AuditDAL(db).record_event(
        organization_id=org_id,
        app_id=None,
        actor_user_id=None,
        actor_agent="scim-deprovisioning",
        action="user.deprovisioned",
        outcome="success",
        target_type="user",
        target_id=user.id,
        metadata={
            "user_id": str(user.id),
            "email": user.email,
            "reason": reason,
            "connector_credentials_wiped": deleted_creds_count,
            "shares_revoked": revoked_shares_count,
            "affected_apps_count": len(affected_apps),
        },
    )

    return {
        "user_id": str(user.id),
        "status": "deprovisioned",
        "sessions_revoked_at": sessions_revoked_at.isoformat(),
        "tokens_revoked_at": tokens_revoked_at.isoformat(),
        "connector_credentials_wiped": deleted_creds_count,
        "shares_revoked": revoked_shares_count,
        "affected_apps": affected_apps,
    }

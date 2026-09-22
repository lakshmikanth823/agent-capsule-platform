"""
Group Synchronization Service: Real-time propagation of SCIM group memberships to App Shares.
"""
import uuid
from typing import List
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SCIMGroupRoleMapping, SCIMGroupMember
from db.dal import AppShareDAL, GroupRoleMappingDAL


async def propagate_group_membership_changes(
    db: AsyncSession,
    org_id: uuid.UUID,
    group_id: uuid.UUID,
    added_user_ids: List[uuid.UUID],
    removed_user_ids: List[uuid.UUID],
) -> None:
    """
    Propagates group membership additions and removals to AppShares in real time.
    """
    mapping_dal = GroupRoleMappingDAL(db)
    share_dal = AppShareDAL(db)

    mappings = await mapping_dal.list_for_group(group_id)
    if not mappings:
        return

    # 1. Process additions
    for user_id in added_user_ids:
        for mapping in mappings:
            await share_dal.upsert_group_share(
                app_id=mapping.app_id,
                user_id=user_id,
                app_role=mapping.app_role,
                group_id=group_id,
            )

    # 2. Process removals
    for user_id in removed_user_ids:
        for mapping in mappings:
            # Check if user is in another group that grants the same (app_id, app_role)
            other_groups_query = await db.execute(
                select(SCIMGroupRoleMapping)
                .join(SCIMGroupMember, SCIMGroupMember.group_id == SCIMGroupRoleMapping.group_id)
                .where(
                    and_(
                        SCIMGroupMember.user_id == user_id,
                        SCIMGroupRoleMapping.app_id == mapping.app_id,
                        SCIMGroupRoleMapping.app_role == mapping.app_role,
                        SCIMGroupRoleMapping.group_id != group_id,
                    )
                )
            )
            has_other_grant = other_groups_query.scalars().first() is not None
            if not has_other_grant:
                await share_dal.revoke_group_share(
                    app_id=mapping.app_id,
                    user_id=user_id,
                    group_id=group_id,
                )

    await db.flush()


async def propagate_new_role_mapping(
    db: AsyncSession,
    org_id: uuid.UUID,
    group_id: uuid.UUID,
    app_id: uuid.UUID,
    app_role: str,
) -> int:
    """
    When a new GroupRoleMapping is configured, immediately grant the role to all current members of the group.
    """
    share_dal = AppShareDAL(db)
    members_query = await db.execute(
        select(SCIMGroupMember.user_id).where(SCIMGroupMember.group_id == group_id)
    )
    user_ids = members_query.scalars().all()
    for user_id in user_ids:
        await share_dal.upsert_group_share(
            app_id=app_id,
            user_id=user_id,
            app_role=app_role,
            group_id=group_id,
        )
    await db.flush()
    return len(user_ids)

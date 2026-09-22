"""
Audit Retention Service
Enforces per-organization retention policies with checkpoint anchoring,
preserving hash-chain validity after pruning.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from sqlalchemy import select, func, text, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Organization, AuditEvent, OrganizationAuditCheckpoint


class AuditRetentionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enforce_organization_retention(
        self, organization_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Prunes audit events older than organization's audit_retention_days.
        Creates a checkpoint anchor with the last deleted event's sequence and hash
        so future chain verifications remain cryptographically continuous.
        """
        # 1. Fetch organization retention setting
        org_result = await self.session.execute(
            select(Organization.audit_retention_days).where(
                Organization.id == organization_id
            )
        )
        retention_days = org_result.scalar_one_or_none()
        if retention_days is None:
            retention_days = 90

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        # 2. Check for events older than cutoff
        events_query = (
            select(AuditEvent)
            .where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.occurred_at < cutoff,
            )
            .order_by(AuditEvent.sequence_number.asc())
        )
        result = await self.session.execute(events_query)
        expired_events = list(result.scalars().all())

        if not expired_events:
            return {
                "organization_id": str(organization_id),
                "retention_days": retention_days,
                "cutoff": cutoff.isoformat(),
                "purged_count": 0,
                "checkpoint": None,
            }

        last_expired = expired_events[-1]
        purged_count = len(expired_events)

        # 3. Create checkpoint anchor
        checkpoint = OrganizationAuditCheckpoint(
            organization_id=organization_id,
            checkpoint_sequence=last_expired.sequence_number,
            checkpoint_hash=last_expired.event_hash,
            purged_count=purged_count,
            purged_before=cutoff,
        )
        self.session.add(checkpoint)
        await self.session.flush()

        # 4. Authorize purge via transaction-local setting for trigger
        await self.session.execute(text("SET LOCAL capsule.allow_retention_purge = 'on'"))

        # 5. Delete pruned events
        await self.session.execute(
            delete(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.occurred_at < cutoff,
            )
        )
        await self.session.flush()

        return {
            "organization_id": str(organization_id),
            "retention_days": retention_days,
            "cutoff": cutoff.isoformat(),
            "purged_count": purged_count,
            "checkpoint": {
                "sequence": checkpoint.checkpoint_sequence,
                "hash": checkpoint.checkpoint_hash,
                "created_at": checkpoint.created_at.isoformat(),
            },
        }

    async def enforce_all_organizations(self) -> Dict[str, Any]:
        """
        Runs retention enforcement across all organizations.
        """
        orgs = await self.session.execute(select(Organization.id))
        org_ids = [row[0] for row in orgs.all()]

        total_purged = 0
        results = []
        for org_id in org_ids:
            res = await self.enforce_organization_retention(org_id)
            total_purged += res["purged_count"]
            results.append(res)

        return {
            "total_organizations": len(org_ids),
            "total_purged": total_purged,
            "details": results,
        }

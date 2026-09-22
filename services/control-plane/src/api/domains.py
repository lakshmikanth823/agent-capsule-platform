"""
Domain Verification API: Register email domains and verify ownership via DNS TXT challenges.
"""
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import DomainDAL
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from services.domain_verification import verify_domain_ownership

router = APIRouter(tags=["Domains"])


class CreateDomainClaimRequest(BaseModel):
    domain: str = Field(..., description="Corporate email domain (e.g. acme.com)")


class DomainClaimResponse(BaseModel):
    id: str
    organization_id: str
    domain: str
    verification_token: str
    status: str
    verified_at: Optional[str] = None
    created_at: str


@router.post("/organizations/{org_id}/domains", response_model=DomainClaimResponse, status_code=status.HTTP_201_CREATED)
async def create_domain_claim(
    org_id: uuid.UUID,
    body: CreateDomainClaimRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Registers an email domain claim and returns a DNS TXT verification token."""
    if user.organization_id != org_id or user.platform_role not in ["owner", "editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization administrators can claim domains."},
        )

    domain_dal = DomainDAL(db)
    clean_domain = body.domain.lower().strip()
    if "@" in clean_domain:
        clean_domain = clean_domain.split("@")[-1]

    existing = await domain_dal.get_by_domain(clean_domain)
    if existing:
        if existing.organization_id == org_id:
            return DomainClaimResponse(
                id=str(existing.id),
                organization_id=str(existing.organization_id),
                domain=existing.domain,
                verification_token=existing.verification_token,
                status=existing.status,
                verified_at=existing.verified_at.isoformat() if existing.verified_at else None,
                created_at=existing.created_at.isoformat(),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "DOMAIN_ALREADY_CLAIMED", "message": f"Domain '{clean_domain}' is already claimed by another organization."},
        )

    claim = await domain_dal.create_claim(org_id, clean_domain)
    await db.commit()

    return DomainClaimResponse(
        id=str(claim.id),
        organization_id=str(claim.organization_id),
        domain=claim.domain,
        verification_token=claim.verification_token,
        status=claim.status,
        verified_at=None,
        created_at=claim.created_at.isoformat(),
    )


@router.get("/organizations/{org_id}/domains", response_model=List[DomainClaimResponse])
async def list_domain_claims(
    org_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists all domain claims and verification statuses for the organization."""
    if user.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Access denied to organization domains."},
        )

    domain_dal = DomainDAL(db)
    claims = await domain_dal.list_for_org(org_id)
    return [
        DomainClaimResponse(
            id=str(c.id),
            organization_id=str(c.organization_id),
            domain=c.domain,
            verification_token=c.verification_token,
            status=c.status,
            verified_at=c.verified_at.isoformat() if c.verified_at else None,
            created_at=c.created_at.isoformat(),
        )
        for c in claims
    ]


@router.post("/organizations/{org_id}/domains/{domain}/verify", response_model=DomainClaimResponse)
async def verify_domain(
    org_id: uuid.UUID,
    domain: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Checks DNS TXT record for verification challenge token."""
    if user.organization_id != org_id or user.platform_role not in ["owner", "editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization administrators can verify domains."},
        )

    clean_domain = domain.lower().strip()
    domain_dal = DomainDAL(db)
    claim = await domain_dal.get_by_domain(clean_domain)

    if not claim or claim.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DOMAIN_NOT_FOUND", "message": f"Domain claim for '{clean_domain}' not found."},
        )

    is_valid = await verify_domain_ownership(clean_domain, claim.verification_token)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VERIFICATION_FAILED",
                "message": (
                    f"DNS verification TXT record '{claim.verification_token}' was not found "
                    f"at _capsule-challenge.{clean_domain} or {clean_domain}."
                ),
            },
        )

    claim = await domain_dal.mark_verified(clean_domain)
    await db.commit()

    return DomainClaimResponse(
        id=str(claim.id),
        organization_id=str(claim.organization_id),
        domain=claim.domain,
        verification_token=claim.verification_token,
        status=claim.status,
        verified_at=claim.verified_at.isoformat() if claim.verified_at else None,
        created_at=claim.created_at.isoformat(),
    )


@router.delete("/organizations/{org_id}/domains/{domain}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(
    org_id: uuid.UUID,
    domain: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Removes a domain claim."""
    if user.organization_id != org_id or user.platform_role not in ["owner", "editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization administrators can delete domains."},
        )

    clean_domain = domain.lower().strip()
    domain_dal = DomainDAL(db)
    deleted = await domain_dal.delete_domain(org_id, clean_domain)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DOMAIN_NOT_FOUND", "message": f"Domain claim for '{clean_domain}' not found."},
        )
    await db.commit()

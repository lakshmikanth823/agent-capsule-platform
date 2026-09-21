"""
Authentication data models.
"""
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AuthenticatedUser:
    """Represents a verified caller in the control plane."""
    id: uuid.UUID
    email: str
    display_name: Optional[str]
    organization_id: uuid.UUID
    platform_role: str  # 'owner', 'editor', 'user'
    token_type: str     # 'oidc' or 'publish_token'
    claims: Dict[str, Any] = field(default_factory=dict)
    publish_app_id: Optional[uuid.UUID] = None  # set if publish token is scoped to specific app

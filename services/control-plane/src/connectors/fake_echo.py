from typing import Any, Dict, Optional
from .base import BaseConnector


class FakeEchoConnector(BaseConnector):
    name = "fake.echo"

    async def invoke(
        self,
        payload: Dict[str, Any],
        credential: Any,
        identity: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Test connector: echoes payload and confirms credential was attached by the broker.
        Guarantees zero raw credential leakage.
        """
        if not credential:
            raise ValueError("No credential was attached by broker for fake.echo")

        user_info = None
        if identity:
            user_info = {
                "user_id": str(identity.get("sub") or identity.get("user_id") or ""),
                "email": identity.get("email"),
                "roles": identity.get("roles") or [],
            }

        return {
            "connector": self.name,
            "status": "success",
            "echo": payload,
            "identity": user_info,
            "credential_attached": True,
            "channel": payload.get("channel") or (context.get("channel") if context else None),
        }

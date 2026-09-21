from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseConnector(ABC):
    name: str

    @abstractmethod
    async def invoke(
        self,
        payload: Dict[str, Any],
        credential: Any,
        identity: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executes the connector operation with attached credentials at the egress layer.
        Must NEVER return or log the raw credential.
        """
        pass

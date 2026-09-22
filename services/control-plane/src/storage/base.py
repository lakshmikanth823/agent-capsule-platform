"""
Object Storage Abstraction for Software Capsule Platform.
"""
from abc import ABC, abstractmethod
from typing import Optional


class StorageDriver(ABC):
    """Abstract interface for object storage drivers."""

    @abstractmethod
    async def put(self, path: str, data: bytes, content_type: Optional[str] = None) -> str:
        """Store bytes at the given relative path and return the storage reference."""
        pass

    @abstractmethod
    async def get(self, path: str) -> bytes:
        """Retrieve stored bytes from the given relative path."""
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if an object exists at the given relative path."""
        pass

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete the object at the given relative path if it exists."""
        pass

    @abstractmethod
    async def get_url(self, path: str) -> str:
        """Return a URL or reference URI for the stored object."""
        pass

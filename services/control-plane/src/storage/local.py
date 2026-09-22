"""
Local disk implementation of StorageDriver for development and testing.
"""
import os
import hashlib
from pathlib import Path
from typing import Optional
from .base import StorageDriver


class LocalStorageDriver(StorageDriver):
    """Stores objects on local filesystem under a base directory."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = os.environ.get("STORAGE_LOCAL_DIR", ".capsule/storage")
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, path: str) -> Path:
        # Strip leading slashes to prevent absolute path interpretation
        clean_path = path.lstrip("/\\")
        target = (self.base_dir / clean_path).resolve()
        # Ensure path does not escape base_dir
        if not str(target).startswith(str(self.base_dir)):
            raise ValueError(f"Path traversal detected: {path}")
        return target

    async def put(self, path: str, data: bytes, content_type: Optional[str] = None) -> str:
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file first for atomicity
        temp_target = target.with_suffix(target.suffix + ".tmp")
        temp_target.write_bytes(data)
        temp_target.replace(target)

        # Return canonical relative storage reference
        relative_path = target.relative_to(self.base_dir).as_posix()
        return relative_path

    async def get(self, path: str) -> bytes:
        target = self._resolve_path(path)
        if not target.is_file():
            raise FileNotFoundError(f"Storage object not found: {path}")
        return target.read_bytes()

    async def exists(self, path: str) -> bool:
        target = self._resolve_path(path)
        return target.is_file()

    async def delete(self, path: str) -> bool:
        target = self._resolve_path(path)
        if target.is_file():
            target.unlink()
            return True
        return False

    async def get_url(self, path: str) -> str:
        relative_path = self._resolve_path(path).relative_to(self.base_dir).as_posix()
        return f"file://{relative_path}"

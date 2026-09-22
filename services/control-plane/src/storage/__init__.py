"""
Storage module factory.
"""
from typing import Optional
from .base import StorageDriver
from .local import LocalStorageDriver

_driver_instance: Optional[StorageDriver] = None


def get_storage_driver() -> StorageDriver:
    global _driver_instance
    if _driver_instance is None:
        _driver_instance = LocalStorageDriver()
    return _driver_instance


def set_storage_driver(driver: StorageDriver) -> None:
    global _driver_instance
    _driver_instance = driver


__all__ = ["StorageDriver", "LocalStorageDriver", "get_storage_driver", "set_storage_driver"]

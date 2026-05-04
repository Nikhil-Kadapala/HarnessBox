"""Storage backend registry and lazy loading.

Mirrors the _providers/__init__.py pattern for sandbox backends.
Backends are registered by name and loaded lazily when requested.
"""

from __future__ import annotations

import importlib
from typing import Any

# Registry maps backend name → (module_path, class_name)
_STORAGE_REGISTRY: dict[str, tuple[str, str]] = {
    "memory": ("harnessbox._storage.memory", "MemoryBackend"),
    "sqlite": ("harnessbox._storage.sqlite", "SQLiteBackend"),
}


def get_storage_backend(name: str) -> type[Any]:
    """Resolve a storage backend by name.

    Args:
        name: Backend name ('memory', 'sqlite').

    Returns:
        Storage backend class (uninstantiated).

    Raises:
        ValueError: If backend name is not registered.
        ImportError: If backend module cannot be imported.

    Example:
        >>> backend_cls = get_storage_backend("sqlite")
        >>> storage = backend_cls(path="~/.harnessbox/sessions.db")
    """
    if name not in _STORAGE_REGISTRY:
        registered = ", ".join(_STORAGE_REGISTRY.keys())
        raise ValueError(
            f"Unknown storage backend: {name!r}. Registered: {registered}"
        )

    module_path, class_name = _STORAGE_REGISTRY[name]
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def register_storage_backend(
    name: str, module_path: str, class_name: str
) -> None:
    """Register a custom storage backend.

    Args:
        name: Backend name (used in get_storage_backend()).
        module_path: Full module path (e.g., 'myproject.backends.redis').
        class_name: Class name within the module (e.g., 'RedisBackend').

    Example:
        >>> register_storage_backend(
        ...     "redis", "myproject.backends.redis", "RedisBackend"
        ... )
        >>> backend = get_storage_backend("redis")
    """
    _STORAGE_REGISTRY[name] = (module_path, class_name)


__all__ = ["get_storage_backend", "register_storage_backend"]

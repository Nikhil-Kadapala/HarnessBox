"""Provider registry — resolves string names to provider classes."""

from __future__ import annotations

import importlib
from typing import Any, cast

_PROVIDER_REGISTRY: dict[str, tuple[str, str]] = {
    "e2b": ("harnessbox._providers.e2b", "E2BProvider"),
    "docker": ("harnessbox._providers.docker", "DockerProvider"),
    "daytona": ("harnessbox._providers.daytona", "DaytonaProvider"),
    "ec2": ("harnessbox._providers.ec2", "EC2Provider"),
}


def register_provider(name: str, module_path: str, class_name: str) -> None:
    """Register a provider for string-based resolution."""
    _PROVIDER_REGISTRY[name] = (module_path, class_name)


def get_provider_class(name: str) -> type[Any]:
    """Resolve a provider name to its class via lazy import.

    Raises KeyError if the provider name is unknown.
    Raises ImportError with a helpful message if the SDK is not installed.
    """
    if name not in _PROVIDER_REGISTRY:
        registered = ", ".join(sorted(_PROVIDER_REGISTRY)) or "(none)"
        raise KeyError(
            f"Unknown provider {name!r}. Registered providers: {registered}. "
            f"Use register_provider() to add custom providers."
        )

    module_path, class_name = _PROVIDER_REGISTRY[name]

    try:
        mod = importlib.import_module(module_path)
    except ImportError as e:
        raise ImportError(
            f"Provider {name!r} requires additional dependencies. "
            f"Install them with: pip install harnessbox[{name}]"
        ) from e

    return cast(type[Any], getattr(mod, class_name))


def list_providers() -> list[str]:
    """Return names of all registered providers."""
    return sorted(_PROVIDER_REGISTRY)

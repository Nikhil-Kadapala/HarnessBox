"""Configuration subpackage — harness types, manifests."""

from harnessbox.config.harness import (
    HarnessTypeConfig,
    get_harness_type,
    list_harness_types,
    register_harness_type,
)
from harnessbox.config.manifest import SandboxManifest, build_manifest

__all__ = [
    "HarnessTypeConfig",
    "SandboxManifest",
    "build_manifest",
    "get_harness_type",
    "list_harness_types",
    "register_harness_type",
]

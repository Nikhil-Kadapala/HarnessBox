"""Discovery endpoints — stateless, read-only introspection of the HarnessBox environment."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["discovery"])


@router.get("/v1/credentials/status")
async def get_credentials() -> dict[str, Any]:
    from harnessbox.credentials import detect_credentials

    status = detect_credentials()
    return {
        "probes": [{"name": p.name, "available": p.available} for p in status.probes],
        "timestamp": status.timestamp,
    }


@router.get("/v1/harnesses")
async def list_harnesses() -> list[dict[str, Any]]:
    from harnessbox.config.harness import get_harness_type, list_harness_types

    result = []
    for name in list_harness_types():
        cfg = get_harness_type(name)
        result.append(
            {
                "name": cfg.name,
                "cli_command": cfg.cli_command,
                "supports_persistent": cfg.supports_persistent,
                "default_template": cfg.default_template,
                "workspace_root": cfg.workspace_root,
            }
        )
    return result


@router.get("/v1/providers")
async def list_available_providers() -> list[dict[str, str]]:
    from harnessbox._providers import list_providers

    return [{"name": p} for p in list_providers()]


@router.get("/v1/guards")
async def list_guards() -> list[dict[str, Any]]:
    from harnessbox.security.guards import GUARD_CATALOG

    return [
        {
            "name": gs.name,
            "bash_deny_count": len(gs.bash_deny_globs),
            "read_deny_count": len(gs.read_deny_globs),
        }
        for gs in GUARD_CATALOG.values()
    ]

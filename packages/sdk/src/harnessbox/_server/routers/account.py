"""Account endpoints — external identity lookups."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["account"])


@router.get("/v1/account/github")
async def get_github_profile() -> dict[str, Any]:
    """Fetch GitHub profile using the local gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "api", "user"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail="GitHub CLI not authenticated")
        data = json.loads(result.stdout)
        return {
            "login": data.get("login", ""),
            "name": data.get("name"),
            "email": data.get("email"),
            "avatar_url": data.get("avatar_url", ""),
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="GitHub CLI not installed")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="GitHub API request timed out")

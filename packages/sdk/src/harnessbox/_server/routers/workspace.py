"""Workspace endpoints — name generation and git repo detection."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

from harnessbox._server.workspace_factory import convert_ssh_to_https

router = APIRouter(tags=["workspace"])


@router.get("/v1/workspace/name")
async def generate_workspace_name() -> dict[str, str]:
    """Generate a unique city name for a new workspace."""
    from harnessbox.names import generate_workspace_name

    return {"name": generate_workspace_name()}


@router.get("/v1/workspace/detect")
async def detect_workspace(path: str) -> dict[str, str]:
    """Detect git repo info from a local filesystem path."""
    repo_path = Path(path).expanduser().resolve()
    git_dir = repo_path / ".git"

    if not git_dir.exists():
        raise HTTPException(status_code=400, detail="Not a git repository")

    if not git_dir.is_dir():
        raise HTTPException(status_code=400, detail="Invalid git repository")

    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        remote = result.stdout.strip()
        if not remote:
            raise HTTPException(status_code=400, detail="No remote.origin.url found")
        remote = convert_ssh_to_https(remote)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=400, detail="Failed to read remote URL") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=500, detail="Git command timed out") from exc

    default_branch = "main"
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            if ref.startswith("refs/remotes/origin/"):
                default_branch = ref.replace("refs/remotes/origin/", "")
        else:
            for branch in ["main", "master"]:
                result = subprocess.run(
                    ["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
                if result.returncode == 0:
                    default_branch = branch
                    break
    except subprocess.TimeoutExpired:
        pass

    name = repo_path.name

    return {"remote": remote, "default_branch": default_branch, "name": name}

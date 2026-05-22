"""HarnessBox multi-session — run multiple agents on different branches.

Usage:
    pip install "harnessbox[e2b]"
    E2B_API_KEY=your-key ANTHROPIC_API_KEY=your-key python examples/multi_session.py
"""

from __future__ import annotations

import asyncio
import os

from harnessbox import HarnessBox, WorkspaceConfig
from harnessbox.workspace import GitRepoConfig


async def main() -> None:
    e2b_key = os.environ.get("E2B_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not e2b_key or not anthropic_key:
        print("Set E2B_API_KEY and ANTHROPIC_API_KEY environment variables.")
        return

    hb = HarnessBox(
        provider="e2b",
        harness="claude-code",
        workspace_config=WorkspaceConfig(
            git_repo_config=GitRepoConfig(
                remote="https://github.com/your-org/your-repo.git",
                branch="main",
                base_branch="main",
            ),
        ),
        secrets={
            "provider_api_key": e2b_key,
            "harness_secrets": {
                "ANTHROPIC_API_KEY": anthropic_key,
            },
        },
    )

    # Create two sessions on different branches
    auth_session = await hb.create_session(branch="feat/auth")
    ui_session = await hb.create_session(branch="feat/ui")

    print(f"Auth session: {auth_session.id} on sandbox {auth_session.sandbox_id}")
    print(f"UI session:   {ui_session.id} on sandbox {ui_session.sandbox_id}")

    # Send messages to each session
    async for event in auth_session.send_message("List the files in this repo"):
        if event.delta:
            print(event.delta, end="")
    print()

    # Non-streaming mode
    result = await ui_session.send_message("What framework is this project using?", stream=False)
    print(f"\nUI session response: {result.text[:200]}")

    # Check status
    print(f"\nAuth status: {auth_session.status}")
    print(f"UI status:   {ui_session.status}")

    # Clean up
    await hb.kill()
    print("\nAll sessions destroyed.")


if __name__ == "__main__":
    asyncio.run(main())

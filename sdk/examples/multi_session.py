"""HarnessBox multi-session — run multiple agents on different branches.

Usage:
    pip install "harnessbox[e2b]"
    E2B_API_KEY=your-key ANTHROPIC_API_KEY=your-key python examples/multi_session.py
"""

from __future__ import annotations

import asyncio
import os

from harnessbox import HarnessBox, WorkspaceMode


async def main() -> None:
    e2b_key = os.environ.get("E2B_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not e2b_key or not anthropic_key:
        print("Set E2B_API_KEY and ANTHROPIC_API_KEY environment variables.")
        return

    hb = HarnessBox(
        provider="e2b",
        harness="claude-code",
        remote="https://github.com/your-org/your-repo.git",
        workspace_mode=WorkspaceMode.NEW,
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

    print(f"Auth session: {auth_session.id} (branch: {auth_session.branch})")
    print(f"UI session:   {ui_session.id} (branch: {ui_session.branch})")

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
    await auth_session.kill()
    await ui_session.kill()
    print("\nSessions destroyed.")


if __name__ == "__main__":
    asyncio.run(main())

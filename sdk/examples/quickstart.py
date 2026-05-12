"""HarnessBox quickstart — run a command in a sandboxed environment with event logging.

Usage:
    pip install "harnessbox[e2b]"
    E2B_API_KEY=your-key python examples/quickstart.py
"""

from __future__ import annotations

import asyncio
import os

from harnessbox import JsonLogger, Sandbox


async def main() -> None:
    api_key = os.environ.get("E2B_API_KEY", "")
    if not api_key:
        print("Set E2B_API_KEY environment variable to run this example.")
        print("Get a free key at https://e2b.dev")
        return

    sandbox = Sandbox(
        "e2b",
        api_key=api_key,
        event_handler=JsonLogger(),
    )

    await sandbox.setup()

    result = await sandbox.run_command("echo 'Hello from the sandbox!'")
    print(f"\nOutput: {result.stdout.strip()}")
    print(f"Exit code: {result.exit_code}")

    await sandbox.kill()


if __name__ == "__main__":
    asyncio.run(main())

import json

import pytest

from harnessbox.process import AgentProcess
from harnessbox.streaming import StreamParser


class StdinProvider:
    def __init__(self) -> None:
        self.stdin: list[str] = []

    async def send_stdin(self, pid: int, data: str) -> None:
        self.stdin.append(data)


@pytest.mark.asyncio
async def test_send_command_captures_structured_stdout_content() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))
    process._running = True
    process._pid = 42

    await process._stdout_queue.put(
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "local-command-stdout",
                            "text": "**Tokens:** 153.7k / 200k (77%)",
                        }
                    ]
                },
            }
        )
    )
    await process._stdout_queue.put(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "total_cost_usd": 0.12,
            }
        )
    )

    result = await process.send_command("/context")

    assert json.loads(provider.stdin[0])["message"]["content"] == "/context"
    assert result["output"] == "**Tokens:** 153.7k / 200k (77%)"
    assert result["total_cost_usd"] == 0.12


@pytest.mark.asyncio
async def test_send_command_captures_nested_content() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))
    process._running = True
    process._pid = 42

    await process._stdout_queue.put(
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Tokens: 1.2k / 10k (12%)",
                                }
                            ],
                        }
                    ]
                },
            }
        )
    )
    await process._stdout_queue.put(json.dumps({"type": "result", "subtype": "success"}))

    result = await process.send_command("/context")

    assert result["output"] == "Tokens: 1.2k / 10k (12%)"

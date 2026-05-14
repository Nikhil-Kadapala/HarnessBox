from harnessbox.sandbox import Sandbox


def test_parse_context_output_with_aggregate_tokens() -> None:
    parsed = Sandbox._parse_context_output(
        """
**Model:** gpt-5.4
**Tokens:** 153.7k / 200k (77%)
"""
    )

    assert parsed == {
        "tokens_used": 153_700,
        "context_window": 200_000,
        "percent_used": 77,
        "model": "gpt-5.4",
    }


def test_parse_context_output_with_category_breakdown() -> None:
    parsed = Sandbox._parse_context_output(
        """
**Tokens:** 153.7K / 200K (77%)

System prompt 3.7K
Tools 13.6K
Rules 3.5K
Skills 91.5K
MCP 3.8K
Subagents 683
Conversation 36.8K
"""
    )

    assert parsed is not None
    assert parsed["categories"] == [
        {"key": "system_prompt", "label": "System prompt", "tokens": 3_700},
        {"key": "tools", "label": "Tools", "tokens": 13_600},
        {"key": "rules", "label": "Rules", "tokens": 3_500},
        {"key": "skills", "label": "Skills", "tokens": 91_500},
        {"key": "mcp", "label": "MCP", "tokens": 3_800},
        {"key": "subagents", "label": "Subagents", "tokens": 683},
        {"key": "conversation", "label": "Conversation", "tokens": 36_800},
    ]


def test_parse_context_output_with_table_rows_and_plain_token_values() -> None:
    parsed = Sandbox._parse_context_output(
        """
**Tokens:** 153,700 / 200,000 (77%)

| System prompt | 3,700 |
| Conversation | 36.8k |
"""
    )

    assert parsed is not None
    assert parsed["tokens_used"] == 153_700
    assert parsed["context_window"] == 200_000
    assert parsed["categories"] == [
        {"key": "system_prompt", "label": "System prompt", "tokens": 3_700},
        {"key": "conversation", "label": "Conversation", "tokens": 36_800},
    ]


def test_parse_context_output_accepts_plain_labels() -> None:
    parsed = Sandbox._parse_context_output(
        """
Model: claude-sonnet-4-5
Tokens: 153.7k / 200k (77%)
"""
    )

    assert parsed == {
        "tokens_used": 153_700,
        "context_window": 200_000,
        "percent_used": 77,
        "model": "claude-sonnet-4-5",
    }


def test_parse_context_output_accepts_claude_terminal_context_view() -> None:
    parsed = Sandbox._parse_context_output(
        """
Context Usage
Opus 4.6 (1M context)
us.anthropic.claude-opus-4-6-v1[1m]
22.3K/1m tokens (2%)

Estimated usage by category
System prompt: 6.2k tokens (0.6%)
System tools: 470 tokens (0.0%)
Memory files: 6.8k tokens (0.7%)
Skills: 8.8k tokens (0.9%)
Messages: 25 tokens (0.0%)
Free space: 944.7k (94.5%)
Autocompact buffer: 33k tokens (3.3%)
"""
    )

    assert parsed is not None
    assert parsed["tokens_used"] == 22_300
    assert parsed["context_window"] == 1_000_000
    assert parsed["percent_used"] == 2
    assert parsed["model"] == "Opus 4.6"
    assert parsed["categories"] == [
        {"key": "system_prompt", "label": "System prompt", "tokens": 6_200},
        {"key": "system_tools", "label": "System tools", "tokens": 470},
        {"key": "memory_files", "label": "Memory files", "tokens": 6_800},
        {"key": "skills", "label": "Skills", "tokens": 8_800},
        {"key": "messages", "label": "Messages", "tokens": 25},
        {"key": "free_space", "label": "Free space", "tokens": 944_700},
        {"key": "autocompact_buffer", "label": "Autocompact buffer", "tokens": 33_000},
    ]


def test_parse_context_output_fills_missing_terminal_categories() -> None:
    parsed = Sandbox._parse_context_output(
        """
Context Usage
Sonnet 4.5 (200K context)
18.0K / 200K tokens (9%)

Estimated usage by category
System prompt: 3.2K tokens
System tools: 16.1K tokens
Messages: 149 tokens
Free space: 147.6K tokens
Autocompact buffer: 33K tokens
"""
    )

    assert parsed is not None
    assert parsed["categories"] == [
        {"key": "system_prompt", "label": "System prompt", "tokens": 3_200},
        {"key": "system_tools", "label": "System tools", "tokens": 16_100},
        {"key": "memory_files", "label": "Memory files", "tokens": 0},
        {"key": "skills", "label": "Skills", "tokens": 0},
        {"key": "messages", "label": "Messages", "tokens": 149},
        {"key": "free_space", "label": "Free space", "tokens": 147_600},
        {"key": "autocompact_buffer", "label": "Autocompact buffer", "tokens": 33_000},
    ]


def test_parse_context_output_ignores_malformed_category_lines() -> None:
    parsed = Sandbox._parse_context_output(
        """
**Tokens:** 1.2k / 10k (12%)
Tools unavailable
Conversation unknown
"""
    )

    assert parsed == {
        "tokens_used": 1_200,
        "context_window": 10_000,
        "percent_used": 12,
    }

"""Post-turn status parsing — context window and token usage."""

from __future__ import annotations

import re
from typing import Any


def parse_context_output(text: str) -> dict[str, Any] | None:
    """Parse the markdown output from /context into structured data."""

    def parse_token_count(value: str, suffix: str | None = None) -> int:
        multiplier = 1
        if suffix:
            normalized_suffix = suffix.lower()
            if normalized_suffix == "k":
                multiplier = 1_000
            elif normalized_suffix == "m":
                multiplier = 1_000_000
        return int(float(value.replace(",", "")) * multiplier)

    result: dict[str, Any] = {}
    tokens_match = re.search(
        r"(?:\*\*)?Tokens:(?:\*\*)?\s*([\d,.]+)\s*([kKmM]?)\s*/\s*([\d,.]+)\s*([kKmM]?)\s*\((\d+)%\)",
        text,
        re.IGNORECASE,
    )
    if not tokens_match:
        tokens_match = re.search(
            r"\b([\d,.]+)\s*([kKmM])\s*/\s*([\d,.]+)\s*([kKmM])\s+tokens\s*\((\d+)%\)",
            text,
            re.IGNORECASE,
        )
    if tokens_match:
        percent = int(tokens_match.group(5))
        result["tokens_used"] = parse_token_count(tokens_match.group(1), tokens_match.group(2))
        result["context_window"] = parse_token_count(tokens_match.group(3), tokens_match.group(4))
        result["percent_used"] = percent

    model_match = re.search(r"(?:\*\*)?Model:(?:\*\*)?\s*(\S+)", text, re.IGNORECASE)
    if not model_match:
        model_match = re.search(
            r"\b([A-Za-z][A-Za-z0-9 ._-]+)\s+\((?:[\d.]+[kKmM]\s+)?context\)",
            text,
            re.IGNORECASE,
        )
    if model_match:
        result["model"] = model_match.group(1).strip()

    category_labels = [
        ("system prompt", "system_prompt", "System prompt"),
        ("system tools", "system_tools", "System tools"),
        ("memory files", "memory_files", "Memory files"),
        ("tools", "tools", "Tools"),
        ("rules", "rules", "Rules"),
        ("skills", "skills", "Skills"),
        ("mcp", "mcp", "MCP"),
        ("subagents", "subagents", "Subagents"),
        ("messages", "messages", "Messages"),
        ("conversation", "conversation", "Conversation"),
        ("free space", "free_space", "Free space"),
        ("autocompact buffer", "autocompact_buffer", "Autocompact buffer"),
    ]
    categories: list[dict[str, Any]] = []
    seen_category_keys: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip().strip("|").strip()
        if not line or "tokens:" in line.lower() or "model:" in line.lower():
            continue
        normalized_line = re.sub(r"[*_`]", "", line)
        for label, key, display_label in category_labels:
            if key in seen_category_keys:
                continue
            category_match = re.search(
                rf"\b{re.escape(label)}\b\s*(?:\||:|-|—|–)?\s*~?\$?([\d,.]+)\s*([kKmM]?)\s*(?:tokens?)?\b",
                normalized_line,
                re.IGNORECASE,
            )
            if not category_match:
                continue
            categories.append(
                {
                    "key": key,
                    "label": display_label,
                    "tokens": parse_token_count(
                        category_match.group(1),
                        category_match.group(2),
                    ),
                }
            )
            seen_category_keys.add(key)
            break

    if categories:
        if any(category["key"] in {"system_tools", "free_space"} for category in categories):
            terminal_category_defaults = [
                ("system_prompt", "System prompt"),
                ("system_tools", "System tools"),
                ("memory_files", "Memory files"),
                ("skills", "Skills"),
                ("messages", "Messages"),
                ("free_space", "Free space"),
                ("autocompact_buffer", "Autocompact buffer"),
            ]
            existing_categories = {category["key"]: category for category in categories}
            categories = [
                existing_categories.get(
                    key,
                    {
                        "key": key,
                        "label": label,
                        "tokens": 0,
                    },
                )
                for key, label in terminal_category_defaults
            ]
        result["categories"] = categories

    return result if result else None

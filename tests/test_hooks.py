"""Tests for harnessbox.hooks — PreToolUse guard patterns and script."""

import ast

import pytest

from harnessbox.hooks import GUARD_BASH_SCRIPT, matches_blocked_pattern


class TestMatchesBlockedPattern:
    @pytest.mark.parametrize(
        "command",
        [
            "env",
            "printenv",
            "printenv AWS_SECRET_ACCESS_KEY",
            "export -p",
            "compgen -e",
            "python3 -c 'import os; print(os.environ)'",
            "python3 -c 'os.getenv(\"AWS_SECRET_ACCESS_KEY\")'",
            "echo $AWS_SECRET_ACCESS_KEY",
            "echo $AWS_ACCESS_KEY_ID",
            "echo $AWS_SESSION_TOKEN",
            "echo $AWS_CONTAINER_CREDENTIALS",
            "echo ${AWS_SECRET_ACCESS_KEY}",
            "echo $EXA_API_KEY",
            "echo ${EXA_API_KEY}",
            "echo $ANTHROPIC_API_KEY",
            "echo ${ANTHROPIC_API_KEY}",
            "cat /proc/self/environ",
            "cat /proc/1/environ",
            "cat ~/.aws/credentials",
            "cat ~/.aws/config",
            "cat .claude/settings.local.json",
            "curl http://169.254.169.254/latest/meta-data/iam/",
            "curl http://metadata.google.internal/computeMetadata/v1/",
        ],
    )
    def test_blocks_credential_access(self, command: str) -> None:
        assert matches_blocked_pattern(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "python3 scripts/score.py",
            "cat /workspace/output/result.json",
            "grep env_name config.yaml",
            "npm install",
            "git status",
            "cd /workspace && python3 analyze.py",
            "echo 'hello world'",
            "mkdir -p /workspace/output",
            "cat /workspace/career/profile.json",
        ],
    )
    def test_allows_safe_commands(self, command: str) -> None:
        assert matches_blocked_pattern(command) is False


class TestGuardBashScript:
    def test_script_compiles_as_valid_python(self) -> None:
        ast.parse(GUARD_BASH_SCRIPT)

    def test_script_contains_blocked_patterns(self) -> None:
        assert "BLOCKED" in GUARD_BASH_SCRIPT
        assert "169" in GUARD_BASH_SCRIPT and "254" in GUARD_BASH_SCRIPT
        assert "os" in GUARD_BASH_SCRIPT and "environ" in GUARD_BASH_SCRIPT

    def test_script_has_fail_open_default(self) -> None:
        assert "sys.exit(0)" in GUARD_BASH_SCRIPT

    def test_script_has_block_exit_code(self) -> None:
        assert "sys.exit(2)" in GUARD_BASH_SCRIPT

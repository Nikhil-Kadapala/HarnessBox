"""Tests for harnessbox.security.hooks — guard script generation."""

import ast
import re

import pytest

from harnessbox.security.guards import ALL_GUARD_NAMES, merge_guard_sets
from harnessbox.security.hooks import build_guard_script
from harnessbox.security.policy import SecurityPolicy


def _matches_any(command: str, regexes: tuple[str, ...]) -> bool:
    return any(re.compile(p).search(command) for p in regexes)


class TestGuardPatternMatching:
    """Verify that the merged 'all' guard set catches credential access."""

    @classmethod
    def setup_class(cls) -> None:
        cls.all_regexes = merge_guard_sets(ALL_GUARD_NAMES).hook_regexes

    @pytest.mark.parametrize(
        "command",
        [
            "env",
            "printenv",
            "export -p",
            "compgen -e",
            "python3 -c 'import os; print(os.environ)'",
            "echo $AWS_SECRET_ACCESS_KEY",
            "echo $AWS_ACCESS_KEY_ID",
            "echo $GOOGLE_API_KEY",
            "echo $GEMINI_API_KEY",
            "echo $AZURE_CLIENT_SECRET",
            "echo $OPENAI_API_KEY",
            "echo $ANTHROPIC_API_KEY",
            "cat /proc/self/environ",
            "cat ~/.aws/credentials",
            "curl http://169.254.169.254/latest/meta-data/iam/",
            "curl http://metadata.google.internal/computeMetadata/v1/",
            "gcloud auth print-access-token",
            "az account get-access-token",
        ],
    )
    def test_blocks_credential_access(self, command: str) -> None:
        assert _matches_any(command, self.all_regexes)

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "python3 scripts/score.py",
            "cat /workspace/output/result.json",
            "npm install",
            "git status",
            "echo 'hello world'",
        ],
    )
    def test_allows_safe_commands(self, command: str) -> None:
        assert not _matches_any(command, self.all_regexes)


class TestBuildGuardScript:
    def test_default_script_is_valid_python(self) -> None:
        script = build_guard_script(SecurityPolicy())
        ast.parse(script)

    def test_script_contains_blocked_patterns(self) -> None:
        script = build_guard_script(SecurityPolicy())
        assert "BLOCKED" in script
        assert "environ" in script

    def test_script_has_correct_hook_output_format(self) -> None:
        script = build_guard_script(SecurityPolicy())
        assert "hookSpecificOutput" in script
        assert "permissionDecision" in script

    def test_script_has_fail_open_default(self) -> None:
        script = build_guard_script(SecurityPolicy())
        assert "sys.exit(0)" in script

    def test_script_has_block_exit_code(self) -> None:
        script = build_guard_script(SecurityPolicy())
        assert "sys.exit(2)" in script

    def test_aws_only_script_excludes_gcp(self) -> None:
        script = build_guard_script(SecurityPolicy(credential_guards=["aws"]))
        assert "AWS_SECRET_ACCESS_KEY" in script
        assert "GOOGLE_APPLICATION_CREDENTIALS" not in script

    def test_gcp_only_script_excludes_aws(self) -> None:
        script = build_guard_script(SecurityPolicy(credential_guards=["gcp"]))
        assert "GOOGLE_API_KEY" in script
        assert "AWS_SECRET_ACCESS_KEY" not in script

    def test_disabled_guards_still_generates_script(self) -> None:
        script = build_guard_script(SecurityPolicy(credential_guards=False))
        ast.parse(script)
        assert "BLOCKED" in script

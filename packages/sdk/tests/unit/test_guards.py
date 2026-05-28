"""Tests for harnessbox.security.guards — credential guard catalog."""

from __future__ import annotations

import re

import pytest

from harnessbox.security.guards import (
    ALL_GUARD_NAMES,
    AWS,
    AZURE,
    CORE,
    DATABASES,
    DOCKER,
    GCP,
    GENERIC,
    GUARD_CATALOG,
    KUBERNETES,
    LLM_PROVIDERS,
    PACKAGE_MANAGERS,
    SSH,
    CredentialGuardSet,
    merge_guard_sets,
)


class TestCredentialGuardSet:
    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            CORE.name = "changed"  # type: ignore[misc]

    def test_all_sets_in_catalog(self) -> None:
        assert len(GUARD_CATALOG) == 10
        assert set(GUARD_CATALOG.keys()) == ALL_GUARD_NAMES

    def test_core_not_in_catalog(self) -> None:
        assert "core" not in GUARD_CATALOG


class TestGuardSetContents:
    @pytest.mark.parametrize(
        "guard_set",
        [
            AWS,
            GCP,
            AZURE,
            SSH,
            DOCKER,
            KUBERNETES,
            DATABASES,
            PACKAGE_MANAGERS,
            LLM_PROVIDERS,
            GENERIC,
        ],
        ids=lambda gs: gs.name,
    )
    def test_has_hook_regexes(self, guard_set: CredentialGuardSet) -> None:
        assert len(guard_set.hook_regexes) > 0

    @pytest.mark.parametrize(
        "guard_set",
        [
            AWS,
            GCP,
            AZURE,
            SSH,
            DOCKER,
            KUBERNETES,
            DATABASES,
            PACKAGE_MANAGERS,
            LLM_PROVIDERS,
            GENERIC,
        ],
        ids=lambda gs: gs.name,
    )
    def test_regexes_compile(self, guard_set: CredentialGuardSet) -> None:
        for pattern in guard_set.hook_regexes:
            re.compile(pattern)

    @pytest.mark.parametrize(
        "guard_set",
        [CORE, AWS, GCP, AZURE, SSH, DOCKER, KUBERNETES],
        ids=lambda gs: gs.name,
    )
    def test_no_duplicate_patterns(self, guard_set: CredentialGuardSet) -> None:
        assert len(guard_set.bash_deny_globs) == len(set(guard_set.bash_deny_globs))
        assert len(guard_set.read_deny_globs) == len(set(guard_set.read_deny_globs))
        assert len(guard_set.hook_regexes) == len(set(guard_set.hook_regexes))


class TestSentinelPatterns:
    def test_aws_metadata(self) -> None:
        assert any("169" in p and "254" in p for p in AWS.hook_regexes)
        assert any("170" in p for p in AWS.hook_regexes)

    def test_gcp_metadata(self) -> None:
        assert any("metadata" in p and "google" in p for p in GCP.hook_regexes)

    def test_gcp_gemini_keys(self) -> None:
        assert any("GOOGLE_API_KEY" in p for p in GCP.hook_regexes)
        assert any("GEMINI_API_KEY" in p for p in GCP.hook_regexes)
        assert any("VERTEX_AI_API_KEY" in p for p in GCP.hook_regexes)

    def test_azure_metadata(self) -> None:
        assert any("168" in p and "63" in p for p in AZURE.hook_regexes)

    def test_azure_secrets(self) -> None:
        assert any("AZURE_CLIENT_SECRET" in p for p in AZURE.hook_regexes)

    def test_ssh_keys(self) -> None:
        assert any("id_rsa" in p for p in SSH.hook_regexes)
        assert any("id_ed25519" in p for p in SSH.hook_regexes)

    def test_docker_socket(self) -> None:
        assert any("docker" in p and "sock" in p for p in DOCKER.hook_regexes)

    def test_kubernetes_serviceaccount(self) -> None:
        assert any("kubernetes" in p for p in KUBERNETES.hook_regexes)

    def test_database_urls(self) -> None:
        assert any("DATABASE_URL" in p for p in DATABASES.hook_regexes)
        assert any("postgres" in p for p in DATABASES.hook_regexes)

    def test_llm_providers(self) -> None:
        assert any("OPENAI_API_KEY" in p for p in LLM_PROVIDERS.hook_regexes)
        assert any("ANTHROPIC_API_KEY" in p for p in LLM_PROVIDERS.hook_regexes)

    def test_generic_wildcards(self) -> None:
        assert any("SECRET" in p for p in GENERIC.hook_regexes)
        assert any("TOKEN" in p for p in GENERIC.hook_regexes)
        assert any("API_KEY" in p for p in GENERIC.hook_regexes)


class TestMergeGuardSets:
    def test_single_set_includes_core(self) -> None:
        merged = merge_guard_sets(frozenset({"aws"}))
        for p in CORE.hook_regexes:
            assert p in merged.hook_regexes
        for p in AWS.hook_regexes:
            assert p in merged.hook_regexes

    def test_single_set_excludes_others(self) -> None:
        merged = merge_guard_sets(frozenset({"aws"}))
        for p in GCP.hook_regexes:
            if p not in CORE.hook_regexes and p not in AWS.hook_regexes:
                assert p not in merged.hook_regexes

    def test_multi_set(self) -> None:
        merged = merge_guard_sets(frozenset({"aws", "gcp"}))
        assert any("AWS_SECRET_ACCESS_KEY" in p for p in merged.hook_regexes)
        assert any("GOOGLE_API_KEY" in p for p in merged.hook_regexes)

    def test_all_sets(self) -> None:
        merged = merge_guard_sets(ALL_GUARD_NAMES)
        assert len(merged.hook_regexes) > 100

    def test_no_duplicates_in_merged(self) -> None:
        merged = merge_guard_sets(ALL_GUARD_NAMES)
        assert len(merged.hook_regexes) == len(set(merged.hook_regexes))
        assert len(merged.bash_deny_globs) == len(set(merged.bash_deny_globs))
        assert len(merged.read_deny_globs) == len(set(merged.read_deny_globs))

    def test_extra_patterns(self) -> None:
        merged = merge_guard_sets(
            frozenset({"aws"}),
            extra_bash_guards=("custom-bash-pattern",),
            extra_read_guards=("~/.custom/secret",),
            extra_hook_regexes=(r"CUSTOM_SECRET",),
        )
        assert "custom-bash-pattern" in merged.bash_deny_globs
        assert "~/.custom/secret" in merged.read_deny_globs
        assert "CUSTOM_SECRET" in merged.hook_regexes

    def test_deterministic_order(self) -> None:
        m1 = merge_guard_sets(frozenset({"aws", "gcp", "azure"}))
        m2 = merge_guard_sets(frozenset({"azure", "aws", "gcp"}))
        assert m1.hook_regexes == m2.hook_regexes
        assert m1.bash_deny_globs == m2.bash_deny_globs

    def test_unknown_name_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown credential guard set"):
            merge_guard_sets(frozenset({"nonexistent"}))

    def test_merged_name_is_merged(self) -> None:
        merged = merge_guard_sets(frozenset({"aws"}))
        assert merged.name == "merged"

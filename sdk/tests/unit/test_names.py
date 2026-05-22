"""Tests for workspace name generation."""

from harnessbox.names import generate_workspace_name


class TestGenerateWorkspaceName:
    """Test workspace name generation."""

    def test_returns_lowercase_string(self) -> None:
        """Name should be lowercase."""
        name = generate_workspace_name()
        assert name == name.lower()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_returns_hyphenated_string(self) -> None:
        """Multi-word names should be hyphenated."""
        name = generate_workspace_name()
        assert " " not in name

    def test_no_duplicates_within_pool(self) -> None:
        """Should not return duplicates until pool is exhausted."""
        names = [generate_workspace_name() for _ in range(50)]
        assert len(names) == len(set(names))

    def test_pool_resets_when_exhausted(self) -> None:
        """Pool should reset when all names are used."""
        all_names = []
        for _ in range(250):
            all_names.append(generate_workspace_name())
        assert len(all_names) == 250
        assert len(set(all_names)) < 250

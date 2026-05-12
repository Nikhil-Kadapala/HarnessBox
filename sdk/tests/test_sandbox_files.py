"""Tests for Sandbox file injection — Path, str, list, and dict forms."""

from __future__ import annotations

from pathlib import Path

import pytest

from harnessbox.sandbox import Sandbox

from .conftest import MockProvider


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


class TestResolveFilesDict:
    def test_str_values_pass_through(self, provider: MockProvider) -> None:
        sandbox = Sandbox(
            provider,
            files={"/workspace/test.txt": "hello world"},
        )
        assert sandbox._files == {"/workspace/test.txt": "hello world"}

    def test_path_values_read_from_disk(self, provider: MockProvider, tmp_path: Path) -> None:
        f = tmp_path / "config.json"
        f.write_text('{"key": "value"}', encoding="utf-8")
        sandbox = Sandbox(
            provider,
            files={"/workspace/config.json": f},
        )
        assert sandbox._files == {"/workspace/config.json": '{"key": "value"}'}

    def test_mixed_str_and_path(self, provider: MockProvider, tmp_path: Path) -> None:
        f = tmp_path / "from_disk.txt"
        f.write_text("disk content", encoding="utf-8")
        sandbox = Sandbox(
            provider,
            files={
                "/workspace/from_disk.txt": f,
                "/workspace/inline.txt": "inline content",
            },
        )
        assert sandbox._files["/workspace/from_disk.txt"] == "disk content"
        assert sandbox._files["/workspace/inline.txt"] == "inline content"

    def test_path_not_found_raises(self, provider: MockProvider) -> None:
        with pytest.raises(FileNotFoundError, match="file not found"):
            Sandbox(
                provider,
                files={"/workspace/missing.txt": Path("/nonexistent/file.txt")},
            )


class TestResolveFilesList:
    def test_list_of_paths(self, provider: MockProvider, tmp_path: Path) -> None:
        a = tmp_path / "CLAUDE.md"
        a.write_text("system prompt", encoding="utf-8")
        b = tmp_path / "rules.json"
        b.write_text('{"rule": 1}', encoding="utf-8")
        sandbox = Sandbox(
            provider,
            files=[str(a), str(b)],
        )
        assert sandbox._files["/workspace/CLAUDE.md"] == "system prompt"
        assert sandbox._files["/workspace/rules.json"] == '{"rule": 1}'

    def test_list_of_path_objects(self, provider: MockProvider, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text("print('hi')", encoding="utf-8")
        sandbox = Sandbox(
            provider,
            files=[f],
        )
        assert sandbox._files["/workspace/test.py"] == "print('hi')"

    def test_list_not_found_raises(self, provider: MockProvider) -> None:
        with pytest.raises(FileNotFoundError, match="file not found"):
            Sandbox(provider, files=["/nonexistent/file.txt"])

    def test_empty_list(self, provider: MockProvider) -> None:
        sandbox = Sandbox(provider, files=[])
        assert sandbox._files == {}


class TestResolveFilesNone:
    def test_none_gives_empty(self, provider: MockProvider) -> None:
        sandbox = Sandbox(provider, files=None)
        assert sandbox._files == {}

    def test_default_gives_empty(self, provider: MockProvider) -> None:
        sandbox = Sandbox(provider)
        assert sandbox._files == {}


class TestFilesEndToEnd:
    @pytest.mark.asyncio
    async def test_list_files_injected_on_setup(
        self, provider: MockProvider, tmp_path: Path
    ) -> None:
        f = tmp_path / "CLAUDE.md"
        f.write_text("You are helpful.", encoding="utf-8")
        sandbox = Sandbox(provider, files=[str(f)])
        await sandbox.setup()
        assert provider._files["/workspace/CLAUDE.md"] == "You are helpful."

    @pytest.mark.asyncio
    async def test_dict_path_files_injected_on_setup(
        self, provider: MockProvider, tmp_path: Path
    ) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("key: value", encoding="utf-8")
        sandbox = Sandbox(
            provider,
            files={"/workspace/custom/config.yaml": f},
        )
        await sandbox.setup()
        assert provider._files["/workspace/custom/config.yaml"] == "key: value"

"""Tests for project root detection."""
from __future__ import annotations

from pathlib import Path

from agento.framework.cli._project import (
    compose_file_flags,
    find_compose_file,
    find_override_file,
    find_project_root,
    update_dotenv_value,
)


class TestFindProjectRoot:
    def test_finds_agento_marker(self, tmp_path: Path):
        (tmp_path / ".agento").mkdir()
        (tmp_path / ".agento" / "project.json").write_text("{}")
        assert find_project_root(tmp_path) == tmp_path

    def test_finds_pyproject_with_agento_name(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "agento"\n')
        assert find_project_root(tmp_path) == tmp_path

    def test_ignores_pyproject_with_other_name(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "other"\n')
        assert find_project_root(tmp_path) is None

    def test_walks_up_to_parent(self, tmp_path: Path):
        (tmp_path / ".agento").mkdir()
        (tmp_path / ".agento" / "project.json").write_text("{}")
        child = tmp_path / "subdir"
        child.mkdir()
        assert find_project_root(child) == tmp_path

    def test_returns_none_when_not_found(self, tmp_path: Path):
        assert find_project_root(tmp_path) is None


class TestFindComposeFile:
    def test_finds_docker_subdir_compose(self, tmp_path: Path):
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        compose = docker_dir / "docker-compose.yml"
        compose.write_text("services: {}")
        assert find_compose_file(tmp_path) == compose

    def test_finds_root_compose(self, tmp_path: Path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("services: {}")
        assert find_compose_file(tmp_path) == compose

    def test_prefers_docker_subdir(self, tmp_path: Path):
        (tmp_path / "docker").mkdir()
        (tmp_path / "docker" / "docker-compose.yml").write_text("docker/")
        (tmp_path / "docker-compose.yml").write_text("root")
        result = find_compose_file(tmp_path)
        assert result == tmp_path / "docker" / "docker-compose.yml"

    def test_finds_dev_compose(self, tmp_path: Path):
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        compose = docker_dir / "docker-compose.dev.yml"
        compose.write_text("services: {}")
        assert find_compose_file(tmp_path) == compose

    def test_prefers_standard_over_dev(self, tmp_path: Path):
        (tmp_path / "docker").mkdir()
        (tmp_path / "docker" / "docker-compose.yml").write_text("standard")
        (tmp_path / "docker" / "docker-compose.dev.yml").write_text("dev")
        result = find_compose_file(tmp_path)
        assert result == tmp_path / "docker" / "docker-compose.yml"

    def test_returns_none_when_missing(self, tmp_path: Path):
        assert find_compose_file(tmp_path) is None


class TestFindOverrideFile:
    def test_finds_override_next_to_docker_subdir_base(self, tmp_path: Path):
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "docker-compose.yml").write_text("services: {}")
        override = docker_dir / "docker-compose.override.yml"
        override.write_text("services: {}")
        assert find_override_file(tmp_path) == override

    def test_finds_override_next_to_dev_compose(self, tmp_path: Path):
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "docker-compose.dev.yml").write_text("services: {}")
        override = docker_dir / "docker-compose.override.yml"
        override.write_text("services: {}")
        assert find_override_file(tmp_path) == override

    def test_finds_override_at_project_root(self, tmp_path: Path):
        (tmp_path / "docker-compose.yml").write_text("services: {}")
        override = tmp_path / "docker-compose.override.yml"
        override.write_text("services: {}")
        assert find_override_file(tmp_path) == override

    def test_returns_none_when_override_absent(self, tmp_path: Path):
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "docker-compose.yml").write_text("services: {}")
        assert find_override_file(tmp_path) is None

    def test_returns_none_when_base_absent(self, tmp_path: Path):
        # Stray override without a base is meaningless.
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "docker-compose.override.yml").write_text("services: {}")
        assert find_override_file(tmp_path) is None


class TestComposeFileFlags:
    def test_base_only(self, tmp_path: Path):
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        base = docker_dir / "docker-compose.yml"
        base.write_text("services: {}")
        assert compose_file_flags(tmp_path) == ["-f", str(base)]

    def test_base_and_override(self, tmp_path: Path):
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        base = docker_dir / "docker-compose.yml"
        override = docker_dir / "docker-compose.override.yml"
        base.write_text("services: {}")
        override.write_text("services: {}")
        # Order matters: base first, override second (native Compose convention).
        assert compose_file_flags(tmp_path) == ["-f", str(base), "-f", str(override)]

    def test_no_base(self, tmp_path: Path):
        assert compose_file_flags(tmp_path) == []

    def test_dev_base_and_override(self, tmp_path: Path):
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        base = docker_dir / "docker-compose.dev.yml"
        override = docker_dir / "docker-compose.override.yml"
        base.write_text("services: {}")
        override.write_text("services: {}")
        assert compose_file_flags(tmp_path) == ["-f", str(base), "-f", str(override)]


class TestUpdateDotenvValue:
    def test_updates_existing_key(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("FOO=old\nBAR=keep\n")
        update_dotenv_value(env, "FOO", "new")
        content = env.read_text()
        assert "FOO=new\n" in content
        assert "BAR=keep\n" in content

    def test_appends_missing_key(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("FOO=old\n")
        update_dotenv_value(env, "BAR", "added")
        content = env.read_text()
        assert "FOO=old\n" in content
        assert "BAR=added\n" in content

    def test_preserves_comments(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("# comment\nVER=1\n")
        update_dotenv_value(env, "VER", "2")
        content = env.read_text()
        assert "# comment\n" in content
        assert "VER=2\n" in content

    def test_does_not_match_prefix(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("AGENTO_VERSION=1\nAGENTO_VERSION_OLD=keep\n")
        update_dotenv_value(env, "AGENTO_VERSION", "2")
        content = env.read_text()
        assert "AGENTO_VERSION=2\n" in content
        assert "AGENTO_VERSION_OLD=keep\n" in content
